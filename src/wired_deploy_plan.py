"""Verify a staged artifact and describe the wired activation/rollback boundary."""

import json
import hashlib
import re
from pathlib import Path, PurePosixPath

import yaml

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
    for key, expected in (("number", target.get("number")), ("dual_board", target.get("dual_board"))):
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
    config_dir = folder / "config"
    config_files = data.get("config_files")
    tree_hash = data.get("config_tree_sha256")
    if not config_dir.is_dir() or config_dir.is_symlink() or not isinstance(config_files, dict) \
            or not isinstance(tree_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", tree_hash) \
            or "deploy.yaml" not in config_files:
        raise ValueError("artifact has no complete pinned config directory")
    for name, digest in config_files.items():
        parts = PurePosixPath(name).parts if isinstance(name, str) else ()
        if not parts or not re.fullmatch(r"[a-zA-Z0-9_./-]+\.yaml", name) or any(part in (".", "..") for part in parts) or name.startswith("/") \
                or not name.endswith(".yaml") or not isinstance(digest, str) \
                or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("artifact config has an invalid file entry")
        path = config_dir.joinpath(*parts)
        if any(parent.is_symlink() for parent in path.parents if parent != config_dir and config_dir in parent.parents) \
                or not path.is_file() or path.is_symlink() or _hash(path) != digest:
            raise ValueError("artifact config file does not match the manifest")
    entries = list(config_dir.rglob("*"))
    if any(p.is_symlink() for p in entries):
        raise ValueError("artifact config directory contains a linked file")
    actual_files = {p.relative_to(config_dir).as_posix() for p in entries if p.is_file()}
    if actual_files != set(config_files):
        raise ValueError("artifact config directory differs from its manifest")
    expected_tree = hashlib.sha256(json.dumps(config_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected_tree != tree_hash or data["config_sha256"] != config_files["deploy.yaml"] \
            or _hash(folder / "deploy.yaml") != config_files["deploy.yaml"]:
        raise ValueError("artifact config tree does not match its hash")
    try:
        deploy = yaml.safe_load((config_dir / "deploy.yaml").read_bytes())
        settings = yaml.safe_load((config_dir / "settings.yaml").read_bytes()) if "settings.yaml" in config_files else deploy
    except yaml.YAMLError as exc:
        raise ValueError("artifact config YAML is invalid") from exc
    if not isinstance(deploy, dict) or not isinstance(settings, dict):
        raise ValueError("artifact config YAML is not a mapping")
    if deploy.get("oraculum") != data["profile"] or deploy.get("oraculumHost") != data["oraculum_host"] \
            or deploy.get("robot") != target["model"] or deploy.get("number") != target.get("number") \
            or deploy.get("dualBoard") != target.get("dual_board") or settings.get("scenario") != "real":
        raise ValueError("artifact config is inconsistent with the selected robot")
    if _architecture(folder / "maximus_main") != "AArch64":
        raise ValueError("staged binary is not AArch64")
    if artifact_id != commit[:12] + "-" + data["binary_sha256"][:12] + "-" + tree_hash[:12]:
        raise ValueError("artifact identity does not match its hashes")
    pending = ["fresh robot identity and service-path checks", "SSH credentials and trusted host key",
               "physical support at activation", "authenticated deploy and rollback adapter"]
    if not target.get("gateway_connected"):
        pending.append("gateway laptop address active on the robot Ethernet subnet")
    return {"artifact": artifact_id, "target": target["id"], "target_ip": target["ip"],
            "profile": data["profile"], "source_commit": commit,
            "phases": list(PHASES), "offline_verified": True, "activation_available": False,
            "pending": pending}
