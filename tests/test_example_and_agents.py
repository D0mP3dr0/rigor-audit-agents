import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

from _util import REPO

AGENTS = REPO / "agents"
SKILLS = REPO / "skills"


def frontmatter(path):
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    assert m, f"no frontmatter in {path}"
    return dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)


class AgentsTest(unittest.TestCase):
    def test_frontmatter_complete(self):
        files = sorted(AGENTS.glob("*.md"))
        self.assertGreater(len(files), 20)
        for f in files:
            fm = {k.strip(): v.strip() for k, v in frontmatter(f).items()}
            for key in ("name", "description", "tools", "model", "effort", "maxTurns"):
                self.assertIn(key, fm, f"{f.name}: {key}")
            self.assertEqual(fm["name"], f.stem)
            self.assertNotIn("Agent", [t.strip() for t in fm["tools"].split(",")], f.name)

    def test_skills_reference_existing_agents(self):
        names = {f.stem for f in AGENTS.glob("*.md")}
        skills = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertEqual(len(skills), 6)
        for s in skills:
            self.assertEqual(frontmatter(s)["name"].strip(), s.parent.name)
            for agent in re.findall(r"\| `([a-z0-9-]+)` \|", s.read_text(encoding="utf-8")):
                self.assertIn(agent, names, f"{s}: {agent}")


class ExampleTest(unittest.TestCase):
    def test_walkthrough_finds_both_planted_defects(self):
        spec = importlib.util.spec_from_file_location(
            "run_walkthrough", REPO / "examples" / "synthetic_geo_ml" / "run_walkthrough.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                s = mod.main(["--work", str(Path(d) / "run"), "--n", "600"])
        self.assertEqual(s["tally"].get("LEAK-01"), "confirmed")
        self.assertEqual(s["tally"].get("SEED-01"), "confirmed")
        self.assertEqual(s["tally"].get("SEED-02"), "confirmed")
        self.assertGreater(s["leakage"]["optimism_r2"], 0.05)
        self.assertEqual(s["thread_check"], "thread clean")
        self.assertTrue(s["reopen_refused"])


if __name__ == "__main__":
    unittest.main()
