"""Script-only walkthrough of an audit campaign on the example project (no LLM involved).

What a real campaign does with agents, this script does with the reference
scripts, so that the mechanics can be run and tested anywhere:

  setup     copy the project to --work, generate the data, train once
  thread    open an audit thread on the project (thread.py)
  fronts    run the two reference front scripts (spatial leakage, seeds) and post
  validate  check the artifacts against the schema (campaign.py validate)
  verify    three scripted verifiers per finding re-execute the evidence command
            into their own directory and vote; campaign.py tally applies the rule
  coverage  mechanical coverage check of the two-front matrix
  close     coordinator synthesis citing every blocking post, check, close
  events    one event per step in the event log; a saved query counts them

In the real campaign the fronts, verifiers, coverage critic and coordinator are
the subagents in agents/, convened by a skill in skills/. Only the judgment
moves to the agents; every mechanical rule used here stays the same.
"""
import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "tools"
COORD = "coord-ml"
FRONTS = {"data-spatial-leakage": HERE / "reference_audit" / "leakage_check.py",
          "ml-seed-reproducibility": HERE / "reference_audit" / "seed_check.py"}

sys.path.insert(0, str(TOOLS))
import campaign  # noqa: E402
import event_log  # noqa: E402


def sh(args, **kw):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True, **kw).stdout.strip()


def tool(name, *args, root):
    return sh([sys.executable, TOOLS / name, "--root", root, *args])


def scripted_vote(finding, vote, out_dir):
    """Re-execute the evidence command into a fresh directory and check that the finding reappears."""
    cmd = shlex.split(finding["evidence"]["command"])
    rerun_dir = out_dir / "verification" / f"rerun_{finding['id']}_{vote}"
    cmd[cmd.index("--out") + 1] = str(rerun_dir)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    vote_doc = {"finding_id": finding["id"], "command_run": " ".join(shlex.quote(c) for c in cmd)}
    if proc.returncode != 0:
        vote_doc.update(refuted=False, reason_class="not_verifiable",
                        reason=f"command failed: {proc.stderr.strip()[:200]}")
    else:
        art = next(rerun_dir.glob("*.json"))
        again = {f["id"]: f for f in json.loads(art.read_text(encoding="utf-8"))["findings"]}
        if finding["id"] in again and again[finding["id"]]["severity"] == finding["severity"]:
            vote_doc.update(refuted=False, reason_class="confirmed",
                            reason="re-execution reproduces the finding with the same severity",
                            suggested_severity=finding["severity"])
        else:
            vote_doc.update(refuted=True, reason_class="refuted_by_execution",
                            reason="re-execution does not reproduce the finding")
    path = out_dir / "verification" / f"{finding['id']}_{vote}.json"
    path.write_text(json.dumps(vote_doc, indent=1), encoding="utf-8")
    return path, vote_doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="walkthrough_run")
    ap.add_argument("--n", type=int, default=1500)
    a = ap.parse_args(argv)
    work = Path(a.work).resolve()
    if work.exists():
        shutil.rmtree(work)
    project, out, root = work / "project", work / "audit_out", work / ".audit"
    shutil.copytree(HERE / "project", project, ignore=shutil.ignore_patterns("data", "results", "__pycache__"))
    (out / "verification").mkdir(parents=True)
    log = lambda agent, arts, task="": event_log.record_event(  # noqa: E731
        mechanism="script", agent_type=agent, task_text=task, artifacts=arts, root=root)

    # setup
    sh([sys.executable, project / "generate_data.py", "--out", project / "data", "--n", a.n])
    declared = json.loads(sh([sys.executable, project / "train.py"]))

    # thread
    thread = tool("thread.py", "open", "--key", "ml-synthetic-example", "--coordinator", COORD,
                  "--mission", "Is the held-out R2 of the example project citable as independent-test skill?",
                  "--target", project, root=root).splitlines()[-1]
    log("thread-open", [Path(thread) / "thread.json"], task=f"threads/{Path(thread).name}")

    # fronts
    post_ids = {}
    for front, script in FRONTS.items():
        sh([sys.executable, script, "--project", project, "--out", out])
        art_path = out / f"{front}.json"
        art = json.loads(art_path.read_text(encoding="utf-8"))
        ids = ", ".join(f["id"] for f in art["findings"]) or "none"
        post_ids[front] = tool("thread.py", "post", "--thread", thread, "--agent", front, "--to", COORD,
                               "--artifact", art_path, "--severity", "block" if art["verdict"] == "block" else "info",
                               "--text", f"Verdict {art['verdict']}; findings: {ids}. Detail and commands in the artifact.",
                               *(["--supports-claim"] if any(f.get("supports_claim") for f in art["findings"]) else []),
                               root=root)
        log(front, [art_path], task=f"threads/{Path(thread).name}")

    # validate
    for front in FRONTS:
        kind, errs = campaign.validate(json.loads((out / f"{front}.json").read_text(encoding="utf-8")))
        if errs:
            raise SystemExit(f"invalid artifact {front}: {errs}")

    # verify: three votes per finding to vote on
    findings = {}
    for front in FRONTS:
        for f in json.loads((out / f"{front}.json").read_text(encoding="utf-8"))["findings"]:
            findings[f["id"]] = f
    for row in campaign.to_vote(out):
        for v in (1, 2, 3):
            path, _ = scripted_vote(findings[row["finding_id"]], v, out)
            log("critic-verifier", [path])
    tally = campaign.tally(out)

    # coverage (mechanical stand-in for critic-coverage)
    delivered = [f for f in FRONTS if (out / f"{f}.json").exists()]
    coverage = {"expected_fronts": list(FRONTS), "delivered_fronts": delivered,
                "missing_fronts": [{"front": f, "reason": "no artifact"} for f in FRONTS if f not in delivered],
                "components_without_owner": ["baseline fairness", "ablation", "experiment card", "silent bugs"],
                "contradictions": [],
                "coverage_verdict": "partial"}
    (out / "critic-coverage.json").write_text(json.dumps(coverage, indent=1), encoding="utf-8")
    log("critic-coverage", [out / "critic-coverage.json"])

    # close: synthesis must cite every blocking / claim-supporting post
    state = {fid: ("accepted" if fid in tally["surviving"] else "refuted") for fid in findings}
    lines = [f"Verdict: block. The held-out R2 {declared['r2']:.3f} is not citable as independent-test skill."]
    lines += [f"- `{pid}` {front}: " + ", ".join(f"{fid} {state[fid]}" for fid in findings
                                                  if fid.split('-')[0] == ('LEAK' if 'leak' in front else 'SEED'))
              for front, pid in post_ids.items()]
    lines += ["Coverage partial: only 2 of the 6 ML fronts ran (example scope).",
              "Round 2: blocked-CV re-evaluation with fixed seeds, then the remaining ML fronts."]
    synth = work / "synthesis.md"
    synth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tool("thread.py", "synthesis", "--thread", thread, "--coordinator", COORD, "--file", synth, root=root)
    check = subprocess.run([sys.executable, TOOLS / "thread.py", "--root", root, "check", "--thread", thread],
                           capture_output=True, text=True)
    if check.returncode == 0:
        tool("thread.py", "close", "--thread", thread, root=root)
    log(COORD, [synth, Path(thread) / "THREAD.md"], task=f"threads/{Path(thread).name}")
    reopen = subprocess.run([sys.executable, TOOLS / "thread.py", "--root", root, "open", "--key", "ml-synthetic-again",
                             "--coordinator", COORD, "--mission", "same target again", "--target", project],
                            capture_output=True, text=True)
    reopen_refused = reopen.returncode != 0 and "already audited" in (reopen.stderr + reopen.stdout)
    counts = json.loads(sh([sys.executable, TOOLS / "query_events.py", "--root", root, "--engine", "python",
                            "by-agent"]))

    leak = json.loads((out / "raw" / "leakage_synthetic.json").read_text(encoding="utf-8"))
    seeds = json.loads((out / "raw" / "seeds_synthetic.json").read_text(encoding="utf-8"))
    summary = {"declared": declared,
               "leakage": {k: leak[k] for k in ("practical_range_km", "fraction_test_inside_range", "block_km",
                                                "r2_random_cv", "r2_blocked_cv", "optimism_r2")},
               "seeds": {"unseeded_generator_lines": [c["line"] for c in seeds["static"]["unseeded_generators"]],
                         "r2_reruns": [r["r2"] for r in seeds["reruns"]], "same_test_set": seeds["same_test_set"]},
               "findings": {fid: {"severity": f["severity"], "status": state[fid]} for fid, f in findings.items()},
               "tally": {r["finding_id"]: r["status"] for r in tally["findings"]},
               "thread": thread, "thread_check": check.stdout.strip(), "reopen_refused": reopen_refused,
               "events_by_agent": counts}
    (work / "walkthrough_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    main()
