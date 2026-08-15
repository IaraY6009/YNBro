from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "rtsp_bootstrap", *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=5.0,
            check=False,
        )

    def test_module_help(self) -> None:
        result = self._run("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"sender", result.stdout)
        self.assertIn(b"receiver", result.stdout)

    def test_invalid_bind_fails_instead_of_exiting_successfully(self) -> None:
        result = self._run("receiver", "--bind", "256.256.256.256")
        self.assertNotEqual(result.returncode, 0)

    def test_nonfinite_cli_values_are_rejected(self) -> None:
        result = self._run("receiver", "--duration", "NaN")
        self.assertEqual(result.returncode, 2)
        sender_result = self._run(
            "sender",
            "--device-id",
            "camera-1",
            "--ip",
            "127.0.0.1",
            "--rtsp-port",
            "8554",
            "--rtsp-path",
            "/stream",
            "--detail-json",
            '{"value":NaN}',
        )
        self.assertEqual(sender_result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
