"""Staging pins files locally and refuses unpinned or secret-bearing input."""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from artifact_stage import stage  # noqa: E402


class ArtifactStageTest(unittest.TestCase):
    def test_stage_and_reject_dirty_input(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            repo.mkdir()
            binary = repo / "build/aarch64/src/app/maximus_main"
            binary.parent.mkdir(parents=True)
            header = bytearray(20)
            header[:4] = b"\x7fELF"
            header[5] = 1
            header[18:20] = (183).to_bytes(2, "little")
            binary.write_bytes(header)
            config_path = repo / "src/app/config/deploy.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("robot: t1\noraculum: off\noraculumHost: ''\nuseRerun: true\n")
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                   "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], env=env, check=True)
            target = {"id": "robot6", "ip": "192.168.10.102", "model": "t1", "gateway_address": "192.168.10.236"}
            output = Path(root) / "artifacts"
            result = stage(repo, target, "match", output)
            saved = output / result["id"]
            self.assertTrue(saved.is_dir())
            self.assertEqual(result["binary_sha256"], hashlib.sha256((saved / "maximus_main").read_bytes()).hexdigest())
            self.assertEqual(result["config_sha256"], hashlib.sha256((saved / "deploy.yaml").read_bytes()).hexdigest())
            self.assertEqual(result["version_sha256"], hashlib.sha256((saved / "version.txt").read_bytes()).hexdigest())
            staged_config = yaml.safe_load((saved / "deploy.yaml").read_text())
            self.assertEqual(staged_config["oraculum"], "match")
            self.assertFalse(staged_config["useRerun"])
            self.assertEqual(stage(repo, target, "match", output), result)
            saved.chmod(0o700)
            (saved / "maximus_main").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "does not match"):
                stage(repo, target, "match", output)
            config_path.write_text(config_path.read_text() + "# changed\n")
            with self.assertRaisesRegex(ValueError, "uncommitted"):
                stage(repo, target, "match", output)


if __name__ == "__main__":
    unittest.main()
