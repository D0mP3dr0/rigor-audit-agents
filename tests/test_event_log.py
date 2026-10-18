import json
import tempfile
import unittest
from pathlib import Path

from _util import run_main

import event_log
import query_events


def transcript(path, artifact=None):
    lines = [{"type": "user", "message": {"content": "audit target; thread threads/2026-01-01_k1"}},
             {"type": "assistant", "message": {"model": "test-model", "usage": {"input_tokens": 10, "output_tokens": 5},
                                               "content": ([{"type": "tool_use", "name": "Write",
                                                             "input": {"file_path": str(artifact)}}] if artifact else [])
                                               + [{"type": "text", "text": "verdict: block"}]}}]
    path.write_text("\n".join(json.dumps(x) for x in lines))


class EventLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = str(Path(self.tmp.name) / ".audit")

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_and_hash_only(self):
        art = Path(self.tmp.name) / "a.json"
        art.write_text("{}")
        ev = event_log.record_event(mechanism="script", agent_type="data-provenance", task_text="secret task",
                                    output_text="out", artifacts=[art, art], root=self.root)
        self.assertEqual(ev["schema_version"], 1)
        self.assertEqual(len(ev["output"]["artifacts"]), 1)
        self.assertIsNotNone(ev["output"]["artifacts"][0]["sha256"])
        ev2 = event_log.record_event(mechanism="script", agent_type="x", task_text="secret task", hash_only=True,
                                     root=self.root)
        self.assertIsNone(ev2["task"]["summary"])
        self.assertEqual(ev2["task"]["sha256"], ev["task"]["sha256"])
        files = list((Path(self.root) / "events").glob("*.jsonl"))
        self.assertEqual(sum(len(f.read_text().splitlines()) for f in files), 2)

    def test_hook_parses_transcript_and_warns_without_artifact(self):
        art = Path(self.tmp.name) / "front.json"
        art.write_text("{}")
        t1 = Path(self.tmp.name) / "t1.jsonl"
        transcript(t1, art)
        warn = event_log.hook(json.dumps({"hook_event_name": "SubagentStop", "agent_type": "data-contract",
                                          "agent_transcript_path": str(t1), "session_id": "s"}), root=self.root)
        self.assertIsNone(warn)
        t2 = Path(self.tmp.name) / "t2.jsonl"
        transcript(t2, None)
        warn = event_log.hook(json.dumps({"hook_event_name": "SubagentStop", "agent_type": "ml-ablation",
                                          "agent_transcript_path": str(t2)}), root=self.root)
        self.assertIn("without writing an artifact", warn["systemMessage"])
        evs = query_events.load_events(self.root)
        self.assertEqual(evs[0]["thread"], "2026-01-01_k1")
        self.assertEqual(evs[0]["tokens"]["output"], 5)
        self.assertEqual(evs[0]["model"], "test-model")

    def _fill(self):
        event_log.record_event(mechanism="script", agent_type="ml-ablation", root=self.root)
        event_log.record_event(mechanism="script", agent_type="ml-ablation", status="error", error="boom",
                               root=self.root)
        event_log.record_event(mechanism="script", agent_type="other-tool", root=self.root)

    def test_queries_python_engine_and_saved_file(self):
        self._fill()
        code, out = run_main(query_events.main, ["--root", self.root, "--engine", "python", "by-agent"])
        rows = json.loads(out)
        self.assertEqual(rows[0], {"agent": "ml-ablation", "events": 2, "tokens_in": 0, "tokens_out": 0,
                                   "mean_duration_s": None})
        self.assertEqual(len(query_events.run_python("failures", self.root)), 1)
        self.assertEqual([r["agent"] for r in query_events.run_python("no-artifact", self.root)],
                         ["ml-ablation", "ml-ablation"])
        self.assertTrue(list((Path(self.root) / "events" / "_queries").glob("*_by-agent.json")))

    @unittest.skipUnless(query_events.have_duckdb(), "duckdb not installed")
    def test_duckdb_engine_matches_python(self):
        self._fill()
        for name in ("failures", "no-artifact"):
            sql = query_events.build_sql(name)
            self.assertEqual(len(query_events.run_duckdb(sql, self.root)),
                             len(query_events.run_python(name, self.root)), name)
        by = {r["agent"]: r["events"] for r in query_events.run_duckdb(query_events.build_sql("by-agent"), self.root)}
        self.assertEqual(by, {"ml-ablation": 2, "other-tool": 1})


if __name__ == "__main__":
    unittest.main()
