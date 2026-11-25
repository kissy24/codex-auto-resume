import runpy
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1] / "bin/codex-auto-resume"
app = runpy.run_path(str(CLI))
Attention = app["Attention"]


def response(snap, allowed=True, **extras):
    data = dict(rateLimitsByLimitId={"codex": snap}, ordinaryUsageAllowed=allowed, **extras)
    return lambda method, params: data


def test_only_structured_quota_failure():
    failed = dict(id="turn", status="failed", error={"codexErrorInfo": "usageLimitExceeded"})
    assert app["failed_turn"](failed) == "turn"
    for turn in [{}, {**failed, "status": "completed"}, {**failed, "status": "interrupted"},
                 {**failed, "error": {"message": "usageLimitExceeded"}}]:
        assert app["failed_turn"](turn) is None


def test_both_windows_and_unknown_reset():
    snap = dict(primary=dict(usedPercent=100, resetsAt=200),
                secondary=dict(usedPercent=101, resetsAt=400))
    assert app["limits"](response(snap), None) == ("codex", True, 400)
    del snap["secondary"]["resetsAt"]
    assert app["limits"](response(snap), None) == ("codex", True, 200)
    snap["primary"]["usedPercent"] = 0
    assert app["limits"](response(snap), None) == ("codex", True, 0)


def test_ordinary_usage_and_cost_controls():
    snap = dict(primary=dict(usedPercent=0))
    assert app["limits"](response(snap), None) == ("codex", False, 0)
    assert app["limits"](response(snap, False), None)[1]
    for call in [response(snap, None), response({**snap, "spendControlReached": True}),
                 response({**snap, "rateLimitReachedType": "workspace_member_credits_depleted"}),
                 response({}), response(dict(primary={})), response(dict(limitId="other"))]:
        with pytest.raises(Attention):
            app["limits"](call, None)


def test_ambiguous_or_missing_bucket():
    snap = dict(primary=dict(usedPercent=0))
    call = lambda *_: dict(rateLimitsByLimitId={"codex": snap, "other": snap},
                           ordinaryUsageAllowed=True)
    for name in [None, "missing"]:
        with pytest.raises(Attention):
            app["limits"](call, name)
    assert app["limits"](call, "other")[0] == "other"
