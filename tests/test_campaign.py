import json
import tempfile
import unittest
from pathlib import Path

import _util  # noqa: F401  (puts tools/ on sys.path)
import campaign


def front(findings, verdict="block"):
    return {"front": "data-contract", "target": "t", "verdict": verdict, "findings": findings,
            "coverage": {"verified": ["x"], "not_verified": [], "reason": ""}, "file": "f.json"}


def finding(fid, sev="block", claim=False):
    return {"id": fid, "severity": sev, "description": "d", "evidence": {"command": "run.py"},
            "supports_claim": claim}


def vote(refuted, cmd="", cls=None):
    v = {"finding_id": "F1", "refuted": refuted, "reason": "r", "command_run": cmd}
    if cls:
        v["reason_class"] = cls
    return v


class ValidateTest(unittest.TestCase):
    def test_valid_front(self):
        self.assertEqual(campaign.validate(front([finding("F1")]))[1], [])

    def test_front_errors(self):
        doc = front([finding("F1"), finding("F1", sev="fatal")], verdict="pass")
        doc["coverage"] = {"verified": [], "not_verified": ["y"]}
        errs = " | ".join(campaign.validate(doc)[1])
        for frag in ("duplicate id", "severity must be", "coverage.verified", "needs a reason", "verdict=block"):
            self.assertIn(frag, errs)

    def test_vote_refuted_needs_command(self):
        kind, errs = campaign.validate(vote(True))
        self.assertEqual(kind, "vote")
        self.assertIn("refuted=true requires command_run", errs)


class TallyTest(unittest.TestCase):
    def test_two_executed_refutations_kill(self):
        t = campaign.tally_votes([vote(True, "cmd"), vote(True, "cmd"), vote(False)])
        self.assertFalse(t["survives"])
        self.assertEqual(t["status"], "refuted")

    def test_refutation_without_execution_does_not_count(self):
        t = campaign.tally_votes([vote(True), vote(True), vote(False)])
        self.assertTrue(t["survives"])
        self.assertEqual(t["valid_votes"], 1)
        self.assertEqual(t["status"], "not_verified")  # invalid votes leave no quorum

    def test_not_verifiable_keeps_finding(self):
        t = campaign.tally_votes([vote(False, cls="not_verifiable")] * 3)
        self.assertTrue(t["survives"])
        self.assertEqual(t["not_verifiable"], 3)

    def test_no_quorum_is_not_verified(self):
        t = campaign.tally_votes([vote(True, "cmd")])
        self.assertTrue(t["survives"])
        self.assertEqual(t["status"], "not_verified")

    def test_to_vote_and_tally_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "verification").mkdir()
            (d / "raw").mkdir()
            (d / "data-contract.json").write_text(json.dumps(front(
                [finding("F1"), finding("F2", sev="warn", claim=True), finding("F3", sev="note")])))
            (d / "raw" / "x.json").write_text("{}")
            self.assertEqual([r["finding_id"] for r in campaign.to_vote(d)], ["F1", "F2"])
            for i, v in enumerate([vote(True, "c"), vote(True, "c"), vote(False)], 1):
                (d / "verification" / f"F1_{i}.json").write_text(json.dumps(v))
            doc = campaign.tally(d)
            self.assertEqual(doc["refuted"], ["F1"])
            self.assertEqual(doc["surviving"], ["F2"])
            self.assertTrue((d / "tally.json").exists())


if __name__ == "__main__":
    unittest.main()
