"""Read-only preview of an existing AArch64 robot build and its practice/match config."""

import hashlib
import os
import subprocess

import yaml


_CONFIG_KEYS = ("robot", "oraculum", "oraculumHost", "useRerun", "useGameController", "customMode")


def _git(repo, *args):
    try:
        proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=3)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _architecture(path):
    with open(path, "rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return "not ELF"
    endian = "little" if header[5] == 1 else "big" if header[5] == 2 else "unknown"
    if endian == "unknown":
        return "unknown ELF"
    machine = int.from_bytes(header[18:20], endian)
    return {183: "AArch64", 62: "x86-64"}.get(machine, "ELF machine " + str(machine))


def preview(repo, target, profile):
    """No build, file modification, network access, or user-supplied path."""
    if profile not in ("practice", "match"):
        raise ValueError("unknown profile")
    repo = os.path.realpath(repo)
    binary = os.path.join(repo, "build", "aarch64", "src", "app", "maximus_main")
    config_path = os.path.join(repo, "src", "app", "config", "deploy.yaml")
    commit = _git(repo, "rev-parse", "HEAD")
    dirty = bool(_git(repo, "status", "--porcelain"))
    blockers = []
    if not commit:
        blockers.append("Robot checkout has no readable Git commit.")
    if dirty:
        blockers.append("Robot checkout has uncommitted or untracked files; artifact provenance is not pinned.")
    if not target.get("gateway_address"):
        blockers.append("Gateway has no IPv4 address on the robot's configured subnet.")
    if not target.get("model"):
        blockers.append("Target robot model is unverified in Operations configuration.")

    binary_info = {"present": os.path.isfile(binary), "architecture": "unknown", "sha256": None,
                   "size": None}
    if binary_info["present"]:
        try:
            binary_info.update(architecture=_architecture(binary), sha256=_hash(binary), size=os.path.getsize(binary))
        except OSError:
            blockers.append("Built binary cannot be read.")
        if binary_info["architecture"] != "AArch64":
            blockers.append("Built binary is not AArch64.")
    else:
        blockers.append("AArch64 binary has not been built.")

    config_info = {"present": os.path.isfile(config_path), "current": {}, "proposed": {}, "changes": {}}
    if config_info["present"]:
        try:
            with open(config_path) as stream:
                raw = yaml.safe_load(stream) or {}
            if not isinstance(raw, dict):
                raise ValueError("deploy.yaml is not a mapping")
            current = {key: raw.get(key) for key in _CONFIG_KEYS}
            proposed = {**current, "oraculum": profile, "oraculumHost": target.get("gateway_address") or ""}
            config_info.update(current=current, proposed=proposed,
                               changes={key: {"from": current[key], "to": proposed[key]}
                                        for key in _CONFIG_KEYS if current[key] != proposed[key]})
            if target.get("model") and current["robot"] != target["model"]:
                blockers.append("Build config model differs from the configured target model.")
        except (OSError, ValueError, yaml.YAMLError):
            blockers.append("deploy.yaml cannot be parsed.")
    else:
        blockers.append("deploy.yaml is missing.")

    # No executable script, SSH action, Wi-Fi edit, or full config contents leave this function.
    return {"target": target["id"], "profile": profile, "commit": commit,
            "dirty": dirty, "binary": binary_info, "config": config_info,
            "ready": not blockers, "blockers": blockers}
