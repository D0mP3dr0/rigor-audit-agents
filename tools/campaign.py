#!/usr/bin/env python3
"""Mechanical parts of an audit campaign: validate artifacts, pick findings to vote, tally votes.

The agents judge; this script enforces the rules that must not depend on judgment.

Commands:
  campaign.py validate  FILE...             check front artifacts / votes / coverage against the schema
  campaign.py to-vote   --out-dir DIR       list findings that must go to adversarial verification
  campaign.py tally     --out-dir DIR       apply the voting rule to DIR/verification/*.json
                                            and write DIR/tally.json

Voting rule (the part that must never be left to an agent):
  * a vote counts as a refutation ONLY if it is refuted=true AND carries a
    non-empty command_run (a refutation without execution is not a refutation);
  * quorum is at least 2 valid votes out of 3;
  * a finding survives unless it has quorum AND at least 2 executed refutations;
  * a finding without quorum survives as NOT VERIFIED, never as refuted.
Being expensive to check is not a reason to drop a finding: "not verifiable" votes
keep it alive.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SEVERITIES = ("block", "warn", "note")
FRONT_VERDICTS = ("pass", "block", "warn")
VOTE_CLASSES = ("refuted_by_execution", "confirmed", "not_verifiable")
COVERAGE_VERDICTS = ("complete", "partial", "insufficient")


def _err(errs, cond, msg):
    if not cond:
        errs.append(msg)


def validate_front(doc):
    errs = []
    for k in ("front", "target", "verdict", "findings", "coverage", "file"):
        _err(errs, k in doc, f"missing key: {k}")
    _err(errs, doc.get("verdict") in FRONT_VERDICTS, f"verdict must be one of {FRONT_VERDICTS}")
    ids = set()
    for i, f in enumerate(doc.get("findings") or []):
        for k in ("id", "severity", "description", "evidence"):
            _err(errs, k in f, f"finding[{i}] missing key: {k}")
        _err(errs, f.get("severity") in SEVERITIES, f"finding[{i}] severity must be one of {SEVERITIES}")
        ev = f.get("evidence") or {}
        _err(errs, isinstance(ev, dict) and (ev.get("command") or ev.get("file")),
             f"finding[{i}] evidence needs a command or a file")
        _err(errs, f.get("id") not in ids, f"finding[{i}] duplicate id {f.get('id')}")
        ids.add(f.get("id"))
    cov = doc.get("coverage") or {}
    _err(errs, isinstance(cov.get("verified"), list) and cov.get("verified"),
         "coverage.verified must list at least one item")
    if cov.get("not_verified"):
        _err(errs, bool(cov.get("reason")), "coverage.not_verified needs a reason")
    blocking = [f for f in doc.get("findings") or [] if f.get("severity") == "block"]
    if blocking:
        _err(errs, doc.get("verdict") == "block", "a block finding requires verdict=block")
    return errs


def validate_vote(doc):
    errs = []
    for k in ("finding_id", "refuted", "reason"):
        _err(errs, k in doc, f"missing key: {k}")
    _err(errs, isinstance(doc.get("refuted"), bool), "refuted must be boolean")
    if "reason_class" in doc:
        _err(errs, doc["reason_class"] in VOTE_CLASSES, f"reason_class must be one of {VOTE_CLASSES}")
    if doc.get("refuted"):
        _err(errs, bool((doc.get("command_run") or "").strip()), "refuted=true requires command_run")
    return errs


def validate_coverage(doc):
    errs = []
    for k in ("expected_fronts", "delivered_fronts", "missing_fronts", "coverage_verdict"):
        _err(errs, k in doc, f"missing key: {k}")
    _err(errs, doc.get("coverage_verdict") in COVERAGE_VERDICTS, f"coverage_verdict must be one of {COVERAGE_VERDICTS}")
    return errs


def validate(doc):
    if "finding_id" in doc:
        return "vote", validate_vote(doc)
    if "coverage_verdict" in doc or "expected_fronts" in doc:
        return "coverage", validate_coverage(doc)
    return "front", validate_front(doc)


def front_artifacts(out_dir):
    skip = {"critic-coverage.json", "tally.json", "memory.json"}
    for f in sorted(Path(out_dir).glob("*.json")):
        if f.name in skip:
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        if "front" in doc and "findings" in doc:
            yield f, doc


def to_vote(out_dir):
    rows = []
    for f, doc in front_artifacts(out_dir):
        for fi in doc["findings"]:
            if fi.get("severity") == "block" or fi.get("supports_claim") is True:
                rows.append({"front": doc["front"], "finding_id": fi["id"], "severity": fi["severity"],
                             "supports_claim": bool(fi.get("supports_claim")), "artifact": str(f)})
    return rows


def tally_votes(votes):
    valid = [v for v in votes if not validate_vote(v)]
    refutations = sum(1 for v in valid if v["refuted"] and (v.get("command_run") or "").strip())
    not_verifiable = sum(1 for v in valid if v.get("reason_class") == "not_verifiable")
    quorum = len(valid) >= 2
    survives = (not quorum) or refutations < 2
    status = "refuted" if not survives else ("confirmed" if quorum else "not_verified")
    return {"votes": len(votes), "valid_votes": len(valid), "refutations": refutations,
            "not_verifiable": not_verifiable, "quorum": quorum, "survives": survives, "status": status,
            "reasons": [v.get("reason", "") for v in valid]}


def tally(out_dir):
    out_dir = Path(out_dir)
    by_id = defaultdict(list)
    for f in sorted((out_dir / "verification").glob("*.json")):
        by_id[json.loads(f.read_text(encoding="utf-8")).get("finding_id")].append(
            json.loads(f.read_text(encoding="utf-8")))
    pending = {r["finding_id"]: r for r in to_vote(out_dir)}
    result = []
    for fid, row in pending.items():
        t = tally_votes(by_id.get(fid, []))
        result.append({**row, **t})
    doc = {"rule": "refutation needs an executed command; quorum >= 2 of 3; survives unless quorum and >= 2 refutations",
           "findings": result,
           "surviving": [r["finding_id"] for r in result if r["survives"]],
           "refuted": [r["finding_id"] for r in result if not r["survives"]]}
    (out_dir / "tally.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("validate")
    s.add_argument("files", nargs="+")
    s = sub.add_parser("to-vote")
    s.add_argument("--out-dir", required=True)
    s = sub.add_parser("tally")
    s.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        bad = 0
        for f in a.files:
            if Path(f).name in ("tally.json", "memory.json"):
                continue  # written by this tool / by the reader, not by agents
            kind, errs = validate(json.loads(Path(f).read_text(encoding="utf-8")))
            print(f"{f} [{kind}]: " + ("ok" if not errs else "; ".join(errs)))
            bad += bool(errs)
        sys.exit(1 if bad else 0)
    if a.cmd == "to-vote":
        print(json.dumps(to_vote(a.out_dir), ensure_ascii=False, indent=1))
    if a.cmd == "tally":
        print(json.dumps(tally(a.out_dir), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
