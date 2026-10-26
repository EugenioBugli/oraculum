"""Create a pinned, local deployment artifact. This module never contacts a robot."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import yaml

from artifact_preview import _git, _hash, preview


_SENSITIVE = ("password", "passwd", "psk", "secret", "token", "privatekey")


def _contains_secret(value):
    if isinstance(value, dict):
        return any(any(word in str(key).lower().replace("_", "") for word in _SENSITIVE)
                   or _contains_secret(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def _copy_hash(source, dest):
    digest = hashlib.sha256()
    with open(source, "rb") as src, open(dest, "xb") as dst:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            dst.write(chunk)
            digest.update(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    return digest.hexdigest()


def stage(repo, target, profile, output_root):
    """Copy binary/config to an immutable commit+hash directory after a strict preview."""
    status = preview(repo, target, profile)
    if not status["ready"]:
        raise ValueError("Artifact cannot be staged: " + " ".join(status["blockers"]))
    repo = Path(repo).resolve()
    source = repo / "build/aarch64/src/app/maximus_main"
    config_path = repo / "src/app/config/deploy.yaml"
    with config_path.open() as stream:
        config = yaml.safe_load(stream) or {}
    if not isinstance(config, dict) or _contains_secret(config):
        raise ValueError("deploy.yaml contains secret-looking fields or is invalid; staging refuses to copy it")
    config["oraculum"] = profile
    config["oraculumHost"] = target["gateway_address"]
    if profile == "match":
        config["useRerun"] = False
        config["useGameController"] = True
    encoded_config = yaml.safe_dump(config, sort_keys=False).encode()
    config_hash = hashlib.sha256(encoded_config).hexdigest()
    identity = status["commit"][:12] + "-" + status["binary"]["sha256"][:12] + "-" + config_hash[:12]
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = output / identity
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("Artifact destination is not a directory")
        manifest = destination / "manifest.json"
        if not manifest.is_file():
            raise ValueError("Artifact directory exists without a manifest")
        data = json.loads(manifest.read_text())
        if (data.get("binary_sha256") != status["binary"]["sha256"]
                or data.get("config_sha256") != config_hash
                or data.get("source_commit") != status["commit"]
                or data.get("target") != target["id"]
                or data.get("profile") != profile
                or not (destination / "maximus_main").is_file()
                or not (destination / "deploy.yaml").is_file()
                or _hash(destination / "maximus_main") != status["binary"]["sha256"]
                or _hash(destination / "deploy.yaml") != config_hash):
            raise ValueError("Existing artifact does not match its identity")
        return data
    temporary = Path(tempfile.mkdtemp(prefix=".stage-", dir=output))
    try:
        binary = temporary / "maximus_main"
        copied_hash = _copy_hash(source, binary)
        if copied_hash != status["binary"]["sha256"]:
            raise ValueError("Binary changed during staging")
        binary.chmod(0o700)
        staged_config = temporary / "deploy.yaml"
        with staged_config.open("xb") as stream:
            stream.write(encoded_config)
            stream.flush()
            os.fsync(stream.fileno())
        staged_config.chmod(0o600)
        if _git(str(repo), "rev-parse", "HEAD") != status["commit"] or _git(str(repo), "status", "--porcelain"):
            raise ValueError("Source checkout changed during staging")
        data = {"id": identity, "source_commit": status["commit"], "target": target["id"],
                "target_ip": target["ip"], "model": target["model"], "profile": profile,
                "oraculum_host": target["gateway_address"],
                "binary_sha256": copied_hash, "config_sha256": config_hash,
                "binary_size": binary.stat().st_size}
        manifest = temporary / "manifest.json"
        with manifest.open("x") as stream:
            json.dump(data, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        manifest.chmod(0o600)
        temporary.chmod(0o500)
        os.replace(temporary, destination)
        return data
    finally:
        if temporary.exists():
            temporary.chmod(0o700)
            shutil.rmtree(temporary)
