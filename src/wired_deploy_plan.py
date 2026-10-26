"""Verify a staged artifact and describe the wired activation/rollback boundary."""

import json
import re
from pathlib import Path

from artifact_preview import _architecture, _hash


_ARTIFACT_ID = re.compile(r"^[0-9a-f]{12}-[0-9a-f]{12}-[0-9a-f]{12}$")
PHASES = (
    "Verify fresh SSH identity, robot model, service path and available space",
    "Copy the pinned binary, deploy.yaml and version.txt to a unique incoming directory",
    "Compare every remote SHA-256 with the manifest before touching the active files",
    "Back up the installed binary and complete config directory under a unique job ID",
    "Stop maximus and maximus-start while the robot is physically supported",
    "Atomically install the staged binary and config, then start the services",
    "Verify service status and Oraculum telemetry; restore the backup on failure",
)


def list_artifacts(root):
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted((p.name for p in root.iterdir()
                   if p.is_dir() and not p.is_symlink() and _ARTIFACT_ID.fullmatch(p.name)), reverse=True)


def plan(root, artifact_id, target):
    """Read only. A browser-supplied ID never becomes a path unless it matches the hash format."""
    if not _ARTIFACT_ID.fullmatch(str(artifact_id)):
        raise ValueError("invalid artifact ID")
    folder = Path(root) / artifact_id
    if not folder.is_dir() or folder.is_symlink():
        raise FileNotFoundError("artifact not found")
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("artifact manifest is missing or linked")
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("artifact manifest cannot be read") from exc
    if data.get("id") != artifact_id:
        raise ValueError("artifact ID does not match its manifest")
    for key, expected in (("target", target["id"]), ("target_ip", target["ip"]), ("model", target["model"])):
        if data.get(key) != expected:
            raise ValueError("artifact " + key + " differs from the configured target")
    if data.get("profile") not in ("practice", "match"):
        raise ValueError("artifact profile is invalid")
    if data.get("oraculum_host") != target.get("gateway_address"):
        raise ValueError("artifact gateway address is no longer on the target subnet")
    commit = data.get("source_commit", "")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source commit is not pinned")
    files = (("maximus_main", "binary_sha256"), ("deploy.yaml", "config_sha256"),
             ("version.txt", "version_sha256"))
    for filename, key in files:
        path = folder / filename
        if not isinstance(data.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", data[key]):
            raise ValueError(filename + " has no valid SHA-256")
        if not path.is_file() or path.is_symlink() or _hash(path) != data.get(key):
            raise ValueError(filename + " does not match the manifest")
    if _architecture(folder / "maximus_main") != "AArch64":
        raise ValueError("staged binary is not AArch64")
    if artifact_id != commit[:12] + "-" + data["binary_sha256"][:12] + "-" + data["config_sha256"][:12]:
        raise ValueError("artifact identity does not match its hashes")
    return {"artifact": artifact_id, "target": target["id"], "target_ip": target["ip"],
            "profile": data["profile"], "source_commit": commit,
            "phases": list(PHASES), "offline_verified": True, "activation_available": False,
            "pending": ["fresh robot identity and service-path checks", "SSH credentials and trusted host key",
                        "physical support at activation", "authenticated deploy and rollback adapter"]}
