"""Field drawing logic."""

import math
import matplotlib.patches as patches
from matplotlib.patches import Circle


def draw_field(ax, f: dict, cfg: dict) -> None:
    """Draw all field elements onto *ax* using data from field dict *f*."""
    disp = cfg.get("display", {})
    field_color = disp.get("field_color", "#3a7d44")
    border_color = disp.get("border_color", "#2d6b35")
    border_width = disp.get("border_width", 1.0)
    surround_color = disp.get("surround_color", "#1e3d1e")
    line_color = disp.get("line_color", "white")
    goal_color = disp.get("goal_color", "#cccccc")
    ball_color = disp.get("ball_color", "orange")
    pm_color = disp.get("penalty_mark_color", line_color)
    lw_pt = 1.5  # linewidth in display points

    W = f["width"]
    H = f["height"]
    cr = f["center_radius"]
    gaw = f["goal_area_width"]    # depth into field (x)
    gah = f["goal_area_height"]   # span along goal line (y)
    paw = f["penalty_area_width"]  # depth into field (x)
    pah = f["penalty_area_height"] # span along goal line (y)
    pmd = f["penalty_mark_distance"]
    gw = f["goal_width"]   # opening span (y)
    gd = f["goal_depth"]   # depth outside field (x)
    br = f["ball_radius"]
    lw = f["line_width"]

    # Layer 0 — surroundings (full axes background)
    ax.set_facecolor(surround_color)
    # Layer 1 — border strip around the field
    bw = border_width
    ax.add_patch(patches.Rectangle(
        (-W / 2 - bw, -H / 2 - bw), W + 2 * bw, H + 2 * bw,
        linewidth=0, facecolor=border_color, zorder=1,
    ))
    # Layer 2 — field surface
    ax.add_patch(patches.Rectangle(
        (-W / 2, -H / 2), W, H,
        linewidth=0, facecolor=field_color, zorder=2,
    ))

    Z = 3  # base zorder for all field markings (above background layers 1-2)

    def rect(x0, y0, x1, y1, color=line_color, fill=False):
        ax.add_patch(patches.Rectangle(
            (x0, y0), x1 - x0, y1 - y0,
            linewidth=lw_pt, edgecolor=color,
            facecolor=color if fill else "none",
            zorder=Z,
        ))

    def cross(x, y, size, color=pm_color):
        ax.plot([x - size, x + size], [y, y], color=color, linewidth=lw_pt, zorder=Z)
        ax.plot([x, x], [y - size, y + size], color=color, linewidth=lw_pt, zorder=Z)

    # Field boundary
    rect(-W / 2, -H / 2, W / 2, H / 2)

    # Halfway line
    ax.plot([0, 0], [-H / 2, H / 2], color=line_color, linewidth=lw_pt, zorder=Z)

    # Center circle + mark
    ax.add_patch(Circle((0, 0), cr, linewidth=lw_pt,
                         edgecolor=line_color, facecolor="none", zorder=Z))
    cross(0, 0, size=lw * 1.5)

    for sx in [-1, 1]:
        gx = sx * W / 2  # goal line x

        # Goal area
        if sx == 1:
            rect(gx - gaw, -gah / 2, gx, gah / 2)
        else:
            rect(gx, -gah / 2, gx + gaw, gah / 2)

        # Penalty area
        if sx == 1:
            rect(gx - paw, -pah / 2, gx, pah / 2)
        else:
            rect(gx, -pah / 2, gx + paw, pah / 2)

        # Penalty spot
        px = gx - sx * pmd
        cross(px, 0, size=lw * 1.5)

        # Goals (outside field boundary, drawn on border layer)
        if disp.get("show_goals", True):
            if sx == 1:
                rect(gx, -gw / 2, gx + gd, gw / 2, color=goal_color)
            else:
                rect(gx - gd, -gw / 2, gx, gw / 2, color=goal_color)

    # Dimensions label
    if disp.get("show_dimensions_label", True):
        ax.text(
            0, -H / 2 - H * 0.06,
            f"{W:.1f} m \u00d7 {H:.1f} m",
            color="white", ha="center", va="top", fontsize=9,
        )
