from pathlib import Path
import runpy
import unittest

issues = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check.py"))["issues"]


class HarnessTests(unittest.TestCase):
    def test_redacted_secret_detection(self):
        for sample in (b"ghp_" + b"x" * 36, b"sk-proj-" + b"x" * 45,
                       b"-----BEGIN " + b"PRIVATE KEY-----"):
            reasons = list(issues(Path("notes"), sample))
            self.assertTrue(reasons)
            self.assertNotIn(sample.decode(), str(reasons))
        self.assertTrue(list(issues(Path(".env"), b"")))

    def test_shell_invocation_detection(self):
        self.assertTrue(list(issues(Path("bin/codex-auto-resume"),
                                    b"subprocess.run(cmd, shell=True)")))
