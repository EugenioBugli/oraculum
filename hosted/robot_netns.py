#!/usr/bin/env python3
"""Run one robot of a hosted session inside its own network namespace, with a userspace relay.

circus (host network namespace) forks this per robot via CIRCUS_ROBOT_LAUNCHER. The robot stack
(booster-motion + simbridge + Maximus) must be isolated per robot: it uses fixed UDP ports (joystick 10007,
camera 10008, GameController 3838) and a FastDDS domain 0 on 127.0.0.1, and booster-motion is a closed binary
with no domain knob. circus's native mode isolates each robot with a Docker container (one netns each); Modal's
gVisor refuses veth/bridge, so we reproduce that with unshare + a relay instead.

How it works (one process):
  1. BEFORE unshare, open the host-namespace sockets the gateway/circus must reach: UDP bound to this robot's
     own loopback IP 127.0.0.N (so the gateway tells robots apart by IP), and a TCP socket connected to circus.
     A file descriptor keeps the namespace it was created in, so these keep working from inside the new netns.
  2. unshare(NEWUSER|NEWNET): a fresh network namespace with its own 127.0.0.1 and its own DDS domain 0.
  3. bring lo up, open the inner 127.0.0.1 sockets, and relay datagrams/stream between the two sides.
  4. exec supervisord (the robot stack) inside the namespace.

Only --net is unshared, so /dev/shm (circus<->robot camera images) is still shared. Set ORACULUM_ISOLATE=1 to
turn this on; unset, it just execs supervisord (the unchanged single-robot path, no regression).

Env from circus (hosted/circus_process_robots.patch): TEAM_COLOR, PLAYER_NUMBER, SERVER_IP, CIRCUS_PORT.
Env from robot.sh: ORACULUM_HOST (the gateway, 127.0.0.1), the robot-stack vars, LD_PRELOAD=libnort.so.
"""
import ctypes
import os
import selectors
import socket
import struct
import subprocess
import sys
import time

CLONE_NEWUSER = 0x10000000
CLONE_NEWNET = 0x40000000

GATEWAY = os.environ.get("ORACULUM_HOST", "127.0.0.1")  # where the robot sends telemetry/camera, in the host ns
# robot.sh writes a per-robot supervisord.conf (unique log paths) and points here; default = the framework's own.
SUPERVISORD = ["/usr/bin/supervisord", "-n", "-c",
               os.environ.get("ORACULUM_SUPERVISORD_CONF", "/workspace/scripts/supervisord.conf")]

# ports the relay carries. "in"  = gateway/referee -> robot (host 127.0.0.N:p  -> inner 127.0.0.1:p)
#                          "out" = robot -> gateway        (inner 127.0.0.1:p -> host, source 127.0.0.N, to GATEWAY:p)
PORTS_IN = [10007, 10008, 3838]   # joystick, camera request, GameController
PORTS_OUT = [10006, 10009]        # telemetry, camera frames


def robot_octet() -> int:
    """A distinct last octet per robot: 10*(color+1)+player. red p2 -> 12, blue p3 -> 23."""
    color = (os.environ.get("TEAM_COLOR") or "red").strip().lower()
    cidx = {"red": 0, "blue": 1}.get(color, 2)
    player = int(os.environ.get("PLAYER_NUMBER") or "1")
    n = 10 * (cidx + 1) + player
    if not (1 < n < 255):
        raise ValueError(f"octet {n} out of range (color={color} player={player})")
    return n


def _udp(bind_ip=None, port=0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if bind_ip is not None:
        s.bind((bind_ip, port))
    s.setblocking(False)
    return s


def connect_circus(server_ip: str, port: int, deadline_s: float = 6.0):
    """Pre-connect a host-namespace TCP socket to circus, if circus has a TCP server. In shm connect-mode circus
    serves joints over /dev/shm and does not listen on this port, so this returns None and the inner listener below
    just accepts and drains simbridge's connection (which it opens unconditionally). Short deadline: no long stall."""
    end = time.time() + deadline_s
    while time.time() < end:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((server_ip, port))
            s.setblocking(False)
            return s
        except OSError:
            s.close()
            time.sleep(0.5)
    return None


def enter_netns(octet: int):
    """New user+network namespace; map root->root (so we keep CAP_NET_ADMIN over the new netns); bring up lo and
    a veth named circus0 with 10.9.0.<octet>/24. The robot's TeamMessageSender broadcasts over the first interface
    whose name contains 'circus' (UdpComm::getWifiBroadcastAddress); with only lo it falls back to 255.255.255.255,
    the send fails and Maximus dies. circus0 gives it a routable broadcast, exactly as the Docker container did."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.unshare(CLONE_NEWUSER | CLONE_NEWNET) != 0:
        e = ctypes.get_errno()
        raise OSError(e, f"unshare failed: {os.strerror(e)}")
    with open("/proc/self/setgroups", "w") as f:
        f.write("deny")
    with open("/proc/self/uid_map", "w") as f:
        f.write("0 0 1")
    with open("/proc/self/gid_map", "w") as f:
        f.write("0 0 1")
    _lo_up_netlink()  # gVisor rejects the SIOCSIFFLAGS ioctl; netlink RTM_NEWLINK works (same call `ip` makes)
    # gVisor refuses dummy interfaces but allows a veth pair inside this (user-namespace-owned) netns.
    for cmd in (["ip", "link", "add", "circus0", "type", "veth", "peer", "name", "circus1"],
                ["ip", "addr", "add", f"10.9.0.{octet}/24", "dev", "circus0"],
                ["ip", "link", "set", "circus0", "up"],
                ["ip", "link", "set", "circus1", "up"]):
        rc = subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if rc != 0:
            print(f"[netns] WARNING: {' '.join(cmd)} -> rc {rc} (team broadcast may fail)", flush=True)


def _lo_up_netlink():
    """Bring lo up with a raw NETLINK_ROUTE RTM_NEWLINK (no iproute2 dependency)."""
    nl = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 0)  # NETLINK_ROUTE
    try:
        nl.bind((0, 0))
        idx = socket.if_nametoindex("lo")
        ifinfo = struct.pack("=BxHiII", 0, 0, idx, 0x1, 0x1)      # ifinfomsg: flags=IFF_UP, change=IFF_UP
        hdr = struct.pack("=IHHII", 16 + len(ifinfo), 16, 0x1 | 0x4, 1, 0)  # RTM_NEWLINK, NLM_F_REQUEST|ACK
        nl.send(hdr + ifinfo)
        err = struct.unpack("=i", nl.recv(4096)[16:20])[0]        # nlmsgerr: 0 = success
        if err != 0:
            raise OSError(-err, f"RTM_NEWLINK lo up failed: {os.strerror(-err)}")
    finally:
        nl.close()


def run():
    octet = robot_octet()
    ip = f"127.0.0.{octet}"
    server_ip = os.environ.get("SERVER_IP", "127.0.0.1")
    circus_port = int(os.environ.get("CIRCUS_PORT") or "0")
    name = os.environ.get("ROBOT_NAME", "?")
    print(f"[netns {name}] loopback {ip}, circus {server_ip}:{circus_port}", flush=True)

    # --- host-namespace sockets (opened BEFORE unshare; they stay in the host netns) ---
    host_in = {p: _udp(ip, p) for p in PORTS_IN}      # gateway -> this robot
    host_out = _udp(ip, 0)                             # this robot -> gateway (source = 127.0.0.N)
    circus_tcp = connect_circus(server_ip, circus_port) if circus_port else None
    if circus_port and circus_tcp is None:  # normal in shm connect-mode: joints go over /dev/shm, not this TCP
        print(f"[netns {name}] circus {server_ip}:{circus_port} has no TCP server (shm mode); inner listener drains simbridge", flush=True)

    # --- into the private network namespace ---
    enter_netns(octet)

    # --- inner (127.0.0.1) sockets, opened AFTER unshare ---
    inner_out = {p: _udp("127.0.0.1", p) for p in PORTS_OUT}  # robot sends telemetry/camera here
    inner_tx = _udp()                                          # to deliver inbound datagrams to the robot
    circus_listen = None
    if circus_tcp is not None:
        circus_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        circus_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        circus_listen.bind(("127.0.0.1", circus_port))
        circus_listen.listen(4)
        circus_listen.setblocking(False)

    # --- start the robot stack inside this namespace ---
    child = subprocess.Popen(SUPERVISORD)

    _relay_loop(host_in, host_out, inner_out, inner_tx, circus_listen, circus_tcp, child)
    return child.returncode or 0


def _relay_loop(host_in, host_out, inner_out, inner_tx, circus_listen, circus_tcp, child):
    sel = selectors.DefaultSelector()
    for p, s in host_in.items():
        sel.register(s, selectors.EVENT_READ, ("in", p))
    for p, s in inner_out.items():
        sel.register(s, selectors.EVENT_READ, ("out", p))
    if circus_listen is not None:
        sel.register(circus_listen, selectors.EVENT_READ, ("accept", None))
    tcp_inner = None       # the accepted simbridge connection
    tcp_out_reg = False    # whether circus_tcp is registered (register it once, on the first accept)
    while True:
        if child.poll() is not None:
            break
        for key, _ in sel.select(timeout=1.0):
            kind, port = key.data
            try:
                if kind == "in":          # gateway/referee -> robot
                    data, _ = key.fileobj.recvfrom(65535)
                    inner_tx.sendto(data, ("127.0.0.1", port))
                elif kind == "out":       # robot -> gateway (source stays 127.0.0.N)
                    data, _ = key.fileobj.recvfrom(65535)
                    host_out.sendto(data, (GATEWAY, port))
                elif kind == "accept":    # simbridge connected to circus (inner); splice to the host circus socket
                    conn, _ = circus_listen.accept()
                    conn.setblocking(False)
                    if tcp_inner is not None:
                        try:
                            sel.unregister(tcp_inner)
                        except KeyError:
                            pass
                        tcp_inner.close()
                    tcp_inner = conn
                    sel.register(tcp_inner, selectors.EVENT_READ, ("tcp_in", None))
                    if circus_tcp is not None and not tcp_out_reg:  # register the circus side once
                        sel.register(circus_tcp, selectors.EVENT_READ, ("tcp_out", None))
                        tcp_out_reg = True
                elif kind == "tcp_in":    # simbridge -> circus (or drain, in shm mode where circus has no TCP)
                    b = key.fileobj.recv(65535)
                    if not b:
                        raise ConnectionError
                    if circus_tcp is not None:
                        circus_tcp.sendall(b)
                elif kind == "tcp_out":   # circus -> simbridge
                    b = key.fileobj.recv(65535)
                    if not b:
                        raise ConnectionError
                    tcp_inner.sendall(b)
            except (BlockingIOError, InterruptedError):
                pass
            except (ConnectionError, OSError):
                # a dropped TCP half: unregister the socket that failed; simbridge can reconnect to the inner listener
                if kind in ("tcp_in", "tcp_out"):
                    try:
                        sel.unregister(key.fileobj)
                    except KeyError:
                        pass
                    try:
                        key.fileobj.close()
                    except OSError:
                        pass
                    if key.fileobj is tcp_inner:
                        tcp_inner = None
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.terminate()


def selftest():
    """Relay forwarding logic without unshare: a datagram each way must come through. Runs anywhere."""
    gw = _udp("127.0.0.1", 0)
    gw_port = gw.getsockname()[1]
    # fake the two sides: 'in' side host socket, 'out' side inner socket
    hin = _udp("127.0.0.1", 0)
    out = _udp("127.0.0.1", 0)
    tx = _udp()
    robot = _udp("127.0.0.1", 0)  # pretends to be the robot listening for inbound
    # inbound: data arriving on hin must be delivered to robot via tx
    global GATEWAY
    GATEWAY = "127.0.0.1"
    sel = selectors.DefaultSelector()
    sel.register(hin, selectors.EVENT_READ, ("in", robot.getsockname()[1]))
    sel.register(out, selectors.EVENT_READ, ("out", gw_port))
    hin.setblocking(True)
    out.setblocking(True)
    # simulate one inbound and one outbound
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.sendto(b"IN", hin.getsockname())
    sender.sendto(b"OUT", out.getsockname())
    seen = set()
    for _ in range(4):
        for key, _ in sel.select(timeout=1.0):
            kind, port = key.data
            data, _ = key.fileobj.recvfrom(65535)
            if kind == "in":
                tx.sendto(data, ("127.0.0.1", port))
            else:
                _udp().sendto(data, (GATEWAY, port))
        if seen >= {"IN", "OUT"}:
            break
        robot.setblocking(False)
        gw.setblocking(False)
        try:
            seen.add(robot.recvfrom(16)[0].decode())
        except BlockingIOError:
            pass
        try:
            seen.add(gw.recvfrom(16)[0].decode())
        except BlockingIOError:
            pass
    assert seen == {"IN", "OUT"}, f"relay selftest failed, saw {seen}"
    print("relay selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif os.environ.get("ORACULUM_ISOLATE") == "1":
        sys.exit(run())
    else:
        os.execv(SUPERVISORD[0], SUPERVISORD)  # unchanged single-robot path
