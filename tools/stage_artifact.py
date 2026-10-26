#!/usr/bin/env python3
"""Pin an existing AArch64 build locally; never connect to a robot."""

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_stage import stage  # noqa: E402
from operations import OperationsInspector  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="ID from config.yaml operations.targets")
    parser.add_argument("--profile", choices=("practice", "match"), required=True)
    args = parser.parse_args()
    with (ROOT / "config.yaml").open() as stream:
        config = yaml.safe_load(stream)
    target = next((item for item in OperationsInspector(config, root=ROOT).inventory()["targets"]
                   if item["id"] == args.target), None)
    if target is None:
        parser.error("unknown configured target")
    repo = Path(target["repo"])
    try:
        data = stage(repo, target, args.profile, ROOT / "artifacts")
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(data, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
