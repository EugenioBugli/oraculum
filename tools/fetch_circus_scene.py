"""Downloads the "Circus (exact)" 3D view files that the CI published into src/static/ (git-ignored).

A circus-scene-<circus>-<config> release holds the scenes exported by circus's own SceneParser
(.github/workflows/circus-scene.yml) and, once .github/workflows/oraculum-renderer.yml passed for them,
the B2 renderer built for that scene:
    b2_bundle.tar.gz                 -> src/static/circus/                          (b2.js, b2_engine.js/.wasm)
    b2_scene_<name>.tar.gz           -> src/static/models/circus_scene_<name>/      (scene package, e.g. maximus_5v5)
With B2 assets in the release only those are fetched; without them, the raw scene exports
(circus_scene_*.tar.gz -> src/static/models/circus_scene_*/). SHA-256 sums are checked against
manifest.json / b2_manifest.json.

It picks the release that matches the local spqrbooster2026 checkout (circus commit pinned
in external/circus + the scene/field config), so the browser shows the scene `pixi run sim`
shows. Without a match it takes the newest scene release and says so.

    python3 tools/fetch_circus_scene.py [--maximus ../spqrbooster2026] [--repo owner/name] [--tag TAG]

A local build instead: copy b2_bundle/* to src/static/circus/ and run
    renderer/package_scenes.sh src/static/models SCENE_DIR:circus_scene_maximus_5v5 ...
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"
OUT = STATIC / "models"
PREFIX = "circus-scene-"


def b2_target(name: str):
    """(folder inside the archive, destination) of a B2 asset of the release, else None."""
    if name == "b2_bundle.tar.gz":
        return "b2_bundle", STATIC / "circus"
    m = re.fullmatch(r"b2_scene_([A-Za-z0-9_]+)\.tar\.gz", name)
    return (m.group(1), OUT / f"circus_scene_{m.group(1)}") if m else None


def origin_repo() -> str:
    url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True).stdout
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    if not m:
        sys.exit("cannot read the GitHub repo from git remote 'origin'; pass --repo owner/name")
    return m.group(1)


def _token() -> str:
    """GH_TOKEN / GITHUB_TOKEN, else the gh CLI's login: a private releases repo needs one; a public one does not."""
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not tok and shutil.which("gh"):
        tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    return tok


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Asset downloads redirect to a signed storage URL, which refuses a second credential."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_NoAuthRedirect)
TOKEN = None


def fetch(url: str, accept: str = "application/vnd.github+json") -> bytes:
    global TOKEN
    if TOKEN is None:
        TOKEN = _token()
    headers = {"Accept": accept, **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})}
    with _OPENER.open(urllib.request.Request(url, headers=headers)) as r:
        return r.read()


def get_json(url: str):
    return json.loads(fetch(url))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maximus", default=str(ROOT.parent / "spqrbooster2026"), help="spqrbooster2026 checkout")
    ap.add_argument("--repo", default=None, help="GitHub repo with the releases (default: git origin)")
    ap.add_argument("--tag", default=None, help="exact release tag")
    args = ap.parse_args()
    repo = args.repo or origin_repo()

    want = args.tag
    if not want and pathlib.Path(args.maximus, ".git").exists():
        tag = subprocess.run([str(ROOT / "tools/circus_scene/scene_tag.sh"), args.maximus], capture_output=True, text=True)
        want = tag.stdout.strip() or None

    releases = [r for r in get_json(f"https://api.github.com/repos/{repo}/releases?per_page=50")
                if r["tag_name"].startswith(PREFIX)]
    if not releases:
        sys.exit(f"no {PREFIX}* release in {repo} yet; run the 'circus scene export' workflow")
    release = next((r for r in releases if r["tag_name"] == want), None)
    if release is None:
        release = releases[0]  # the API lists the newest first
        print(f"[fetch_circus_scene] no release for {want or 'this checkout'}; using the newest: {release['tag_name']}")

    assets = {a["name"]: a["url"] for a in release["assets"]}  # API URLs: they also work for a private repo
    sums = {}
    for m in ("manifest.json", "b2_manifest.json"):
        if m in assets:
            sums.update({k: v.get("sha256") for k, v in json.loads(fetch(assets[m], "application/octet-stream"))["files"].items()})
    b2 = any(b2_target(n) for n in assets)
    if not b2:
        print(f"[fetch_circus_scene] {release['tag_name']} has no B2 renderer yet (oraculum-renderer.yml); raw scenes only")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in assets.items():
        target = b2_target(name)
        if not name.endswith(".tar.gz") or (b2 and not target):
            continue
        data = fetch(url, "application/octet-stream")
        if sums.get(name) and hashlib.sha256(data).hexdigest() != sums[name]:
            sys.exit(f"{name}: checksum does not match the release manifest")
        with tempfile.TemporaryDirectory(dir=STATIC) as tmp:
            archive = pathlib.Path(tmp) / name
            archive.write_bytes(data)
            with tarfile.open(archive) as tar:
                tar.extractall(tmp, filter="data")  # "data" filter: no absolute paths, no links outside tmp
            if target:  # replace the whole folder: no stale files of an older scene or renderer
                folder, dest = target
                shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(pathlib.Path(tmp) / folder), dest)
            else:
                dest = OUT / name.removesuffix(".tar.gz")
                shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(pathlib.Path(tmp) / dest.name), dest)
        print(f"[fetch_circus_scene] {name} -> {dest}")
    (OUT / "CIRCUS_SCENE_RELEASE").write_text(release["tag_name"] + "\n")


if __name__ == "__main__":
    main()
