#!/usr/bin/env python3
"""Audit thread: a file-based message bus and record for one audit mission.

Every agent in a campaign talks through the thread, and because the thread is
made of files it is also the record: what is not in the thread did not happen.

Layout (under <root>/threads/<YYYY-MM-DD>_<key>/):
  thread.json      header: key, mission, coordinator, target, target hash,
                   token budget, opened_at, closed_at
  posts/<HHMMSS>_<agent>.md   one file per post, written only by its author
  SYNTHESIS.md     written only by the coordinator, <= 15 non-empty lines
  THREAD.md        generated view; never edit by hand

Commands:
  thread.py open      --key K --mission "..." --coordinator AG [--target PATH]
                      [--budget-tokens N] [--force "reason"]
  thread.py post      --thread DIR --agent AG --to X --artifact PATH (--text "..." | --file F)
                      [--reply-to ID] [--severity block|warn|info] [--supports-claim] [--tokens N]
  thread.py synthesis --thread DIR --coordinator AG (--text "..." | --file F)
  thread.py render    --thread DIR
  thread.py check     --thread DIR      exit 0 clean, 1 with problems
  thread.py total     --thread DIR      tokens used vs budget
  thread.py close     --thread DIR
  thread.py list      [--open]

The root is --root, else $AUDIT_ROOT, else ./.audit. Standard library only.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

MAX_WORDS = 200
MAX_SYNTHESIS_LINES = 15
CONTENT_HASH_LIMIT = 200 * 1024 * 1024  # above this, hash (path, size, mtime) instead of content
SKIP_PARTS = (".git", "__pycache__", ".venv", ".audit")
EMPTY_SYNTHESIS = "(no synthesis yet"


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def root_dir(arg=None):
    return Path(arg or os.environ.get("AUDIT_ROOT") or ".audit").resolve()


def threads_dir(root):
    return Path(root) / "threads"


def audited_file(root):
    return threads_dir(root) / "audited_targets.jsonl"


def hash_target(path):
    """sha256 over the content of every file in the target (file or directory).

    Content is hashed up to CONTENT_HASH_LIMIT in total; larger targets fall back
    to (relative path, size, mtime). Hashing content rather than metadata matters
    because sync tools preserve mtime, so a stat-only hash is blind to swapped data.
    """
    p = Path(path)
    if p.is_file():
        files = [p]
    else:
        files = sorted(f for f in p.rglob("*") if f.is_file() and not any(x in f.parts for x in SKIP_PARTS))
    total = sum(f.stat().st_size for f in files)
    h = hashlib.sha256()
    for f in files:
        rel = f.name if p.is_file() else f.relative_to(p).as_posix()
        if total <= CONTENT_HASH_LIMIT:
            h.update(rel.encode())
            with open(f, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
        else:
            st = f.stat()
            h.update(f"{rel}|{st.st_size}|{int(st.st_mtime)}".encode())
    h.update(b"content" if total <= CONTENT_HASH_LIMIT else b"stat")
    return h.hexdigest()


def read_thread(d):
    d = Path(d)
    return d, json.loads((d / "thread.json").read_text(encoding="utf-8"))


def write_header(d, header):
    (Path(d) / "thread.json").write_text(json.dumps(header, ensure_ascii=False, indent=1), encoding="utf-8")


def read_post(p):
    text = p.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    head = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                head[k.strip()] = v.split(" #")[0].strip()
        body = m.group(2).strip()
    else:
        body = text.strip()
    head["_id"] = p.stem
    head["_body"] = body
    head["_words"] = len(body.split())
    return head


def posts(d):
    # Post ids carry only HHMMSS; a thread that crosses midnight would sort the
    # next day's posts first. Chronological order is the file mtime (posts are
    # never edited after creation), with the id as tie-breaker.
    files = sorted((Path(d) / "posts").glob("*.md"), key=lambda q: (q.stat().st_mtime, q.name))
    return [read_post(p) for p in files]


def cmd_open(a):
    root = root_dir(a.root)
    tdir = threads_dir(root)
    tdir.mkdir(parents=True, exist_ok=True)
    for f in tdir.glob(f"*_{a.key}"):
        if (f / "thread.json").exists() and json.loads((f / "thread.json").read_text()).get("closed_at") is None:
            sys.exit(f"REFUSED: a thread with key '{a.key}' is already open: {f}")
    h = hash_target(a.target) if a.target else None
    af = audited_file(root)
    if h and af.exists() and not a.force:
        for line in af.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("hash") == h:
                sys.exit(f"REFUSED: target already audited without change at {r['closed_at']} "
                         f"(thread {r['thread']}; synthesis: {r.get('synthesis', '')[:120]}). "
                         f"Use --force \"reason\" to reopen.")
    day = time.strftime("%Y-%m-%d")
    d, n = tdir / f"{day}_{a.key}", 2
    while d.exists():  # same key reopened on the same day (changed target or --force)
        d, n = tdir / f"{day}-{n}_{a.key}", n + 1
    (d / "posts").mkdir(parents=True)
    header = {"key": a.key, "mission": a.mission, "coordinator": a.coordinator,
              "target": str(a.target) if a.target else None, "target_hash": h,
              "budget_tokens": a.budget_tokens or 0, "opened_at": now(), "closed_at": None,
              "forced": a.force}
    write_header(d, header)
    (d / "SYNTHESIS.md").write_text(f"{EMPTY_SYNTHESIS} - coordinator: {a.coordinator})\n", encoding="utf-8")
    render(d)
    print(d)
    return d


def _text(a):
    if getattr(a, "text", None) is not None:
        return a.text
    if getattr(a, "file", None):
        return Path(a.file).read_text(encoding="utf-8")
    sys.exit("REFUSED: give --text or --file.")


def cmd_post(a):
    d, header = read_thread(a.thread)
    if header.get("closed_at"):
        sys.exit("REFUSED: thread is closed.")
    text = _text(a)
    n = len(text.split())
    if n > MAX_WORDS:
        sys.exit(f"REFUSED: post has {n} words (max {MAX_WORDS}). Detail belongs in the artifact.")
    if not Path(a.artifact).exists():
        sys.exit(f"REFUSED: artifact does not exist: {a.artifact}")
    stamp = time.strftime("%H%M%S")
    pid, k = f"{stamp}_{a.agent}", 2
    while (d / "posts" / f"{pid}.md").exists():  # two posts by one agent in the same second
        pid, k = f"{stamp}_{a.agent}_{k}", k + 1
    lines = [f"id: {pid}", f"agent: {a.agent}", f"to: {a.to}", f"artifact: {a.artifact}",
             f"tokens: {int(a.tokens or 0)}", f"when: {now()}"]
    if a.reply_to:
        lines.append(f"reply_to: {a.reply_to}")
    if a.severity:
        lines.append(f"severity: {a.severity}")
    if a.supports_claim:
        lines.append("supports_claim: true")
    (d / "posts" / f"{pid}.md").write_text("---\n" + "\n".join(lines) + "\n---\n" + text.strip() + "\n",
                                           encoding="utf-8")
    render(d)
    print(pid)
    return pid


def cmd_synthesis(a):
    d, header = read_thread(a.thread)
    if a.coordinator != header["coordinator"]:
        sys.exit(f"REFUSED: only the thread coordinator ({header['coordinator']}) writes the synthesis.")
    text = _text(a)
    n = len([ln for ln in text.splitlines() if ln.strip()])
    if n > MAX_SYNTHESIS_LINES:
        sys.exit(f"REFUSED: synthesis has {n} lines (max {MAX_SYNTHESIS_LINES}).")
    (d / "SYNTHESIS.md").write_text(f"<!-- {now()} by {a.coordinator} -->\n" + text.strip() + "\n",
                                    encoding="utf-8")
    render(d)
    print("synthesis written")


def _synthesis_time(d):
    m = re.search(r"<!-- (\S+ \S+) by", (Path(d) / "SYNTHESIS.md").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def render(d):
    d, header = read_thread(d)
    ps = posts(d)
    synth = (d / "SYNTHESIS.md").read_text(encoding="utf-8")
    st = _synthesis_time(d)
    answered = {p.get("reply_to") for p in ps}
    open_q = [p for p in ps if p.get("to") and p["_id"] not in answered
              and p.get("to") != "coordinator" and p["_body"].rstrip().endswith("?")]
    unabsorbed = [p for p in ps if p.get("when", "") > st or p["_id"] not in synth]
    budget = header.get("budget_tokens") or 0
    out = [f"# THREAD - {header['key']}", f"_generated {now()} by thread.py; do not edit by hand_", "",
           f"**Mission:** {header['mission']}  ",
           f"**Coordinator:** {header['coordinator']} | **Target:** {header.get('target') or '-'} | "
           f"**Budget:** {f'{budget} tokens' if budget else 'none (thermometer only)'} | "
           f"**Opened:** {header['opened_at']} | **Closed:** {header.get('closed_at') or 'no'}", "",
           "## Synthesis", synth.strip(), "", "## Open questions"]
    out += [f"- `{p['_id']}` {p.get('agent')} -> {p.get('to')}: {p['_body'][:160]}" for p in open_q] or ["- none"]
    out += ["", "## Posts not absorbed by the synthesis"]
    out += [f"- `{p['_id']}` {p.get('agent')} ({p.get('severity', 'info')}"
            f"{', supports claim' if p.get('supports_claim') == 'true' else ''})" for p in unabsorbed] or ["- none"]
    out += ["", "## Posts"]
    for p in ps:
        out += [f"### {p['_id']} - {p.get('agent')} -> {p.get('to', '?')}",
                f"artifact: `{p.get('artifact', '?')}` | tokens: {p.get('tokens', '0')}"
                + (f" | reply to `{p['reply_to']}`" if p.get("reply_to") else "")
                + (f" | **{p['severity']}**" if p.get("severity") else ""),
                "", p["_body"], ""]
    (d / "THREAD.md").write_text("\n".join(out) + "\n", encoding="utf-8")


def check(d):
    d, header = read_thread(d)
    synth = (d / "SYNTHESIS.md").read_text(encoding="utf-8")
    problems = []
    for p in posts(d):
        pid = p["_id"]
        if p["_words"] > MAX_WORDS:
            problems.append(f"{pid}: {p['_words']} words")
        if not p.get("artifact") or not Path(p["artifact"]).exists():
            problems.append(f"{pid}: missing artifact ({p.get('artifact')})")
        if (p.get("severity") == "block" or p.get("supports_claim") == "true") and pid not in synth:
            problems.append(f"{pid}: {p.get('severity') or 'supports_claim'} post NOT cited in the synthesis")
    if EMPTY_SYNTHESIS in synth:
        problems.append("synthesis not written")
    return problems


def cmd_check(a):
    problems = check(a.thread)
    print("\n".join(problems) if problems else "thread clean")
    sys.exit(1 if problems else 0)


def total(d):
    d, header = read_thread(d)
    used = sum(int(float(p.get("tokens", 0) or 0)) for p in posts(d))
    budget = header.get("budget_tokens") or 0
    frac = used / budget if budget else 0.0
    return {"thread": str(d), "tokens": used, "budget_tokens": budget,
            "fraction": round(frac, 2), "alert": bool(budget) and frac >= 0.8}


def cmd_total(a):
    print(json.dumps(total(a.thread), ensure_ascii=False))


def cmd_close(a):
    d, header = read_thread(a.thread)
    problems = check(d)
    if problems:
        sys.exit("REFUSED: check reports:\n- " + "\n- ".join(problems))
    header["closed_at"] = now()
    header["tokens"] = total(d)["tokens"]
    write_header(d, header)
    if header.get("target_hash"):
        root = d.parent.parent
        with open(audited_file(root), "a", encoding="utf-8") as f:
            f.write(json.dumps({"target": header["target"], "hash": header["target_hash"], "thread": str(d),
                                "key": header["key"], "closed_at": header["closed_at"],
                                "synthesis": (d / "SYNTHESIS.md").read_text(encoding="utf-8")[:400]},
                               ensure_ascii=False) + "\n")
    render(d)
    print(f"closed: {d}")


def cmd_list(a):
    for f in sorted(threads_dir(root_dir(a.root)).glob("*_*")):
        if (f / "thread.json").exists():
            h = json.loads((f / "thread.json").read_text(encoding="utf-8"))
            if a.open and h.get("closed_at"):
                continue
            print(f"{f.name}  coordinator={h['coordinator']}  closed={h.get('closed_at') or 'no'}  "
                  f"posts={len(list((f / 'posts').glob('*.md')))}")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="audit root (default $AUDIT_ROOT or ./.audit)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("open")
    s.add_argument("--key", required=True)
    s.add_argument("--mission", required=True)
    s.add_argument("--coordinator", required=True)
    s.add_argument("--target")
    s.add_argument("--budget-tokens", type=int, default=0)
    s.add_argument("--force")
    s = sub.add_parser("post")
    s.add_argument("--thread", required=True)
    s.add_argument("--agent", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--artifact", required=True)
    s.add_argument("--text")
    s.add_argument("--file")
    s.add_argument("--tokens", type=int, default=0)
    s.add_argument("--reply-to")
    s.add_argument("--severity", choices=["block", "warn", "info"])
    s.add_argument("--supports-claim", action="store_true")
    s = sub.add_parser("synthesis")
    s.add_argument("--thread", required=True)
    s.add_argument("--coordinator", required=True)
    s.add_argument("--text")
    s.add_argument("--file")
    for name in ("render", "check", "total", "close"):
        s = sub.add_parser(name)
        s.add_argument("--thread", required=True)
    s = sub.add_parser("list")
    s.add_argument("--open", action="store_true")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "render":
        render(a.thread)
        print("THREAD.md rendered")
        return
    {"open": cmd_open, "post": cmd_post, "synthesis": cmd_synthesis, "check": cmd_check,
     "total": cmd_total, "close": cmd_close, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
