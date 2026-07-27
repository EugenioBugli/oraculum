"""Figure setup, animation loop, and entry point — with animation on separate thread.

This version moves animation updates to a background thread to prevent freezing
when dragging the window. The main thread only handles matplotlib event loop.
"""

import os
import sys
import threading
import time
import atexit

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from .config import load_config, load_teams
from .field import draw_field
from matplotlib.patches import Circle, FancyBboxPatch
from .agents import create_agents, make_agent_artists, update_agent_artists, Ball, draw_agent_legend
from .socket_client import UDPReceiver
from .gc_client import GCReceiver
from .physical_joystick import PhysicalJoystick


_ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")

_SET_PLAY_NAMES = {
    1: "DIRECT FREE KICK",
    2: "INDIRECT FREE KICK",
    3: "PENALTY KICK",
    4: "THROW IN",
    5: "GOAL KICK",
    6: "CORNER KICK",
}

_SEP_XS      = [0.17, 0.27, 0.42, 0.63]
_COL_CENTERS = [0.085, 0.22, 0.345, 0.525]
_COL_LABELS  = ["STATE", "HALF", "TIME", "EVENT"]
_SCORE_X_L   = 0.695
_SCORE_X_MID = 0.815
_SCORE_X_R   = 0.935
_Y_BOT, _Y_MID, _Y_TOP = 1.005, 1.055, 1.095
_Y_HDR = (_Y_MID + _Y_TOP) / 2
_Y_VAL = (_Y_BOT + _Y_MID) / 2


# Global state for cleanup
_cleanup_state = {"receiver": None, "gc_receiver": None, "fig": None, "stop_event": None, "phys_joy": None, "control_server": None}


def _parse_color(c_arr):
    if c_arr and len(c_arr) >= 3:
        return (c_arr[0]/255.0, c_arr[1]/255.0, c_arr[2]/255.0)
    return "white"


def _visible_color(css: str) -> str:
    """Ensure a CSS color name is legible on a dark background."""
    return "#888888" if css.lower() in ("black", "#000", "#000000") else css


def _cleanup_resources():
    """Cleanup handler called at exit."""
    print("\n[Cleanup] Stopping animation and receivers...")
    if _cleanup_state["stop_event"] is not None:
        _cleanup_state["stop_event"].set()

    if _cleanup_state["receiver"] is not None:
        try:
            _cleanup_state["receiver"].stop()
            print("[Cleanup] UDP receiver stopped")
        except Exception as e:
            print(f"[Cleanup] Error stopping receiver: {e}")

    if _cleanup_state["gc_receiver"] is not None:
        try:
            _cleanup_state["gc_receiver"].stop()
            print("[Cleanup] GC receiver stopped")
        except Exception as e:
            print(f"[Cleanup] Error stopping gc_receiver: {e}")

    if _cleanup_state["phys_joy"] is not None:
        try:
            _cleanup_state["phys_joy"].stop()
            print("[Cleanup] Physical joystick reader stopped")
        except Exception as e:
            print(f"[Cleanup] Error stopping physical joystick: {e}")

    if _cleanup_state["fig"] is not None:
        try:
            plt.close(_cleanup_state["fig"])
        except Exception:
            pass

    print("[Cleanup] Done.")


def _make_gc_artists(ax):
    """Build the static GC info panel above the field axes and return mutable text artists."""
    tr = ax.transAxes
    z  = dict(zorder=7)

    ax.add_patch(FancyBboxPatch(
        (0.0, _Y_BOT), 1.0, _Y_TOP - _Y_BOT,
        boxstyle="square,pad=0", facecolor="#252525", edgecolor="none",
        transform=tr, clip_on=False, zorder=5,
    ))

    lkw = dict(transform=tr, clip_on=False, color="#555555", linewidth=0.8, zorder=6)
    for x in _SEP_XS:
        ax.plot([x, x], [_Y_BOT, _Y_TOP], **lkw)
    for y in (_Y_BOT, _Y_MID, _Y_TOP):
        ax.plot([0.0, 1.0], [y, y], **lkw)

    hkw = dict(transform=tr, clip_on=False, ha="center", va="center",
               fontfamily="monospace", color="#666666", fontsize=8,
               fontweight="bold", **z)
    for label, x in zip(_COL_LABELS, _COL_CENTERS):
        ax.text(x, _Y_HDR, label, **hkw)
    ax.text(_SCORE_X_MID, _Y_HDR, "SCORE", **hkw)

    vkw = dict(transform=tr, clip_on=False, ha="center", va="center",
               fontfamily="monospace", color="#dddddd", fontsize=10, **z)
    state_t = ax.text(_COL_CENTERS[0], _Y_VAL, "INITIAL", **vkw)
    half_t  = ax.text(_COL_CENTERS[1], _Y_VAL, "\u2014",  **vkw)
    time_t  = ax.text(_COL_CENTERS[2], _Y_VAL, "\u2014",  **vkw)
    event_t = ax.text(_COL_CENTERS[3], _Y_VAL, "",         **vkw)

    skw = dict(transform=tr, clip_on=False, va="center",
               fontfamily="monospace", fontsize=8, **z)
    team0_t = ax.text(_SCORE_X_L,   _Y_VAL, "", color="#dddddd", ha="right",  **skw)
    nums_t  = ax.text(_SCORE_X_MID, _Y_VAL, "\u2014", color="#dddddd", ha="center", **skw)
    team1_t = ax.text(_SCORE_X_R,   _Y_VAL, "", color="#dddddd", ha="left",   **skw)

    return state_t, half_t, time_t, event_t, team0_t, nums_t, team1_t


def _update_gc_artists(artists, gc, teams_map: dict) -> None:
    state_t, half_t, time_t, event_t, team0_t, nums_t, team1_t = artists

    half = "1st" if gc.first_half else "2nd"
    mins, secs = divmod(max(gc.secs_remaining, 0), 60)

    if gc.set_play != 0:
        event = _SET_PLAY_NAMES.get(gc.set_play, str(gc.set_play))
    elif gc.game_phase != 0:
        event = gc.phase_name
    else:
        event = ""

    state_t.set_text(gc.state_name)
    half_t.set_text(half)
    time_t.set_text(f"{mins:02d}:{secs:02d}")
    event_t.set_text(event)

    if len(gc.teams) == 2:
        t0, t1 = gc.teams[0], gc.teams[1]
        info0 = teams_map.get(t0.team_number, {})
        info1 = teams_map.get(t1.team_number, {})
        n0 = info0.get("name", str(t0.team_number))[:13]
        n1 = info1.get("name", str(t1.team_number))[:13]
        cols0 = info0.get("colors", [])
        cols1 = info1.get("colors", [])
        c0 = _visible_color(cols0[t0.field_player_colour]) if t0.field_player_colour < len(cols0) else "#dddddd"
        c1 = _visible_color(cols1[t1.field_player_colour]) if t1.field_player_colour < len(cols1) else "#dddddd"
        team0_t.set_text(n0);  team0_t.set_color(c0)
        nums_t.set_text(f"{t0.score}  \u2014  {t1.score}")
        team1_t.set_text(n1);  team1_t.set_color(c1)


def main() -> None:
    root = os.path.abspath(_ROOT_DIR)

    try:
        cfg, field, field_name = load_config(root)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    # Register cleanup at exit
    atexit.register(_cleanup_resources)

    teams_map = load_teams(root)

    disp = cfg.get("display", {})
    title = disp.get("title", "Field Viewer")

    W = field["width"]
    H = field["height"]
    hw, hh = W / 2, H / 2
    margin = max(W, H) * 0.06

    # --- Figure setup ---
    fig_w = 14
    fig_h_field = 10 * (H + 2 * margin) / (W + 2 * margin)
    legend_h = 0.75
    fig = plt.figure(figsize=(fig_w, fig_h_field + legend_h))

    # Store reference for cleanup
    _cleanup_state["fig"] = fig

    active_agents = {}
    text_records = {}
    drawings_filters = {}
    drawings_y_positions = []
    robot_stops_positions = []
    agent_size = min(W, H) * 0.032

    ax = fig.add_axes([0.02, 0.20, 0.68, 0.75])
    ax_leg = fig.add_axes([0.02, 0.05, 0.68, 0.12])

    fig.patch.set_facecolor("#1e1e1e")
    fig.canvas.manager.set_window_title(title)
    try:
        fig.canvas.manager.window.minsize(int(fig_w * fig.dpi), int((fig_h_field + legend_h) * fig.dpi))
    except AttributeError:
        pass

    draw_field(ax, field, cfg)

    ax.set_xlim(-hw - margin, hw + margin)
    ax.set_ylim(-hh - margin, hh + margin)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.suptitle(title,
                 color="#822433", fontsize=22, fontweight="bold",
                 fontfamily="serif")
    gc_artists = _make_gc_artists(ax)

    # --- Sidebar Control Widgets ---
    from matplotlib.widgets import Button, Slider, CheckButtons
    import socket

    # Vertical divider line
    fig.add_artist(plt.Line2D([0.72, 0.72], [0.02, 0.98], color="#444444", linewidth=1.5, transform=fig.transFigure))

    # GC Override Title & Status
    fig.text(0.74, 0.95, "GAME CONTROLLER OVERRIDE", color="#00a0b0", fontsize=10, fontweight="bold", fontfamily="monospace")
    gc_status_text = fig.text(0.74, 0.92, "GC Status: OFFLINE", color="#ff4444", fontsize=9, fontfamily="monospace")

    def send_sim_command(cmd_str):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(cmd_str.encode("utf-8"), ("127.0.0.1", 3840))
            sock.close()
            print(f"[Oraculum] Sent command to simulator: {cmd_str}")
        except Exception as e:
            print(f"[Oraculum] Error sending command to simulator: {e}")

    def send_stop_to_robot(ip):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if ip == "255.255.255.255":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            payload = {"lb": True, "rb": True, "x": True}
            sock.sendto(json.dumps(payload).encode("utf-8"), (ip, 10007))
            sock.close()
            print(f"[Oraculum] Sent SIGTERM stop combo to {ip}:10007")
        except Exception as e:
            print(f"[Oraculum] Error sending stop command: {e}")

    # GC State Buttons
    ax_btn_init = fig.add_axes([0.74, 0.86, 0.11, 0.035])
    btn_init = Button(ax_btn_init, "Initial", color="#252525", hovercolor="#353535")
    btn_init.label.set_color("#ffffff")
    btn_init.label.set_fontsize(8)
    btn_init.on_clicked(lambda e: send_sim_command("initial"))

    ax_btn_ready = fig.add_axes([0.86, 0.86, 0.11, 0.035])
    btn_ready = Button(ax_btn_ready, "Ready", color="#252525", hovercolor="#353535")
    btn_ready.label.set_color("#ffffff")
    btn_ready.label.set_fontsize(8)
    btn_ready.on_clicked(lambda e: send_sim_command("ready"))

    ax_btn_set = fig.add_axes([0.74, 0.81, 0.11, 0.035])
    btn_set = Button(ax_btn_set, "Set", color="#252525", hovercolor="#353535")
    btn_set.label.set_color("#ffffff")
    btn_set.label.set_fontsize(8)
    btn_set.on_clicked(lambda e: send_sim_command("set"))

    ax_btn_play = fig.add_axes([0.86, 0.81, 0.11, 0.035])
    btn_play = Button(ax_btn_play, "Play", color="#252525", hovercolor="#353535")
    btn_play.label.set_color("#ffffff")
    btn_play.label.set_fontsize(8)
    btn_play.on_clicked(lambda e: send_sim_command("playing"))

    ax_btn_finish = fig.add_axes([0.74, 0.76, 0.23, 0.035])
    btn_finish = Button(ax_btn_finish, "Finish", color="#252525", hovercolor="#353535")
    btn_finish.label.set_color("#ffffff")
    btn_finish.label.set_fontsize(8)
    btn_finish.on_clicked(lambda e: send_sim_command("finish"))

    def update_sidebar_gc_status(ext_gc_online):
        if ext_gc_online:
            gc_status_text.set_text("GC Status: ONLINE")
            gc_status_text.set_color("#00ff00")
            for ax_b, btn in [(ax_btn_init, btn_init), (ax_btn_ready, btn_ready), (ax_btn_set, btn_set), (ax_btn_play, btn_play), (ax_btn_finish, btn_finish)]:
                btn.eventson = False
                ax_b.set_facecolor("#444444")
        else:
            gc_status_text.set_text("GC Status: OFFLINE")
            gc_status_text.set_color("#ff4444")
            for ax_b, btn in [(ax_btn_init, btn_init), (ax_btn_ready, btn_ready), (ax_btn_set, btn_set), (ax_btn_play, btn_play), (ax_btn_finish, btn_finish)]:
                btn.eventson = True
                ax_b.set_facecolor("#252525")

    # Manual Override & E-Stop Title
    fig.text(0.74, 0.835, "MANUAL OVERRIDE & E-STOP", color="#00a0b0", fontsize=10, fontweight="bold", fontfamily="monospace")

    # Override Toggle Button
    ax_btn_override = fig.add_axes([0.74, 0.795, 0.23, 0.03])
    btn_override = Button(ax_btn_override, "Override: OFF", color="#252525", hovercolor="#353535")
    btn_override.label.set_color("#ffffff")
    btn_override.label.set_fontsize(8)

    # Sliders
    ax_sld_vx = fig.add_axes([0.79, 0.75, 0.18, 0.02])
    sld_vx = Slider(ax_sld_vx, "Vx", -1.0, 1.0, valinit=0.0, color="#00a0b0", valfmt="%.2f")
    sld_vx.label.set_color("#ffffff")
    sld_vx.label.set_fontsize(7)
    sld_vx.valtext.set_color("#ffffff")
    sld_vx.valtext.set_fontsize(7)

    ax_sld_vy = fig.add_axes([0.79, 0.71, 0.18, 0.02])
    sld_vy = Slider(ax_sld_vy, "Vy", -1.0, 1.0, valinit=0.0, color="#00a0b0", valfmt="%.2f")
    sld_vy.label.set_color("#ffffff")
    sld_vy.label.set_fontsize(7)
    sld_vy.valtext.set_color("#ffffff")
    sld_vy.valtext.set_fontsize(7)

    ax_sld_vt = fig.add_axes([0.79, 0.67, 0.18, 0.02])
    sld_vt = Slider(ax_sld_vt, "Vth", -1.0, 1.0, valinit=0.0, color="#00a0b0", valfmt="%.2f")
    sld_vt.label.set_color("#ffffff")
    sld_vt.label.set_fontsize(7)
    sld_vt.valtext.set_color("#ffffff")
    sld_vt.valtext.set_fontsize(7)

    def on_override_clicked(e):
        enabled = not key_state.get("isManual", False)
        key_state["isManual"] = enabled
        btn_override.label.set_text(f"Override: {'ON' if enabled else 'OFF'}")
        ax_btn_override.set_facecolor("#00a0b0" if enabled else "#252525")
        print(f"[Manual Control] Override: {enabled}")
        fig.canvas.draw_idle()
    btn_override.on_clicked(on_override_clicked)

    sld_vx.on_changed(lambda val: key_state.update({"ly": val}))
    sld_vy.on_changed(lambda val: key_state.update({"lx": val}))
    sld_vt.on_changed(lambda val: key_state.update({"rx": val}))

    # Action Buttons
    ax_btn_stop = fig.add_axes([0.74, 0.62, 0.11, 0.03])
    btn_stop = Button(ax_btn_stop, "Stop All", color="#822433", hovercolor="#a13243")
    btn_stop.label.set_color("#ffffff")
    btn_stop.label.set_fontsize(8)

    def on_stop_clicked(e):
        from tkinter import messagebox
        if messagebox.askyesno("Confirm Stop All", "Are you sure you want to STOP all robots? This will terminate their main control loops."):
            for (agent_ip, _) in active_agents.keys():
                send_stop_to_robot(agent_ip)
            send_stop_to_robot("255.255.255.255")
            print("[Oraculum] Sent global stop signal to all robots.")
    btn_stop.on_clicked(on_stop_clicked)

    ax_btn_estop = fig.add_axes([0.86, 0.62, 0.11, 0.03])
    btn_estop = Button(ax_btn_estop, "E-STOP", color="#822433", hovercolor="#a13243")
    btn_estop.label.set_color("#ffffff")
    btn_estop.label.set_fontsize(8)
    btn_estop.label.set_weight("bold")

    def on_estop_clicked(e):
        print("[Emergency Stop] TRIGGERED!")
        key_state.update({"rb": True, "rt": True, "lx": 0.0, "ly": 0.0, "rx": 0.0})
        sld_vx.set_val(0.0)
        sld_vy.set_val(0.0)
        sld_vt.set_val(0.0)
    btn_estop.on_clicked(on_estop_clicked)

    # Robot Info & Text Data Pane
    fig.text(0.74, 0.575, "ROBOT INFO & TEXT DATA", color="#00a0b0", fontsize=10, fontweight="bold", fontfamily="monospace")
    ax_robot_info = fig.add_axes([0.74, 0.32, 0.23, 0.24])
    ax_robot_info.axis("off")
    ax_robot_info.set_facecolor("#1a1a1a")

    text_records = {}  # key: (agent_id, path) -> text_value

    def draw_robot_info():
        ax_robot_info.clear()
        ax_robot_info.axis("off")
        ax_robot_info.set_facecolor("#1a1a1a")
        
        sorted_agents_keys = sorted(active_agents.keys(), key=lambda k: k[1])
        
        if not sorted_agents_keys:
            ax_robot_info.text(0.05, 0.9, "No active robots detected.", color="#888888", fontsize=8, transform=ax_robot_info.transAxes)
            return
            
        y = 0.92
        dy = 0.09
        for ip, agent_id in sorted_agents_keys:
            entry = active_agents[(ip, agent_id)]
            agent = entry['agent']
            
            # Print Robot Header
            ax_robot_info.text(0.05, y, f"Robot {agent_id} ({agent.role})", color=agent.color, fontsize=8, fontweight="bold", va="center", transform=ax_robot_info.transAxes)
            y -= dy
            if y < 0.05:
                break
                
            # Filter and print text records for this robot
            robot_texts = {path: val for (a_id, path), val in text_records.items() if a_id == agent_id}
            if not robot_texts:
                ax_robot_info.text(0.12, y, "No telemetry texts.", color="#555555", fontsize=7.5, fontfamily="monospace", va="center", transform=ax_robot_info.transAxes)
                y -= dy
                if y < 0.05:
                    break
            else:
                for path in sorted(robot_texts.keys()):
                    val = robot_texts[path]
                    display_path = path if len(path) < 15 else "..." + path[-12:]
                    display_val = val if len(val) < 15 else val[:12] + "..."
                    line_str = f"  {display_path}: {display_val}"
                    ax_robot_info.text(0.10, y, line_str, color="#ffffff", fontsize=7.5, fontfamily="monospace", va="center", transform=ax_robot_info.transAxes)
                    y -= dy
                    if y < 0.05:
                        break
            
            y -= 0.02
            if y < 0.05:
                break

    # Drawings Filter Checkbox List
    fig.text(0.74, 0.285, "ROBOT DRAWINGS FILTER", color="#00a0b0", fontsize=10, fontweight="bold", fontfamily="monospace")
    ax_drawings_list = fig.add_axes([0.74, 0.05, 0.23, 0.22])
    ax_drawings_list.axis("off")
    ax_drawings_list.set_facecolor("#1a1a1a")



    def draw_drawings_checklist():
        ax_drawings_list.clear()
        ax_drawings_list.axis("off")
        ax_drawings_list.set_facecolor("#1a1a1a")
        
        nonlocal drawings_y_positions, robot_stops_positions
        drawings_y_positions = []
        robot_stops_positions = []
        
        sorted_agents_keys = sorted(active_agents.keys(), key=lambda k: k[1])
        
        if not sorted_agents_keys:
            ax_drawings_list.text(0.05, 0.9, "No active robots detected.", color="#888888", fontsize=8, transform=ax_drawings_list.transAxes)
            return
            
        y = 0.92
        dy = 0.08
        for ip, agent_id in sorted_agents_keys:
            entry = active_agents[(ip, agent_id)]
            agent = entry['agent']
            
            # 1. Draw Robot Header
            header_text = f"Robot {agent_id} ({agent.role}, {agent.state})"
            ax_drawings_list.text(0.05, y, header_text, color=agent.color, fontsize=8, fontweight="bold", va="center", transform=ax_drawings_list.transAxes)
            
            # 2. Draw "STOP" Button for this robot
            rect_stop = plt.Rectangle((0.72, y - 0.025), 0.23, 0.05, facecolor="#822433", edgecolor="#993333", linewidth=1, transform=ax_drawings_list.transAxes)
            ax_drawings_list.add_patch(rect_stop)
            ax_drawings_list.text(0.835, y, "STOP", color="#ffffff", fontsize=7, fontweight="bold", ha="center", va="center", transform=ax_drawings_list.transAxes)
            robot_stops_positions.append((y - 0.03, y + 0.03, ip, agent_id))
            
            y -= dy
            if y < 0.05:
                break
                
            # 3. Draw nested drawings
            robot_prefix = f"R{agent_id}: "
            robot_drawings = [p for p in drawings_filters.keys() if p.startswith(robot_prefix)]
            
            for path_key in sorted(robot_drawings):
                enabled = drawings_filters[path_key]
                drawing_name = path_key[len(robot_prefix):]
                
                rect_color = "#00a0b0" if enabled else "#444444"
                rect = plt.Rectangle((0.12, y - 0.02), 0.045, 0.04, facecolor=rect_color, edgecolor="#666666", linewidth=1, transform=ax_drawings_list.transAxes)
                ax_drawings_list.add_patch(rect)
                
                if enabled:
                    ax_drawings_list.text(0.1425, y, "X", color="#ffffff", fontsize=6, fontweight="bold", ha="center", va="center", transform=ax_drawings_list.transAxes)
                
                text_color = "#ffffff" if enabled else "#888888"
                display_path = drawing_name if len(drawing_name) < 18 else "..." + drawing_name[-15:]
                ax_drawings_list.text(0.20, y, display_path, color=text_color, fontsize=7, fontfamily="monospace", va="center", transform=ax_drawings_list.transAxes)
                
                drawings_y_positions.append((y - 0.03, y + 0.03, path_key))
                y -= dy
                if y < 0.05:
                    break
            
            y -= 0.02
            if y < 0.05:
                break

    def on_checklist_click(event):
        if event.inaxes == ax_drawings_list:
            click_y = event.ydata
            
            # Check if clicked a STOP button
            for y_min, y_max, ip, agent_id in robot_stops_positions:
                if y_min <= click_y <= y_max and event.xdata >= 0.7:
                    from tkinter import messagebox
                    if messagebox.askyesno("Confirm Stop", f"Are you sure you want to STOP Robot {agent_id}? This will terminate its main control loop."):
                        send_stop_to_robot(ip)
                    return
            
            # Check if clicked a drawing checkbox
            for y_min, y_max, path in drawings_y_positions:
                if y_min <= click_y <= y_max and event.xdata <= 0.2:
                    drawings_filters[path] = not drawings_filters[path]
                    
                    disabled = []
                    for p_key, enabled in drawings_filters.items():
                        if not enabled:
                            parts = p_key.split(": ", 1)
                            if len(parts) == 2:
                                disabled.append(parts[1])
                                
                    disabled_str = "," + ",".join(disabled) + "," if disabled else ""
                    
                    try:
                        payload = {"disabled_drawings": disabled_str}
                        import urllib.request
                        data_bytes = json.dumps(payload).encode('utf-8')
                        req = urllib.request.Request("http://localhost:8080/control", data=data_bytes, headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(req, timeout=0.1) as f:
                            f.read()
                    except Exception as e:
                        print(f"[Drawings Filter] Error posting filter: {e}")
                        
                    draw_drawings_checklist()
                    fig.canvas.draw_idle()
                    break

    fig.canvas.mpl_connect('button_press_event', on_checklist_click)
    draw_drawings_checklist()

    # --- Decoupled Control Server Integration ---
    from .control_server import ControlServer
    import urllib.request
    import json

    use_http = False
    server_port = 8080

    def check_port_in_use(port):
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0

    control_server = None
    if check_port_in_use(server_port):
        print(f"[*] Control server already running on port {server_port}. Connecting via HTTP API.")
        use_http = True
    else:
        print(f"[*] Starting local in-process Control Server.")
        control_server = ControlServer()
        control_server.start()
        _cleanup_state["control_server"] = control_server


    # --- Ball ---
    ball_color = disp.get("ball_color", "white")
    ball = Ball(x=0.0, y=0.0, vx=2.0, vy=1.3,
                radius=field["ball_radius"], color=ball_color)
    ball_patch = Circle((ball.x, ball.y), ball.radius,
                        facecolor=ball.color, edgecolor="black", linewidth=1, zorder=6)
    if disp.get("show_ball", True):
        ax.add_patch(ball_patch)

    # Cache for debug drawings
    drawing_artists = []

    # --- Animation on separate thread ---
    dt = 0.04
    stop_event = threading.Event()
    _cleanup_state["stop_event"] = stop_event

    def check_drawing_condition(cond, agent):
        if not cond:
            return True
        try:
            context = {
                'role': agent.role,
                'state': agent.state,
                'x': agent.x,
                'y': agent.y,
                'angle': agent.angle
            }
            return bool(eval(cond, {"__builtins__": None}, context))
        except Exception as e:
            print(f"[Condition Eval] Error: {e}")
            return True

    def animation_thread():
        """Run animation updates in background thread (no main thread blocking)."""
        from .socket_client import GameStateMsg
        state_url = "http://localhost:8080/state"
        
        while not stop_event.is_set():
            try:
                msg = None
                gc_data = None

                if use_http:
                    try:
                        with urllib.request.urlopen(state_url, timeout=0.1) as response:
                            state_dict = json.loads(response.read().decode('utf-8'))
                            msg = GameStateMsg.from_dict(state_dict)
                            gc_dict = state_dict.get("gamecontroller")
                            if gc_dict:
                                class DummyGC:
                                    pass
                                gc_data = DummyGC()
                                gc_data.state_name = gc_dict.get("state", "INITIAL")
                                gc_data.secs_remaining = gc_dict.get("secsRemaining", 0)
                                gc_data.kickingTeam = gc_dict.get("kickingTeam", 0)
                                gc_data.set_play = 0
                                gc_data.game_phase = 0
                                gc_data.first_half = True
                                
                                class DummyTeam:
                                    def __init__(self, score, num):
                                        self.score = score
                                        self.team_number = num
                                        self.field_player_colour = 0
                                scores = gc_dict.get("score", [0, 0])
                                own_team_num = cfg.get("game_controller", {}).get("own_team", 19)
                                gc_data.teams = [DummyTeam(scores[0], own_team_num), DummyTeam(scores[1], 0)]
                    except Exception:
                        pass
                else:
                    if control_server:
                        msg = control_server.udp_receiver.latest()
                        gc_data = control_server.gc_receiver.latest()

                # Determine external GC status
                ext_gc_online = False
                if use_http:
                    if 'gc_dict' in locals() and gc_dict:
                        ext_gc_online = gc_dict.get("external_gc_online", False)
                else:
                    if control_server:
                        ext_gc_online = control_server.gc_receiver.external_gc_online
                update_sidebar_gc_status(ext_gc_online)

                if gc_data is not None:
                    _update_gc_artists(gc_artists, gc_data, teams_map)

                if msg is not None:
                    # Update dynamic checklist filters
                    checklist_changed = False
                    for dr in msg.drawings:
                        path_key = f"R{dr.agent_id}: {dr.path}"
                        if path_key not in drawings_filters:
                            drawings_filters[path_key] = True
                            checklist_changed = True
                    if checklist_changed:
                        draw_drawings_checklist()

                    legend_changed = False
                    for agent_msg in msg.agents:
                        agent_ip = getattr(agent_msg, "ip", "") or ""
                        key = (agent_ip, agent_msg.id)
                        if key not in active_agents:
                            from .agents import Agent, make_agent_artists
                            new_agent = Agent(
                                x=agent_msg.x,
                                y=agent_msg.y,
                                speed=0.0,
                                angle=agent_msg.angle,
                                color=agent_msg.color,
                                role=agent_msg.role,
                                state=agent_msg.state,
                                id=agent_msg.id
                            )
                            body, text = make_agent_artists(ax, new_agent, agent_msg.id - 1, agent_size)
                            active_agents[key] = {
                                'agent': new_agent,
                                'artists': (body, text)
                            }
                            legend_changed = True
                        else:
                            entry = active_agents[key]
                            a = entry['agent']
                            a.x, a.y, a.angle = agent_msg.x, agent_msg.y, agent_msg.angle
                            if a.role != agent_msg.role or a.state != agent_msg.state or a.color != agent_msg.color:
                                a.role, a.state, a.color = agent_msg.role, agent_msg.state, agent_msg.color
                                legend_changed = True
                            from .agents import update_agent_artists
                            update_agent_artists(a, entry['artists'][0], entry['artists'][1], agent_size)

                    if legend_changed:
                        ax_leg.clear()
                        sorted_agents = sorted(
                            [v['agent'] for v in active_agents.values()],
                            key=lambda a: (a.color, a.id)
                        )
                        if sorted_agents:
                            from .agents import draw_agent_legend
                            draw_agent_legend(ax_leg, sorted_agents)
                        draw_drawings_checklist()

                    # Update text records and draw them
                    texts_changed = False
                    if hasattr(msg, "texts") and msg.texts:
                        for t in msg.texts:
                            k = (t.agent_id, t.path)
                            if text_records.get(k) != t.text:
                                text_records[k] = t.text
                                texts_changed = True
                    if texts_changed or legend_changed:
                        draw_robot_info()

                    if msg.ball is not None:
                        ball.x, ball.y = msg.ball.x, msg.ball.y

                    # Render debug drawings
                    for artist in drawing_artists:
                        try:
                            artist.remove()
                        except Exception:
                            pass
                    drawing_artists.clear()

                    from matplotlib.patches import Circle, Rectangle, Arc
                    for dr in msg.drawings:
                        path_key = f"R{dr.agent_id}: {dr.path}"
                        if path_key in drawings_filters and not drawings_filters[path_key]:
                            continue

                        # Find corresponding agent for condition check
                        agent = None
                        for (ip, a_id), entry in active_agents.items():
                            if a_id == dr.agent_id:
                                agent = entry['agent']
                                break
                        
                        if agent is not None and getattr(dr, "condition", ""):
                            if not check_drawing_condition(dr.condition, agent):
                                continue

                        color = _parse_color(dr.color)
                        size = dr.size
                        coords = dr.coords
                        if not coords:
                            continue

                        # Determine transform (viewport vs field)
                        is_viewport = getattr(dr, "frame", "field") == "viewport"
                        tf = ax.transAxes if is_viewport else ax.transData

                        if dr.type == "point":
                            artist = ax.plot(coords[0], coords[1], marker='o', color=color, markersize=size * 200, transform=tf, zorder=6)[0]
                            drawing_artists.append(artist)
                        elif dr.type == "circle":
                            artist = Circle((coords[0], coords[1]), size, facecolor='none', edgecolor=color, linewidth=1.5, transform=tf, zorder=6)
                            ax.add_patch(artist)
                            drawing_artists.append(artist)
                        elif dr.type == "line" and len(coords) >= 4:
                            artist = ax.plot([coords[0], coords[2]], [coords[1], coords[3]], color=color, linewidth=size * 50, transform=tf, zorder=6)[0]
                            drawing_artists.append(artist)
                        elif dr.type == "box" and len(coords) >= 4:
                            cx, cy, w, h = coords[0], coords[1], coords[2], coords[3]
                            artist = Rectangle((cx - w/2, cy - h/2), w, h, facecolor='none', edgecolor=color, linewidth=1.5, transform=tf, zorder=6)
                            ax.add_patch(artist)
                            drawing_artists.append(artist)
                        elif dr.type == "arc" and len(coords) >= 2:
                            cx, cy = coords[0], coords[1]
                            radius = coords[2] if len(coords) > 2 else size
                            start = coords[3] if len(coords) > 3 else 0
                            end = coords[4] if len(coords) > 4 else 360
                            artist = Arc((cx, cy), radius * 2, radius * 2, angle=0, theta1=start, theta2=end, color=color, linewidth=1.5, transform=tf, zorder=6)
                            ax.add_patch(artist)
                            drawing_artists.append(artist)

                ball_patch.set_center((ball.x, ball.y))

                fig.canvas.draw_idle()

            except Exception as e:
                print(f"[Animation] Error: {e}")

            time.sleep(dt)

    anim_thread = threading.Thread(target=animation_thread, daemon=True, name="AnimationThread")
    anim_thread.start()

    # --- Joystick (Keyboard + Physical) Control Setup ---
    joy_cfg = cfg.get("joystick", {})
    key_state = {
        "lx": 0.0,
        "ly": 0.0,
        "rx": 0.0,
        "ry": 0.0,
        "a": False,
        "b": False,
        "x": False,
        "y": False,
        "lb": False,
        "rb": False,
        "lt": False,
        "rt": False,
        "back": False,
        "start": False,
    }

    phys_joy = PhysicalJoystick(device_path=joy_cfg.get("device_path", "/dev/input/js0"))
    phys_joy.start()
    _cleanup_state["phys_joy"] = phys_joy

    def get_merged_joystick_state():
        p_state = phys_joy.get_state() if phys_joy.connected else {}
        merged = {}
        for k in key_state:
            if k in ("lx", "ly", "rx", "ry"):
                val = p_state.get(k, 0.0)
                if abs(val) > 0.01:
                    merged[k] = val
                else:
                    merged[k] = key_state[k]
            else:
                merged[k] = key_state[k] or p_state.get(k, False)
        return merged

    def on_key_press(event):
        if event.key is None:
            return
        key = event.key.lower()
        if key == 'w': key_state["ly"] = 1.0
        elif key == 's': key_state["ly"] = -1.0
        elif key == 'a': key_state["lx"] = -1.0
        elif key == 'd': key_state["lx"] = 1.0
        elif key == 'q': key_state["rx"] = -1.0
        elif key == 'e': key_state["rx"] = 1.0
        elif key == '1':
            key_state["rb"] = True
            key_state["rt"] = True
            key_state["a"] = True
        elif key == '2':
            key_state["rb"] = True
            key_state["rt"] = True
            key_state["b"] = True
        elif key in (' ', 'space', '0'):
            key_state["rb"] = True
            key_state["rt"] = True
            key_state["lx"] = 0.0
            key_state["ly"] = 0.0
            key_state["rx"] = 0.0
        elif key == 'k':
            key_state["lt"] = not key_state["lt"]
            print(f"[Joystick] Keyboard arm stiffness toggled. Limp arms: {key_state['lt']}")

    def on_key_release(event):
        if event.key is None:
            return
        key = event.key.lower()
        if key in ('w', 's'): key_state["ly"] = 0.0
        elif key in ('a', 'd'): key_state["lx"] = 0.0
        elif key in ('q', 'e'): key_state["rx"] = 0.0
        elif key == '1':
            key_state["rb"] = False
            key_state["rt"] = False
            key_state["a"] = False
        elif key == '2':
            key_state["rb"] = False
            key_state["rt"] = False
            key_state["b"] = False
        elif key in (' ', 'space', '0'):
            key_state["rb"] = False
            key_state["rt"] = False

    fig.canvas.mpl_connect('key_press_event', on_key_press)
    fig.canvas.mpl_connect('key_release_event', on_key_release)

    # Background transmitter thread (50Hz)
    if joy_cfg.get("enabled", True):
        url = "http://localhost:8080/control"
        target_addr = (joy_cfg.get("target_host", "127.0.0.1"), joy_cfg.get("target_port", 10007))
        print(f"[Joystick TX] Sending commands to {target_addr[0]}:{target_addr[1]}")

        def joystick_transmitter_loop():
            while not stop_event.is_set():
                try:
                    state = get_merged_joystick_state()
                    is_manual = state.get("start", False) or state.get("rb", False)
                    payload = {
                        "ip": target_addr[0],
                        "port": target_addr[1],
                        
                        # Legacy velocity support
                        "vx": state.get("ly", 0.0),
                        "vy": state.get("lx", 0.0),
                        "vtheta": state.get("rx", 0.0),
                        
                        # Full Joystick class support matching Joystick.h
                        "lx": state.get("lx", 0.0),
                        "ly": state.get("ly", 0.0),
                        "rx": state.get("rx", 0.0),
                        "ry": state.get("ry", 0.0),
                        
                        "a": state.get("a", False),
                        "b": state.get("b", False),
                        "x": state.get("x", False),
                        "y": state.get("y", False),
                        
                        "lb": state.get("lb", False),
                        "rb": state.get("rb", False),
                        "lt": state.get("lt", False),
                        "rt": state.get("rt", False),
                        
                        "ls": state.get("ls", False),
                        "rs": state.get("rs", False),
                        
                        "back": state.get("back", False),
                        "start": state.get("start", False),
                        
                        "isManual": is_manual,
                        "testingOverride": True
                    }
                    data_bytes = json.dumps(payload).encode('utf-8')
                    
                    if use_http:
                        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(req, timeout=0.1) as f:
                            f.read()
                    else:
                        # Local direct send over UDP to bypass HTTP overhead
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        if payload["ip"] == "255.255.255.255":
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        sock.sendto(json.dumps(payload).encode("utf-8"), (payload["ip"], payload["port"]))
                        sock.close()
                except Exception:
                    pass
                time.sleep(0.02)

        tx_thread = threading.Thread(target=joystick_transmitter_loop, daemon=True, name="JoyTXThread")
        tx_thread.start()

    plt.tight_layout()
    plt.subplots_adjust(top=0.85)

    print("[*] Window opened. Press Ctrl+C or close the window to exit.")
    try:
        plt.show()
    except KeyboardInterrupt:
        pass

