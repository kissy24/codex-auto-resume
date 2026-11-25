from pathlib import Path
import runpy

issues = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check.py"))["issues"]


def test_redacted_secret_detection():
    for sample in (b"ghp_" + b"x" * 36, b"sk-proj-" + b"x" * 45,
                   b"-----BEGIN " + b"PRIVATE KEY-----"):
        reasons = list(issues(Path("notes"), sample))
        assert reasons
        assert sample.decode() not in str(reasons)
    assert list(issues(Path(".env"), b""))


def test_shell_invocation_detection():
    assert list(issues(Path("bin/codex-auto-resume"),
                       b"subprocess.run(cmd, shell=True)"))
