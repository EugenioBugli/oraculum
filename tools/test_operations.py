"""The Operations probe must stay bounded to configured, read-only targets."""

import contextlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from operations import OperationsInspector  # noqa: E402


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.inspector = OperationsInspector({"operations": {"targets": [
            {"id": "robot6", "ip": "192.168.10.102", "user": "booster", "service": "maximus"}
        ]}})

    def test_target_is_allowlisted(self):
        with self.assertRaises(KeyError):
            self.inspector.probe("127.0.0.1")
        with self.assertRaises(ValueError):
            OperationsInspector({"operations": {"targets": [
                {"id": "bad", "ip": "127.0.0.1", "service": "maximus"}
            ]}})
        with self.assertRaises(ValueError):
            OperationsInspector({"operations": {"targets": [
                {"id": "bad", "ip": "192.168.10.102", "service": "maximus; reboot"}
            ]}})

    def test_disconnected_does_not_run_ssh(self):
        def disconnected(*args, **kwargs):
            raise OSError("cable unplugged")

        def forbidden(*args, **kwargs):
            self.fail("SSH must not run after connection failure")

        result = self.inspector.probe("robot6", connect=disconnected, run=forbidden)
        self.assertFalse(result["ssh_port"])
        self.assertIn("cable unplugged", result["ssh"])

    def test_fixed_ssh_read_only_probe(self):
        @contextlib.contextmanager
        def connected(*args, **kwargs):
            yield object()

        def fake_run(args, **kwargs):
            self.assertEqual(args[-3:], ["booster@192.168.10.102", "sh", "-s"])
            self.assertEqual(kwargs["timeout"], 5)
            script = kwargs["input"]
            self.assertIn("systemctl is-active maximus", script)
            self.assertIn("journalctl -u maximus -n 30", script)
            self.assertNotIn("systemctl restart", script)
            return SimpleNamespace(returncode=0, stderr="", stdout=(
                "ORC_SERVICE=active\nORC_VERSION=abc123\nORC_JOYSTICKS=none\n"
                "ORC_LOGS_BEGIN\n2026-10-26 service running\n"))

        result = self.inspector.probe("robot6", connect=connected, run=fake_run)
        self.assertEqual(result["service"], "active")
        self.assertEqual(result["version"], "abc123")
        self.assertEqual(result["logs"], ["2026-10-26 service running"])


if __name__ == "__main__":
    unittest.main()
