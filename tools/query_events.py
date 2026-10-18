#!/usr/bin/env python3
"""Query the event log by script, never by eye, and save every query next to its result.

Rule: no number about the audit process itself (how many fronts failed, which
agents finished without an artifact, token use per agent) comes from reading the
JSONL by eye. It comes from a saved query; the number quoted in a report points to
the file this script writes under <root>/events/_queries/.

Commands:
  query_events.py by-agent      [--since YYYY-MM-DD] [--until YYYY-MM-DD]
  query_events.py by-day
  query_events.py failures
  query_events.py no-artifact   audit agents that finished without writing anything
  query_events.py artifacts     [--agent NAME]
  query_events.py sql "SELECT ... FROM ev ..."      (needs duckdb)

DuckDB is optional: when installed, every named query runs as SQL over the
JSONL files (table `ev`); without it, the same named queries run in pure Python.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_log import AUDIT_AGENT, events_dir  # noqa: E402

AUDIT_RE_SQL = AUDIT_AGENT.pattern

SQL = {
    "by-agent": """SELECT agent_type AS agent, count(*) AS events,
        sum(tokens.input + tokens.cache_read + tokens.cache_write) AS tokens_in,
        sum(tokens.output) AS tokens_out, round(avg(TRY_CAST(duration_s AS DOUBLE))) AS mean_duration_s
        FROM ev {where} GROUP BY 1 ORDER BY events DESC, agent""",
    "by-day": """SELECT substr(ts, 1, 10) AS day, count(*) AS events, sum(tokens.output) AS tokens_out
        FROM ev {where} GROUP BY 1 ORDER BY 1""",
    "failures": """SELECT ts, agent_type AS agent, status, error FROM ev {where_and} status <> 'ok'
        ORDER BY ts DESC""",
    "no-artifact": f"""SELECT ts, agent_type AS agent, session_id FROM ev {{where_and}}
        len(output.artifacts) = 0 AND regexp_matches(agent_type, '{AUDIT_RE_SQL}') ORDER BY ts DESC""",
    "artifacts": """SELECT ts, agent_type AS agent, a.path AS path, a.sha256 AS sha256
        FROM ev, unnest(output.artifacts) AS t(a) {where_and} true {agent} ORDER BY ts DESC""",
}


def load_events(root=None):
    evs = []
    d = events_dir(root)
    for f in sorted(d.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                evs.append(json.loads(line))
    return evs


def _in_window(ev, since, until):
    day = ev.get("ts", "")[:10]
    return (not since or day >= since) and (not until or day <= until)


def run_python(name, root=None, since=None, until=None, agent=None):
    evs = [e for e in load_events(root) if _in_window(e, since, until)]
    if name == "by-agent":
        acc = defaultdict(lambda: {"events": 0, "tokens_in": 0, "tokens_out": 0, "_dur": []})
        for e in evs:
            r, t = acc[e["agent_type"]], e.get("tokens") or {}
            r["events"] += 1
            r["tokens_in"] += t.get("input", 0) + t.get("cache_read", 0) + t.get("cache_write", 0)
            r["tokens_out"] += t.get("output", 0)
            if e.get("duration_s") is not None:
                r["_dur"].append(e["duration_s"])
        rows = [{"agent": k, "events": v["events"], "tokens_in": v["tokens_in"], "tokens_out": v["tokens_out"],
                 "mean_duration_s": round(sum(v["_dur"]) / len(v["_dur"])) if v["_dur"] else None}
                for k, v in acc.items()]
        return sorted(rows, key=lambda r: (-r["events"], r["agent"]))
    if name == "by-day":
        acc = defaultdict(lambda: {"events": 0, "tokens_out": 0})
        for e in evs:
            acc[e["ts"][:10]]["events"] += 1
            acc[e["ts"][:10]]["tokens_out"] += (e.get("tokens") or {}).get("output", 0)
        return [{"day": k, **v} for k, v in sorted(acc.items())]
    if name == "failures":
        return sorted(({"ts": e["ts"], "agent": e["agent_type"], "status": e["status"], "error": e.get("error")}
                       for e in evs if e.get("status") != "ok"), key=lambda r: r["ts"], reverse=True)
    if name == "no-artifact":
        return sorted(({"ts": e["ts"], "agent": e["agent_type"], "session_id": e.get("session_id")}
                       for e in evs if not e["output"]["artifacts"] and AUDIT_AGENT.match(e["agent_type"] or "")),
                      key=lambda r: r["ts"], reverse=True)
    if name == "artifacts":
        rows = [{"ts": e["ts"], "agent": e["agent_type"], "path": a["path"], "sha256": a["sha256"]}
                for e in evs for a in e["output"]["artifacts"] if not agent or e["agent_type"] == agent]
        return sorted(rows, key=lambda r: r["ts"], reverse=True)
    raise SystemExit(f"unknown query: {name}")


def run_duckdb(sql, root=None):
    import duckdb  # optional dependency
    files = sorted(events_dir(root).glob("*.jsonl"))
    if not files:
        return []
    con = duckdb.connect()
    lst = ", ".join("'" + f.as_posix().replace("'", "''") + "'" for f in files)
    con.execute(f"CREATE VIEW ev AS SELECT * FROM read_json([{lst}], format='newline_delimited', "
                f"union_by_name=true, maximum_object_size=16777216)")
    cur = con.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_sql(name, since=None, until=None, agent=None):
    conds = []
    if since:
        conds.append(f"substr(ts, 1, 10) >= '{since}'")
    if until:
        conds.append(f"substr(ts, 1, 10) <= '{until}'")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    where_and = ("WHERE " + " AND ".join(conds) + " AND") if conds else "WHERE"
    agent_c = f"AND agent_type = '{agent.replace(chr(39), '')}'" if agent else ""
    return SQL[name].format(where=where, where_and=where_and, agent=agent_c)


def have_duckdb():
    try:
        import duckdb  # noqa: F401
        return True
    except ImportError:
        return False


def save(name, sql, result, engine, root=None):
    d = events_dir(root) / "_queries"
    d.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "query"
    f = d / f"{time.strftime('%Y-%m-%d_%H%M%S')}_{slug}.json"
    f.write_text(json.dumps({"query": name, "sql": sql, "engine": engine, "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "result": result}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    ap.add_argument("--engine", choices=["auto", "duckdb", "python"], default="auto")
    ap.add_argument("name", choices=list(SQL) + ["sql"])
    ap.add_argument("sql", nargs="?")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--agent")
    a = ap.parse_args(argv)
    engine = a.engine if a.engine != "auto" else ("duckdb" if have_duckdb() else "python")
    if a.name == "sql":
        if not a.sql:
            raise SystemExit("sql needs a query string")
        if engine != "duckdb":
            raise SystemExit("free SQL needs duckdb (pip install duckdb)")
        sql, result = a.sql, run_duckdb(a.sql, a.root)
    else:
        sql = build_sql(a.name, a.since, a.until, a.agent)
        result = run_duckdb(sql, a.root) if engine == "duckdb" else run_python(a.name, a.root, a.since, a.until, a.agent)
    f = save(a.name, sql, result, engine, a.root)
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    print(f"# saved: {f}", file=sys.stderr)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
