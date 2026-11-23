import runpy
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "bin/codex-auto-resume"
app = runpy.run_path(str(CLI))
Attention = app["Attention"]


def response(snap, allowed=True, **extras):
    data = dict(rateLimitsByLimitId={"codex": snap}, ordinaryUsageAllowed=allowed, **extras)
    return lambda method, params: data


class Detection(unittest.TestCase):
    def test_only_structured_quota_failure(self):
        failed = dict(id="turn", status="failed", error={"codexErrorInfo": "usageLimitExceeded"})
        self.assertEqual(app["failed_turn"](failed), "turn")
        for turn in [{}, {**failed, "status": "completed"}, {**failed, "status": "interrupted"},
                     {**failed, "error": {"message": "usageLimitExceeded"}}]:
            self.assertIsNone(app["failed_turn"](turn))

    def test_both_windows_and_unknown_reset(self):
        snap = dict(primary=dict(usedPercent=100, resetsAt=200),
                    secondary=dict(usedPercent=101, resetsAt=400))
        self.assertEqual(app["limits"](response(snap), None), ("codex", True, 400))
        del snap["secondary"]["resetsAt"]
        self.assertEqual(app["limits"](response(snap), None), ("codex", True, 200))
        snap["primary"]["usedPercent"] = 0
        self.assertEqual(app["limits"](response(snap), None), ("codex", True, 0))

    def test_ordinary_usage_and_cost_controls(self):
        snap = dict(primary=dict(usedPercent=0))
        self.assertEqual(app["limits"](response(snap), None), ("codex", False, 0))
        self.assertTrue(app["limits"](response(snap, False), None)[1])
        for call in [response(snap, None), response({**snap, "spendControlReached": True}),
                     response({**snap, "rateLimitReachedType": "workspace_member_credits_depleted"}),
                     response({}), response(dict(primary={})), response(dict(limitId="other"))]:
            with self.assertRaises(Attention):
                app["limits"](call, None)

    def test_ambiguous_or_missing_bucket(self):
        snap = dict(primary=dict(usedPercent=0))
        call = lambda *_: dict(rateLimitsByLimitId={"codex": snap, "other": snap},
                               ordinaryUsageAllowed=True)
        for name in [None, "missing"]:
            with self.assertRaises(Attention):
                app["limits"](call, name)
        self.assertEqual(app["limits"](call, "other")[0], "other")
