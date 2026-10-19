"""Print the exactness table of results/<tag>/metrics.json files (markdown).

Usage: python summarize.py results/auto results/d24 ...
"""
import json
import sys

print("| run | depth | pose | size | PSNR dB | % px diff > 16 | mean abs diff |")
print("|---|---|---|---|---|---|---|")
for d in sys.argv[1:]:
    for r in json.load(open(f"{d}/metrics.json")):
        if "psnr_db" in r:
            print(f"| {d.split('/')[-1]} | {r['depth']} | {r['pose']} | {r['size']} | {r['psnr_db']} | "
                  f"{r['pct_pixels_diff_gt_16']} | {r['mean_abs_diff_0_255']} |")
