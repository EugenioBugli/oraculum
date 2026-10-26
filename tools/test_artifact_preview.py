"""Check artifact architecture and that config secrets stay out of the preview."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from artifact_preview import preview  # noqa: E402


class ArtifactPreviewTest(unittest.TestCase):
    def test_profile_diff_excludes_secrets_and_checks_architecture(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root)
            binary = repo / "build/aarch64/src/app/maximus_main"
            binary.parent.mkdir(parents=True)
            header = bytearray(20)
            header[:4] = b"\x7fELF"
            header[5] = 1
            header[18:20] = (183).to_bytes(2, "little")
            binary.write_bytes(header)
            config = repo / "src/app/config/deploy.yaml"
            config.parent.mkdir(parents=True)
            config.write_text("robot: t1\noraculum: off\noraculumHost: ''\nwifiPsk: SECRET-DO-NOT-LEAK\n")
            target = {"id": "robot6", "model": "t1", "gateway_address": "192.168.10.236"}
            data = preview(str(repo), target, "practice")
            self.assertEqual(data["binary"]["architecture"], "AArch64")
            self.assertEqual(data["config"]["proposed"]["oraculum"], "practice")
            self.assertEqual(data["config"]["proposed"]["oraculumHost"], "192.168.10.236")
            self.assertNotIn("SECRET-DO-NOT-LEAK", json.dumps(data))
            self.assertFalse(data["ready"])  # No source commit in this fixture.
            header[18:20] = (62).to_bytes(2, "little")
            binary.write_bytes(header)
            wrong = preview(str(repo), target, "practice")
            self.assertIn("Built binary is not AArch64.", wrong["blockers"])
            with self.assertRaises(ValueError):
                preview(str(repo), target, "untrusted-profile")


if __name__ == "__main__":
    unittest.main()
