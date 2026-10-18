#!/usr/bin/env python3
"""Registry of viability tests: every experimental change to the audit process is a test.

A process change (a new gate, a new front, a stricter rule) enters the registry as
an open test with an entry date and an EXIT QUESTION: what must be true for the
test to become permanent, or to be withdrawn. A periodic review is obliged to
give each open test a verdict; tests older than --max-age-days are reported as
stale so that nothing stays "experimental" forever.

Files (under <root>/experiments/):
  registry.json   source of truth (machine)
  REGISTRY.md     generated view (humans)

Commands:
  experiment_registry.py list   [--open] [--json]
  experiment_registry.py open   --id X --title "..." --question "..." [--origin ...] [--measure ...] [--components a,b]
  experiment_registry.py close  --id X --verdict adopted|withdrawn|renewed|not_executed --reason "..."
  experiment_registry.py stale  [--max-age-days 60]     exit 1 if any open test is older
  experiment_registry.py render

Root: --root, else $AUDIT_ROOT, else ./.audit. Standard library only.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

VERDICTS = ["adopted", "withdrawn", "renewed", "not_executed"]


def paths(root=None):
    base = Path(root or os.environ.get("AUDIT_ROOT") or ".audit").resolve() / "experiments"
    return base, base / "registry.json", base / "REGISTRY.md"


def today():
    return dt.date.today().isoformat()


def load(root=None):
    _, reg, _ = paths(root)
    if reg.exists():
        return json.loads(reg.read_text(encoding="utf-8"))
    return {"_doc": "Registry of viability tests for the audit process.", "tests": []}


def save(data, root=None):
    base, reg, _ = paths(root)
    base.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    render(data, root)


def render(data=None, root=None):
    data = data or load(root)
    base, _, md = paths(root)
    base.mkdir(parents=True, exist_ok=True)
    lines = ["# Registry of viability tests", "",
             "Generated from `registry.json`; do not edit here. Every experimental change",
             "to the audit process enters as a test with an exit question; the periodic",
             "review must give a verdict (adopted / withdrawn / renewed / not_executed),",
             "backed by evidence from the event log, never by reading logs by eye.", ""]
    open_t = [t for t in data["tests"] if t.get("state") == "open"]
    closed = [t for t in data["tests"] if t.get("state") != "open"]
    lines.append(f"## Open ({len(open_t)})\n")
    for t in open_t:
        lines += [f"### {t['id']} - {t['title']}",
                  f"- Entered: {t['entered']} | Origin: {t.get('origin', '')}",
                  f"- Exit question: {t['question']}",
                  f"- How to measure: {t.get('measure', '')}",
                  f"- Components: {', '.join(t.get('components', []))}", ""]
    lines.append(f"## Closed ({len(closed)})\n")
    for t in closed:
        lines.append(f"- {t['id']} - {t['title']}: **{t.get('verdict')}** on {t.get('closed_at', '')} - "
                     f"{t.get('reason', '')}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md


def open_test(data, tid, title, question, origin="", measure="", components=""):
    if any(t["id"] == tid for t in data["tests"]):
        raise SystemExit(f"id already exists: {tid}")
    data["tests"].append({"id": tid, "title": title, "question": question, "origin": origin,
                          "measure": measure,
                          "components": [c.strip() for c in components.split(",") if c.strip()],
                          "entered": today(), "state": "open"})
    return data


def close_test(data, tid, verdict, reason):
    if verdict not in VERDICTS:
        raise SystemExit(f"verdict must be one of {VERDICTS}")
    for t in data["tests"]:
        if t["id"] == tid:
            if verdict == "renewed":  # renewal restarts the clock and keeps the test open
                t["entered"] = today()
                t.setdefault("renewals", []).append({"when": t["entered"], "reason": reason})
            else:
                t.update({"state": "closed", "verdict": verdict, "reason": reason, "closed_at": today()})
            return data
    raise SystemExit(f"id not found: {tid}")


def stale(data, max_age_days=60, on=None):
    on = dt.date.fromisoformat(on) if on else dt.date.today()
    out = []
    for t in data["tests"]:
        if t.get("state") == "open":
            age = (on - dt.date.fromisoformat(t["entered"])).days
            if age > max_age_days:
                out.append({"id": t["id"], "age_days": age, "title": t["title"]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--open", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("open")
    p.add_argument("--id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--origin", default="")
    p.add_argument("--measure", default="")
    p.add_argument("--components", default="")
    p = sub.add_parser("close")
    p.add_argument("--id", required=True)
    p.add_argument("--verdict", required=True, choices=VERDICTS)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("stale")
    p.add_argument("--max-age-days", type=int, default=60)
    sub.add_parser("render")
    a = ap.parse_args(argv)
    data = load(a.root)
    if a.cmd == "list":
        ts = [t for t in data["tests"] if not a.open or t.get("state") == "open"]
        if a.json:
            print(json.dumps(ts, ensure_ascii=False, indent=1))
        else:
            for t in ts:
                print(f"[{t.get('state')}] {t['id']} ({t['entered']}) {t['title']} -> {t['question'][:100]}")
    elif a.cmd == "open":
        save(open_test(data, a.id, a.title, a.question, a.origin, a.measure, a.components), a.root)
        print(f"opened: {a.id}")
    elif a.cmd == "close":
        save(close_test(data, a.id, a.verdict, a.reason), a.root)
        print(f"{a.verdict}: {a.id}")
    elif a.cmd == "stale":
        s = stale(data, a.max_age_days)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        sys.exit(1 if s else 0)
    elif a.cmd == "render":
        print(render(data, a.root))


if __name__ == "__main__":
    main()
