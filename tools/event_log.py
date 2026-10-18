#!/usr/bin/env python3
"""Event log: one record per finished agent, so the audit of the auditors is possible.

Agent transcripts are usually deleted after a retention period; without a log of
what each agent produced, the raw material for auditing the process disappears.
This module writes one JSON line per event to <root>/events/<YYYY-MM-DD>.jsonl.

Schema (schema_version 1, always present so a future change does not silently
break queries):
  event_id, schema_version, ts, mechanism, agent_type, session_id, project,
  thread, model, status, error, duration_s,
  tokens{input, output, cache_read, cache_write},
  task{summary, sha256}, output{summary, sha256, words, artifacts[{path, sha256}]}

Ways to write an event:
  * as a library:   record_event(mechanism="script", agent_type="data-provenance", ...)
  * from the CLI:   event_log.py record --agent-type X --artifact out.json --status ok
  * as a Claude Code SubagentStop hook:  event_log.py hook   (reads the hook JSON on stdin)

In hook mode the transcript is parsed for Write/Edit tool calls (artifacts),
token usage, the model name and the final text. If an audit agent finishes
without writing any artifact, the hook prints a warning as `systemMessage`.

Privacy: with --hash-only or AUDIT_EVENT_HASH_ONLY=1 only hashes of task and
output text are stored, never the text itself.

Root: --root, else $AUDIT_ROOT, else ./.audit. Standard library only.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 1
SUMMARY_CHARS = 600
AUDIT_AGENT = re.compile(r"^(data-|ml-|physics-|geo-|math-|arch-|critic-|coord-|traceability-)")
THREAD_RE = re.compile(r"threads[/\\]([^\s\"'(),:;`<>\[\]]+)")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def events_dir(root=None):
    return Path(root or os.environ.get("AUDIT_ROOT") or ".audit").resolve() / "events"


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def sha256_file(path, limit_mb=200):
    p = Path(path)
    if not p.is_file():
        return None
    if p.stat().st_size > limit_mb * 1024 * 1024:
        return f"size:{p.stat().st_size}"
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def summary(text, limit=SUMMARY_CHARS):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "..."


def thread_of(text):
    m = THREAD_RE.search(text or "")
    return m.group(1).rstrip("/.") if m else None


def record_event(*, mechanism, agent_type, task_text="", output_text="", artifacts=(), status="ok",
                 error=None, model=None, tokens=None, session_id=None, project=None, duration_s=None,
                 hash_only=None, root=None, ts=None):
    """Append one event and return it."""
    if hash_only is None:
        hash_only = os.environ.get("AUDIT_EVENT_HASH_ONLY") == "1"
    ts = ts or time.strftime("%Y-%m-%dT%H:%M:%S")
    tok = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    tok.update({k: int(v or 0) for k, v in (tokens or {}).items() if k in tok})
    arts, seen = [], set()
    for a in artifacts:
        a = str(a)
        if a not in seen:
            seen.add(a)
            arts.append({"path": a, "sha256": sha256_file(a)})
    ev = {
        "event_id": uuid.uuid4().hex,
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "mechanism": mechanism,
        "agent_type": agent_type,
        "session_id": session_id,
        "project": project,
        "thread": thread_of(task_text),
        "model": model,
        "status": status,
        "error": error,
        "duration_s": duration_s,
        "tokens": tok,
        "task": {"summary": None if hash_only else summary(task_text), "sha256": sha256_text(task_text)},
        "output": {"summary": None if hash_only else summary(output_text), "sha256": sha256_text(output_text),
                   "words": len((output_text or "").split()), "artifacts": arts},
    }
    d = events_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{ts[:10]}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def parse_transcript(path):
    """Extract task text, final text, artifacts, tokens and model from a JSONL transcript."""
    out = {"task": "", "final": "", "artifacts": [], "tokens": {"input": 0, "output": 0, "cache_read": 0,
                                                                "cache_write": 0}, "model": None}
    p = Path(path) if path else None
    if not p or not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if rec.get("type") == "user" and not out["task"]:
            if isinstance(content, str):
                out["task"] = content
            elif isinstance(content, list):
                out["task"] = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
        if rec.get("type") == "assistant":
            out["model"] = msg.get("model") or out["model"]
            u = msg.get("usage") or {}
            out["tokens"]["input"] += int(u.get("input_tokens") or 0)
            out["tokens"]["output"] += int(u.get("output_tokens") or 0)
            out["tokens"]["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
            out["tokens"]["cache_write"] += int(u.get("cache_creation_input_tokens") or 0)
            texts = []
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_use" and c.get("name") in WRITE_TOOLS:
                    fp = (c.get("input") or {}).get("file_path") or (c.get("input") or {}).get("notebook_path")
                    if fp:
                        out["artifacts"].append(fp)
                elif c.get("type") == "text":
                    texts.append(c.get("text", ""))
            if texts:
                out["final"] = "\n".join(texts)
    return out


def hook(stdin_text, root=None):
    """Claude Code SubagentStop/Stop hook entry point. Returns the warning dict (or None)."""
    try:
        payload = json.loads(stdin_text or "{}")
    except json.JSONDecodeError:
        payload = {}
    transcript = payload.get("agent_transcript_path") or payload.get("transcript_path")
    agent_type = payload.get("agent_type") or ("main_session" if payload.get("hook_event_name") == "Stop"
                                               else "subagent")
    t = parse_transcript(transcript)
    record_event(mechanism="claude_code_" + ("subagent" if payload.get("hook_event_name") != "Stop" else "session"),
                 agent_type=agent_type, task_text=t["task"], output_text=t["final"], artifacts=t["artifacts"],
                 model=t["model"], tokens=t["tokens"], session_id=payload.get("session_id"),
                 project=Path(payload.get("cwd") or ".").name, root=root)
    if AUDIT_AGENT.match(agent_type) and not t["artifacts"]:
        return {"systemMessage": f"[event_log] audit agent '{agent_type}' finished without writing an artifact; "
                                 f"its verdict is not on disk and cannot be verified."}
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--agent-type", required=True)
    r.add_argument("--mechanism", default="script")
    r.add_argument("--task", default="")
    r.add_argument("--output", default="")
    r.add_argument("--artifact", action="append", default=[])
    r.add_argument("--status", default="ok", choices=["ok", "error", "partial"])
    r.add_argument("--error")
    r.add_argument("--model")
    r.add_argument("--project")
    r.add_argument("--hash-only", action="store_true")
    sub.add_parser("hook")
    a = ap.parse_args(argv)
    if a.cmd == "record":
        ev = record_event(mechanism=a.mechanism, agent_type=a.agent_type, task_text=a.task, output_text=a.output,
                          artifacts=a.artifact, status=a.status, error=a.error, model=a.model, project=a.project,
                          hash_only=a.hash_only or None, root=a.root)
        print(ev["event_id"])
    else:
        warn = hook(sys.stdin.read(), root=a.root)
        if warn:
            print(json.dumps(warn))


if __name__ == "__main__":
    main()
