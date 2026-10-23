"""Hosted oraculum simulation sessions on Modal: one container per session with circus (1 robot, headless on a
virtual display), the robot stack (booster-motion, simbridge, Maximus) and its own oraculum gateway.

    hosted/stage.sh                                          # build folder from local files (nothing is pushed)
    python3 hosted/modal_session.py start [--minutes 25]     # build the image if needed, start one session, print links
    python3 hosted/modal_session.py exec sb-... "tail /tmp/circus.log"   # run a command in a session
    python3 hosted/modal_session.py stop sb-...              # stop a session early (it also stops itself after --minutes)

Sessions belong to the persistent Modal app "oraculum-hosted" (a session of a temporary `modal run` app would stop
with it). The Modal client needs Python >= 3.9.

Only HTTP leaves the container: the gateway (8080) and a browser view of the circus window (noVNC, 6080).
Each session has its own random access token: the printed links carry it (gateway ?token=, noVNC password).
"""

import os
import pathlib
import secrets
import time
import urllib.request

import modal

HERE = pathlib.Path(__file__).resolve().parent
STAGE = pathlib.Path(os.environ.get("ORACULUM_HOSTED_STAGE", "/tmp/oraculum-hosted-stage"))
PIXI = "/root/.pixi/bin/pixi"

image = (
    # The robot container of spqrbooster2026 (ROS 2 Humble, simbridge, Booster binaries in /opt/booster)
    modal.Image.from_dockerfile(STAGE / "spqrbooster2026" / "Dockerfile", context_dir=STAGE / "spqrbooster2026")
    .entrypoint([])
    .apt_install("xvfb", "x11vnc", "novnc", "websockify", "libgl1-mesa-dri", "libglx-mesa0", "libegl-mesa0",
                 "mesa-utils", "curl", "ca-certificates", "python3-yaml", "procps", "rsync", "patch")
    .run_commands("curl -fsSL https://pixi.sh/install.sh | bash")
    # circus at the pinned commit, with the robots-as-processes patch
    .add_local_dir(STAGE / "circus", "/opt/circus", copy=True)
    .run_commands(f"cd /opt/circus && {PIXI} install && JOBS=$(nproc) {PIXI} run compile")
    # Maximus from the local working tree (CPU inference: TensorRT off; CUDA libraries install without a GPU)
    .add_local_dir(STAGE / "spqrbooster2026", "/workspace", copy=True)
    .run_commands(f"cd /workspace && CONDA_OVERRIDE_CUDA=12.0 {PIXI} install")
    # LD_LIBRARY_PATH (Booster libraries, set by the Dockerfile) would give the linker an older OpenSSL than the
    # environment's libcurl needs; the runtime keeps it (supervisord.conf passes its own --library-path).
    .run_commands(f"cd /workspace && env -u LD_LIBRARY_PATH CONDA_OVERRIDE_CUDA=12.0 EXTRA_CMAKE_ARGS=-DENABLE_TENSORRT=OFF "
                  f"JOBS=$(nproc) {PIXI} run compile --skip-gcdo-update")
    # iproute2 for the per-robot veth (robot_netns.py); a late layer so it does not re-trigger the compiles above
    .apt_install("iproute2")
    # oraculum and the session scripts change most often: last layers
    .add_local_dir(STAGE / "oraculum", "/opt/oraculum", copy=True)
    .add_local_dir(HERE, "/opt/session", copy=True,
                   ignore=["__pycache__", "modal_session.py", ".ruff_cache", "launcher"])  # keep robot_netns.py
    .run_commands("gcc -shared -fPIC -O2 -Wno-unused-parameter -o /opt/session/libnort.so /opt/session/nort.c")
    # useRerun also switches on the oraculum link; with no Rerun viewer in the session, Rerun writes to /dev/null
    .run_commands("cp -r /workspace/src/app/config /opt/session/config && "
                  "sed -i 's/^useRerun: false/useRerun: true /' /opt/session/config/deploy.yaml && "
                  "grep -q '^useRerun: true' /opt/session/config/deploy.yaml && "
                  "sed -i 's|^  mode: \"connect\"|  mode: \"save\"|; s|^  savePath: .*|  savePath: \"/dev/null\"|; "
                  "s|^    rgb: true|    rgb: false|' /opt/session/config/settings.yaml && "
                  "grep -q '^  mode: \"save\"' /opt/session/config/settings.yaml")
)

APP_NAME = "oraculum-hosted"


def _wait_http(url: str, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=10).read(64)
            return True
        except Exception:  # not up yet
            time.sleep(3)
    return False


# Measured 2026-10-20: base (circus+Xvfb+gateway+noVNC) ~2.0 cores/1.3 GB; per robot ~1.6 cores/0.78 GB (flat
# walking vs rest). Billed max(request, usage), so the limits (second numbers) bound the cost.
CPU, MEMORY = (4.0, 5.0), (4096, 6144)


def _scene_robot_ips(scene_path: str) -> list:
    """Loopback IP per robot from a scene file: 10*(color+1)+player, matching robot_netns.py:robot_loopback_ip."""
    ips, cidx, in_players = [], None, False
    for raw in open(scene_path):
        s = raw.strip()
        if s.startswith("red:"):
            cidx, in_players = 0, False
        elif s.startswith("blue:"):
            cidx, in_players = 1, False
        elif s.startswith("players:"):
            in_players = True
        elif in_players and s.startswith("number:") and cidx is not None:
            ips.append(f"127.0.0.{10 * (cidx + 1) + int(s.split(':')[1].strip())}")
    return ips


def _scene_teams(scene_path: str) -> list:
    """Team numbers from a scene file (the 'number:' line right after red:/blue:, before players:)."""
    teams, after_color = [], False
    for raw in open(scene_path):
        s = raw.strip()
        if s.startswith("red:") or s.startswith("blue:"):
            after_color = True
        elif s.startswith("players:"):
            after_color = False
        elif after_color and s.startswith("number:"):
            teams.append(s.split(":")[1].strip())
            after_color = False
    return teams


def _autosize(n: int):
    """Size the sandbox to n robots: base ~2 cores/1.3 GB + ~1.6 cores each; per-robot memory includes Maximus
    growth (~18 MB/min, ~0.45 GB over a session), so ~1.3 GB each, plus 3 GB headroom on the limit."""
    cpu_req = max(4.0, round(2 + 1.7 * n))
    mem_req = max(4096, 1500 + 1300 * n)
    return (cpu_req, cpu_req + 4), (mem_req, mem_req + 3072)


def start(minutes: int = 25, idle_minutes: int = 10, block_network: bool = False,
          scene: str = "1v0.yaml", cpu=None, memory=None) -> dict:
    app = modal.App.lookup(APP_NAME, create_if_missing=True)
    t0 = time.time()
    token = secrets.token_urlsafe(16)
    base = os.path.basename(scene)
    ips = _scene_robot_ips(HERE / "scenes" / base)
    teams = _scene_teams(HERE / "scenes" / base)
    isolate = "1" if len(ips) > 1 else "0"
    if cpu is None or memory is None:
        acpu, amem = _autosize(max(1, len(ips)))
        cpu, memory = cpu or acpu, memory or amem
    print(f"scene {base}: {len(ips)} robot(s) {ips or '[default]'}; teams={teams}; isolate={isolate}; cpu={cpu} mem={memory}")
    env = {"ORACULUM_ACCESS_TOKEN": token, "SCENE": f"/opt/session/scenes/{base}",
           "ORACULUM_ISOLATE": isolate, "GC_TARGETS": ",".join(ips) if ips else "127.0.0.1"}
    if len(teams) == 2:  # two-team game -> the simulated referee runs both teams
        env["SIM_GC_TEAMS"] = ",".join(teams)
    # idle_timeout: Modal ends the sandbox when no connection through its tunnels was open for that long (an open
    # oraculum page polls /state several times per second; an open circus view holds a websocket).
    sb = modal.Sandbox.create("bash", "/opt/session/session.sh", app=app, image=image, cpu=cpu, memory=memory,
                              encrypted_ports=[8080, 6080], timeout=minutes * 60, idle_timeout=idle_minutes * 60,
                              cidr_allowlist=["127.0.0.1/32"] if block_network else None,  # Modal refuses block_network with open ports
                              secrets=[modal.Secret.from_dict(env)])
    tunnels = sb.tunnels()
    gateway, vnc = tunnels[8080].url, tunnels[6080].url
    print(f"session {sb.object_id} started in {time.time() - t0:.0f} s (stops after {minutes} min, or {idle_minutes} min with no page)")
    print(f"  image {image.object_id} (the launcher starts sessions from this id)")
    print(f"  oraculum:      {gateway}/index.html?token={token}   (then {gateway}/fleet.html)")
    print(f"  circus window: {vnc}/vnc.html?autoconnect=1&resize=scale&password={token}")
    print(f"  stop early:    python3 hosted/modal_session.py stop {sb.object_id}")
    print("gateway up" if _wait_http(f"{gateway}/state?token={token}", 120) else "gateway not answering after 120 s")
    return {"id": sb.object_id, "gateway": gateway, "vnc": vnc, "token": token}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="hosted oraculum simulation sessions on Modal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("start")
    st.add_argument("--minutes", type=int, default=25)
    st.add_argument("--idle-minutes", type=int, default=10)
    st.add_argument("--scene", default="1v0.yaml", help="scene file in hosted/scenes/ (e.g. 2v0.yaml); >1 robot auto-isolates")
    st.add_argument("--block-network", action="store_true", help="no outbound network (test: do the tunnels still work?)")
    sub.add_parser("stop").add_argument("id")
    ex = sub.add_parser("exec")
    ex.add_argument("id")
    ex.add_argument("command")
    a = ap.parse_args()
    if a.cmd == "start":
        start(a.minutes, a.idle_minutes, a.block_network, scene=a.scene)
    elif a.cmd == "stop":
        modal.Sandbox.from_id(a.id).terminate()
        print(f"session {a.id} stopped")
    else:
        p = modal.Sandbox.from_id(a.id).exec("bash", "-lc", a.command)
        print(p.stdout.read() + p.stderr.read())
