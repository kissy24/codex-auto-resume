import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
import uuid

import pytest

from test_detection import CLI, app

# Replace just the system launchctl call in child processes; CLI, locks, IPC and
# exec resume all follow the normal entry points across real process boundaries.
DRIVER = """
import os, runpy, sys
from pathlib import Path
sys.argv = sys.argv[1:]
app = runpy.run_path(sys.argv[0])
def launchctl(command, *args):
    marker = Path.home() / "loaded"
    with (Path.home() / "commands").open("a") as f:
        print(command, file=f)
    if command == "print":
        return int(not marker.exists())
    if command == "bootstrap":
        if (Path.home() / "refuse").exists(): return 1
        marker.touch()
    elif command == "bootout":
        if (Path.home() / "refuse-bootout").exists(): return 1
        marker.unlink()
    return 0
app["main"].__globals__["launchctl"] = launchctl
os.umask(0o077)
try:
    app["main"]()
except (app["Attention"], app["Retry"]) as e:
    sys.exit(str(e))
"""
FAILED = {"id": "fail1", "status": "failed", "error": {"codexErrorInfo": "usageLimitExceeded"}}
SUCCESS = {"id": "next", "status": "completed"}


class TestReservation:
    @pytest.fixture(autouse=True)
    def reservation(self, tmp_path):
        self.home = tmp_path.resolve()
        self.sid = str(uuid.uuid4())
        self.cwd = self.home / "project"
        self.cwd.mkdir()
        (self.home / "codex").symlink_to(Path(__file__).with_name("fake_codex.py").resolve())
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.home)+":"+os.environ["PATH"])
        self.job = self.home / "Library/Application Support/codex-auto-resume" / self.sid
        self.plist = self.home / "Library/LaunchAgents" / ("local.codex-auto-resume."+self.sid+".plist")
        self.opts = dict(sid=self.sid, turns=[FAILED],
                         limits=dict(rateLimits={"limitId": "codex", "primary": {"usedPercent": 0}},
                                     ordinaryUsageAllowed=True))
        self.configure()

    def configure(self, **opts):
        self.opts.update(opts)
        (self.home / "scenario").write_text(json.dumps(self.opts))

    def command(self, verb, *args, background=False, check=True):
        cmd = [sys.executable, "-c", DRIVER, str(CLI), verb, self.sid, *args]
        if background:
            return subprocess.Popen(cmd, env=self.env)
        result = subprocess.run(cmd, env=self.env, capture_output=True, text=True, timeout=10)
        if check:
            assert result.returncode == 0, result.stderr
        return result

    def state(self, **changes):
        path = self.job / "state.json"
        value = json.loads(path.read_text())
        if changes:
            value.update(changes)
            path.write_text(json.dumps(value))
        return value

    def test_resume_once_in_original_directory(self):
        self.command("watch")
        config = plistlib.loads(self.plist.read_bytes())
        assert config["ProgramArguments"][-2:] == ["_tick", self.sid]
        assert config["RunAtLoad"]
        assert config["StartInterval"] == 60
        self.command("watch")
        assert (self.home/"commands").read_text().count("bootstrap") == 1
        workers = [self.command("_tick", background=True) for _ in range(4)]
        assert [p.wait(10) for p in workers] == [0]*4
        sent = json.loads((self.home / "sent").read_text())
        assert sent == [str(self.cwd), "exec", "resume", self.sid, app["PROMPT"]]
        assert "done" in self.command("status").stdout
        assert not self.plist.exists()
        assert not (self.home/"loaded").exists()
        assert self.job.stat().st_mode & 0o777 == 0o700
        for path in self.job.iterdir():
            assert path.stat().st_mode & 0o777 == 0o600
            assert "PRIVATE-OUTPUT" not in path.read_text()
        self.command("watch", "--new")
        self.command("_tick")
        assert self.state()["phase"] == "watching"
        self.command("cancel")
        self.command("_tick")
        assert self.state()["phase"] == "cancelled"

    def test_deadline_rechecked_and_manual_turn_observed(self):
        self.configure(turns=[SUCCESS])
        self.command("watch")
        self.command("_tick")
        assert self.state()["phase"] == "watching"
        due = int(time.time()) + 10000
        self.opts["limits"]["rateLimits"]["secondary"] = dict(usedPercent=100, resetsAt=due)
        self.configure(turns=[FAILED])
        self.command("_tick")
        assert self.state()["due"] == due
        self.configure(account="apiKey")
        self.command("_tick")
        assert self.state()["phase"] == "waiting"
        self.configure(account="chatgpt")
        self.state(due=0)
        self.command("_tick")
        assert self.state()["due"] == due
        del self.opts["limits"]["rateLimits"]["secondary"]
        self.configure(turns=[FAILED, SUCCESS])
        self.state(due=0)
        self.command("_tick")
        assert self.state()["phase"] == "cancelled"
        assert not (self.home/"sent").exists()

    def test_overdue_wait_recovers_after_worker_restart(self):
        self.opts["limits"]["rateLimits"]["primary"] = dict(usedPercent=100, resetsAt=None)
        self.configure()
        self.command("watch")
        self.command("_tick")
        assert self.state()["phase"] == "waiting"
        assert not (self.home/"sent").exists()
        # A new process after sleep/login observes an overdue reservation.
        self.state(due=int(time.time()) - 300)
        self.command("_tick")
        assert self.state()["phase"] == "waiting"
        assert not (self.home/"sent").exists()
        self.opts["limits"]["rateLimits"]["primary"] = dict(usedPercent=5)
        self.configure()
        self.state(due=int(time.time()) - 1)
        self.command("_tick")
        self.command("_tick")
        assert self.state()["phase"] == "done"
        assert len((self.home/"sent").read_text().splitlines()) == 1
        assert not self.plist.exists()

    def test_crash_recovery_and_cancel_during_exec(self):
        self.command("watch")
        hold = self.home/"hold"
        hold.touch()
        proc = self.command("_tick", background=True)
        try:
            for _ in range(200):
                if (self.home/"sent").exists():
                    break
                time.sleep(0.02)
            assert (self.home/"sent").exists()
            self.command("_tick")
            assert "dispatching" in self.command("cancel").stdout
            assert self.plist.exists()
            proc.kill()
            proc.wait(10)
        finally:
            hold.unlink()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.command("_tick")
        assert "needs_attention" in self.command("status").stdout
        assert not self.plist.exists()
        assert len((self.home/"sent").read_text().splitlines()) == 1

    def test_cleanup_failure_preserves_dispatch_result(self):
        self.command("watch")
        refuse = self.home / "refuse-bootout"
        refuse.touch()
        assert self.command("_tick", check=False).returncode != 0
        result = self.state()
        assert (result["phase"], result["exit_code"]) == ("done", 0)
        assert self.command("_tick", check=False).returncode != 0
        assert self.state() == result
        refuse.unlink()
        self.command("_tick")
        assert not (self.home / "loaded").exists()
        assert not self.plist.exists()
        assert self.state() == result
        assert len((self.home / "sent").read_text().splitlines()) == 1

    def test_registration_failure_and_retry(self):
        refuse = self.home/"refuse"
        refuse.touch()
        assert self.command("watch", check=False).returncode != 0
        assert not self.plist.exists()
        assert self.state()["phase"] == "needs_attention"
        refuse.unlink()
        self.command("watch")
        assert self.plist.exists()
        self.command("cancel")
        assert not self.plist.exists()

    def test_backoff_then_auth_failure(self):
        self.command("watch")
        self.configure(error={"code": -32000, "message": "PRIVATE-OUTPUT"})
        for delay in (60, 120, 240, 480, 900, 900):
            self.state(due=0)
            before = int(time.time())
            self.command("_tick")
            state = self.state()
            assert before+delay <= state["due"] <= int(time.time())+delay
            assert state["turn"] == FAILED["id"]
            assert "PRIVATE-OUTPUT" not in str(state)
        self.configure(account="apiKey")
        self.state(due=0)
        self.command("_tick")
        assert self.state()["phase"] == "needs_attention"

    def test_cli_failure_and_missing_cwd(self):
        self.command("watch")
        (self.home/"exit").write_text("17")
        self.command("_tick")
        assert self.state()["exit_code"] == 17
        assert self.state()["phase"] == "needs_attention"
        self.command("watch", "--new")
        shutil.rmtree(self.cwd)
        self.command("_tick")
        assert self.state()["phase"] == "needs_attention"
