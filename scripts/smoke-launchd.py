#!/usr/bin/env python3.14
"""Exercise the installed tool with real user launchd and a fake Codex in a temporary HOME."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != "darwin":
        sys.exit("macOS のログインセッションで実行してください")
    sid = str(uuid.uuid4())
    service = f"gui/{os.getuid()}/local.codex-auto-resume.{sid}"
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp).resolve()
        tools = home / ".local/bin"
        tools.mkdir(parents=True)
        cli = tools / "codex-auto-resume"
        shutil.copy2(ROOT / "bin/codex-auto-resume", cli)
        shutil.copy2(ROOT / "tests/fake_codex.py", tools / "codex")
        (home / "project").mkdir()
        scenario = dict(sid=sid, turns=[dict(id="failed", status="failed",
                        error={"codexErrorInfo": "usageLimitExceeded"})],
                        limits=dict(rateLimits=dict(limitId="codex", primary=dict(usedPercent=0)),
                                    ordinaryUsageAllowed=True))
        (home / "scenario").write_text(json.dumps(scenario))
        python_bin = Path(sys.executable).resolve().parent
        env = dict(HOME=str(home), PATH=f"{tools}:{python_bin}:/usr/bin:/bin")
        def command(name):
            return subprocess.check_output([str(cli), name, sid], env=env, text=True, timeout=30)
        def loaded():
            return subprocess.run(["/bin/launchctl", "print", service], capture_output=True).returncode == 0
        try:
            command("watch")
            for _ in range(100):
                if command("status").startswith("done") and not loaded():
                    break
                time.sleep(0.2)
            else:
                sys.exit("RunAtLoad または終端時の解除を確認できません: " + command("status"))
            sent = json.loads((home / "sent").read_text())
            state_dir = home / "Library/Application Support/codex-auto-resume" / sid
            state = json.loads((state_dir / "state.json").read_text())
            assert Path(state["python"]).samefile(sys.executable)
            assert sent[:4] == [str(home / "project"), "exec", "resume", sid]
            assert not list((home / "Library/LaunchAgents").glob("*.plist"))
            assert command("cancel").startswith("done")
            scenario["turns"] = []
            (home / "scenario").write_text(json.dumps(scenario))
            subprocess.run([str(cli), "watch", sid, "--new"], env=env, check=True, timeout=30)
            assert loaded()
            assert command("cancel").startswith("cancelled")
            assert not loaded()
            print("LaunchAgent の登録、自動起動、一回送信、終了・手動解除を確認しました")
        finally:
            if loaded():
                subprocess.run(["/bin/launchctl", "bootout", service], check=True)


if __name__ == "__main__":
    main()
