import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from _util import run_main

import experiment_registry as er


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = str(Path(self.tmp.name) / ".audit")

    def tearDown(self):
        self.tmp.cleanup()

    def r(self, *argv):
        return run_main(er.main, ["--root", self.root, *argv])

    def test_open_close_and_render(self):
        self.assertEqual(self.r("open", "--id", "T1", "--title", "gate", "--question", "does it catch X?")[0], 0)
        self.assertEqual(self.r("open", "--id", "T1", "--title", "dup", "--question", "q")[0], 1)
        self.assertEqual(self.r("close", "--id", "T1", "--verdict", "adopted", "--reason", "caught 3 of 3")[0], 0)
        data = er.load(self.root)
        self.assertEqual(data["tests"][0]["verdict"], "adopted")
        md = (Path(self.root) / "experiments" / "REGISTRY.md").read_text()
        self.assertIn("Closed (1)", md)

    def test_renewed_stays_open_and_restarts_clock(self):
        self.r("open", "--id", "T2", "--title", "t", "--question", "q")
        self.r("close", "--id", "T2", "--verdict", "renewed", "--reason", "needs more data")
        t = er.load(self.root)["tests"][0]
        self.assertEqual(t["state"], "open")
        self.assertEqual(len(t["renewals"]), 1)

    def test_stale(self):
        data = er.open_test(er.load(self.root), "T3", "old", "q")
        data["tests"][0]["entered"] = "2020-01-01"
        er.save(data, self.root)
        s = er.stale(er.load(self.root), 60, on=dt.date.today().isoformat())
        self.assertEqual([x["id"] for x in s], ["T3"])
        self.assertEqual(self.r("stale")[0], 1)

    def test_unknown_id(self):
        self.assertEqual(self.r("close", "--id", "nope", "--verdict", "withdrawn", "--reason", "x")[0], 1)

    def test_list_json(self):
        self.r("open", "--id", "T4", "--title", "t", "--question", "q", "--components", "a, b")
        code, out = self.r("list", "--json")
        self.assertEqual(json.loads(out)[0]["components"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
