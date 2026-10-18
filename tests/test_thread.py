import json
import tempfile
import unittest
from pathlib import Path

from _util import run_main

import thread


class ThreadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".audit"
        self.target = Path(self.tmp.name) / "target"
        self.target.mkdir()
        (self.target / "data.csv").write_text("a,b\n1,2\n")
        self.artifact = Path(self.tmp.name) / "front.json"
        self.artifact.write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def t(self, *argv):
        return run_main(thread.main, ["--root", str(self.root), *argv])

    def open(self, *extra):
        code, out = self.t("open", "--key", "k1", "--mission", "m", "--coordinator", "coord-data",
                           "--target", str(self.target), *extra)
        return code, (out.splitlines()[-1] if code == 0 and out else out)

    def post(self, d, *extra, text="short post"):
        return self.t("post", "--thread", d, "--agent", "data-provenance", "--to", "coord-data",
                      "--artifact", str(self.artifact), "--text", text, *extra)

    def test_open_refuses_second_open_thread(self):
        self.assertEqual(self.open()[0], 0)
        code, out = self.open()
        self.assertEqual(code, 1)
        self.assertIn("already open", out)

    def test_post_limits(self):
        _, d = self.open()
        self.assertEqual(self.post(d, text="word " * 201)[0], 1)
        code, out = self.t("post", "--thread", d, "--agent", "x", "--to", "y", "--artifact", "/no/such/file",
                           "--text", "hi")
        self.assertEqual(code, 1)
        self.assertIn("artifact does not exist", out)
        code, pid = self.post(d)
        self.assertEqual(code, 0)
        self.assertTrue((Path(d) / "posts" / f"{pid}.md").exists())
        code, pid2 = self.post(d)
        self.assertNotEqual(pid, pid2)  # same agent, same second: no overwrite

    def test_synthesis_only_by_coordinator_and_line_limit(self):
        _, d = self.open()
        self.assertEqual(self.t("synthesis", "--thread", d, "--coordinator", "someone", "--text", "x")[0], 1)
        self.assertEqual(self.t("synthesis", "--thread", d, "--coordinator", "coord-data",
                                "--text", "\n".join(["l"] * 16))[0], 1)
        self.assertEqual(self.t("synthesis", "--thread", d, "--coordinator", "coord-data", "--text", "ok")[0], 0)

    def test_check_requires_blocking_posts_cited_and_close_flow(self):
        _, d = self.open()
        _, pid = self.post(d, "--severity", "block")
        self.assertEqual(self.t("check", "--thread", d)[0], 1)  # no synthesis yet
        self.t("synthesis", "--thread", d, "--coordinator", "coord-data", "--text", "nothing cited")
        code, out = self.t("check", "--thread", d)
        self.assertEqual(code, 1)
        self.assertIn("NOT cited", out)
        self.assertEqual(self.t("close", "--thread", d)[0], 1)
        self.t("synthesis", "--thread", d, "--coordinator", "coord-data", "--text", f"`{pid}` accepted")
        self.assertEqual(self.t("check", "--thread", d), (0, "thread clean"))
        self.assertEqual(self.t("close", "--thread", d)[0], 0)
        self.assertIsNotNone(json.loads((Path(d) / "thread.json").read_text())["closed_at"])
        self.assertEqual(self.post(d)[0], 1)  # closed thread refuses posts

    def test_audited_target_is_not_reaudited_unless_changed_or_forced(self):
        _, d = self.open()
        self.t("synthesis", "--thread", d, "--coordinator", "coord-data", "--text", "done")
        self.t("close", "--thread", d)
        code, out = self.open()
        self.assertEqual(code, 1)
        self.assertIn("already audited", out)
        (self.target / "data.csv").write_text("a,b\n1,3\n")  # content change -> new hash
        self.assertEqual(self.open()[0], 0)

    def test_force_reopens_unchanged_target(self):
        _, d = self.open()
        self.t("synthesis", "--thread", d, "--coordinator", "coord-data", "--text", "done")
        self.t("close", "--thread", d)
        code, d2 = self.open("--force", "new reviewer question")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((Path(d2) / "thread.json").read_text())["forced"], "new reviewer question")

    def test_hash_is_content_based(self):
        h1 = thread.hash_target(self.target)
        (self.target / "data.csv").write_text("a,b\n1,9\n")
        self.assertNotEqual(h1, thread.hash_target(self.target))

    def test_total_and_open_questions(self):
        _, d = self.open("--budget-tokens", "100")
        self.post(d, "--tokens", "85", text="which split file is canonical?")
        tot = thread.total(d)
        self.assertEqual(tot["tokens"], 85)
        self.assertTrue(tot["alert"])
        self.assertIn("which split file", (Path(d) / "THREAD.md").read_text().split("## Posts not absorbed")[0])


if __name__ == "__main__":
    unittest.main()
