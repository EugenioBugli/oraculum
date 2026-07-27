"""Test field rendering to diagnose the horizontal line issue."""
import matplotlib
matplotlib.use('TkAgg')  # Explicit backend

import matplotlib.pyplot as plt
from src.config import load_config
from src.field import draw_field
import os
import time

root = os.path.abspath('.')
cfg, field, field_name = load_config(root)

print("[*] Creating figure...")
fig, ax = plt.subplots(figsize=(10, 7))

W = field["width"]
H = field["height"]
hw, hh = W / 2, H / 2
margin = max(W, H) * 0.06

print(f"[*] Setting axis limits: X=[{-hw-margin:.1f}, {hw+margin:.1f}], Y=[{-hh-margin:.1f}, {hh+margin:.1f}]")
ax.set_xlim(-hw - margin, hw + margin)
ax.set_ylim(-hh - margin, hh + margin)
ax.set_aspect("equal")
ax.axis("off")

print("[*] Drawing field...")
draw_field(ax, field, cfg)

print(f"[*] Patches on figure: {len(ax.patches)}")
print(f"[*] Lines on figure: {len(ax.lines)}")

fig.suptitle("Field Render Test", fontsize=14)

# Try different draw methods
print("\n[*] Testing draw methods...")
print("  1. canvas.draw()...", end=" ", flush=True)
try:
    fig.canvas.draw()
    print("✓")
except Exception as e:
    print(f"✗ {e}")

print("  2. canvas.draw_idle()...", end=" ", flush=True)
try:
    fig.canvas.draw_idle()
    print("✓")
except Exception as e:
    print(f"✗ {e}")

print("\n[*] Saving figure to field_render_test.png...")
fig.savefig("field_render_test.png")
print("[*] Saved.")
print("[*] Test complete")
