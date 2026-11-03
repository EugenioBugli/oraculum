"""Create a pinned, local deployment artifact. This module never contacts a robot."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import yaml

from artifact_preview import _git, _hash, _source_dirty, preview, binary_path


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


def _config_bundle(repo, target, profile):
    config_root = repo / "src/app/config"
    if not config_root.is_dir() or config_root.is_symlink():
        raise ValueError("Robot source config directory is missing or linked")
    if type(target.get("number")) is not int or not 1 <= target["number"] <= 99:
        raise ValueError("Target player number must be configured before staging")
    if type(target.get("dual_board")) is not bool:
        raise ValueError("Target board layout must be configured before staging")
    files = {}
    for path in sorted(config_root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Linked files are not allowed in the robot config")
        if path.is_dir():
            continue
        if not path.is_file() or path.suffix != ".yaml":
            raise ValueError("Unexpected file in robot config: " + path.name)
        relative = path.relative_to(config_root).as_posix()
        raw = yaml.safe_load(path.read_bytes())
        if relative == "deploy.yaml" and isinstance(raw, dict):
            raw.pop("wifi", None)  # Ethernet artifacts never contain or change Wi-Fi credentials.
        if not isinstance(raw, dict) or _contains_secret(raw):
            raise ValueError("Robot config contains secret-looking fields or invalid YAML: " + relative)
        if relative == "deploy.yaml":
            raw.update(oraculum=profile, oraculumHost=target["gateway_address"],
                       number=target["number"], dualBoard=target["dual_board"])
            if not (config_root / "settings.yaml").exists():
                raw["scenario"] = "real"
            if profile == "match":
                raw.update(useRerun=False, useGameController=True)
            files[relative] = yaml.safe_dump(raw, sort_keys=False).encode()
        elif relative == "settings.yaml":
            raw["scenario"] = "real"
            files[relative] = yaml.safe_dump(raw, sort_keys=False).encode()
        else:
            files[relative] = path.read_bytes()
    if "deploy.yaml" not in files:
        raise ValueError("Robot config must include deploy.yaml")
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    tree_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return files, hashes, tree_hash


def stage(repo, target, profile, output_root):
    """Copy binary/config to an immutable commit+hash directory after a strict preview."""
    status = preview(repo, target, profile)
    if not status["ready"]:
        raise ValueError("Artifact cannot be staged: " + " ".join(status["blockers"]))
    repo = Path(repo).resolve()
    source = Path(binary_path(str(repo), target))
    files, file_hashes, tree_hash = _config_bundle(repo, target, profile)
    encoded_config = files["deploy.yaml"]
    config_hash = hashlib.sha256(encoded_config).hexdigest()
    encoded_version = (status["commit"][:8] + "\n").encode()
    version_hash = hashlib.sha256(encoded_version).hexdigest()
    identity = status["commit"][:12] + "-" + status["binary"]["sha256"][:12] + "-" + tree_hash[:12]
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
                or data.get("config_tree_sha256") != tree_hash
                or data.get("config_files") != file_hashes
                or data.get("version_sha256") != version_hash
                or data.get("source_commit") != status["commit"]
                or data.get("target") != target["id"]
                or data.get("profile") != profile
                or not (destination / "maximus_main").is_file()
                or not (destination / "deploy.yaml").is_file()
                or not (destination / "version.txt").is_file()
                or not (destination / "config").is_dir()
                or (destination / "config").is_symlink()
                or _hash(destination / "maximus_main") != status["binary"]["sha256"]
                or _hash(destination / "deploy.yaml") != config_hash
                or _hash(destination / "version.txt") != version_hash
                or any(not (destination / "config" / name).is_file()
                       or (destination / "config" / name).is_symlink()
                       or _hash(destination / "config" / name) != digest
                       for name, digest in file_hashes.items())
                or any(p.is_symlink() for p in (destination / "config").rglob("*"))
                or {p.relative_to(destination / "config").as_posix()
                    for p in (destination / "config").rglob("*") if p.is_file()} != set(file_hashes)):
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
        config_dir = temporary / "config"
        config_dir.mkdir(mode=0o700)
        for name, contents in files.items():
            path = config_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o600)
        version = temporary / "version.txt"
        with version.open("xb") as stream:
            stream.write(encoded_version)
            stream.flush()
            os.fsync(stream.fileno())
        version.chmod(0o600)
        if _git(str(repo), "rev-parse", "HEAD") != status["commit"] or _source_dirty(str(repo)):
            raise ValueError("Source checkout changed during staging")
        data = {"id": identity, "source_commit": status["commit"], "target": target["id"],
                "target_ip": target["ip"], "model": target["model"], "profile": profile,
                "oraculum_host": target["gateway_address"],
                "binary_sha256": copied_hash, "config_sha256": config_hash,
                "config_tree_sha256": tree_hash, "config_files": file_hashes,
                "number": target["number"], "dual_board": target["dual_board"],
                "version_sha256": version_hash,
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
