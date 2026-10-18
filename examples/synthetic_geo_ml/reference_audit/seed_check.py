"""Reference script of the ml-seed-reproducibility front, applied to the example project.

  1. static check (AST): every random generator constructed in the training code,
     and whether the seed from the config reaches any of them;
  2. dynamic check: run the training twice with the same config, outputs written
     only under --out, and compare metrics and test sets.
The front artifact is ml-seed-reproducibility.json; raw output in raw/seeds_synthetic.json.
"""
import argparse
import ast
import json
import shlex
import subprocess
import sys
from pathlib import Path

GENERATORS = {"default_rng", "RandomState", "Random", "Generator", "seed", "manual_seed", "PCG64"}


def static_check(source):
    tree = ast.parse(source)
    calls, seed_refs = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in GENERATORS:
                calls.append({"line": node.lineno, "call": ast.unparse(node), "has_args": bool(node.args or node.keywords)})
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == "seed":
            seed_refs.append(node.lineno)
    seeded = [c for c in calls if c["has_args"]]
    return {"generator_calls": calls, "seed_config_reads": seed_refs,
            "unseeded_generators": [c for c in calls if not c["has_args"]],
            "seed_reaches_a_generator": any("seed" in c["call"] for c in seeded)}


def rerun(project, out, runs):
    results = []
    for r in range(runs):
        d = Path(out) / "raw" / f"rerun_{r + 1}"
        subprocess.run([sys.executable, str(Path(project) / "train.py"), "--out", str(d)], check=True,
                       capture_output=True, text=True)
        m = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
        s = json.loads((d / "split.json").read_text(encoding="utf-8"))
        results.append({"r2": m["r2"], "rmse": m["rmse"], "seed_reported": m.get("seed"),
                        "test_ids_head": sorted(s["test_ids"])[:5], "test_ids_set": sorted(s["test_ids"])})
    return results


def run(project, out, runs=2, tol=1e-9):
    project, out = Path(project), Path(out)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    src_path = project / "train.py"
    st = static_check(src_path.read_text(encoding="utf-8"))
    reruns = rerun(project, out, runs)
    r2s = [r["r2"] for r in reruns]
    same_split = all(r["test_ids_set"] == reruns[0]["test_ids_set"] for r in reruns)
    spread = max(r2s) - min(r2s)
    command = " ".join(shlex.quote(c) for c in [sys.executable, str(Path(__file__).resolve()),
                                                  "--project", str(project), "--out", str(out)])
    raw = {"static": st, "reruns": [{k: v for k, v in r.items() if k != "test_ids_set"} for r in reruns],
           "same_test_set": same_split, "r2_spread": spread, "command": command}
    raw_path = out / "raw" / "seeds_synthetic.json"
    raw_path.write_text(json.dumps(raw, indent=1), encoding="utf-8")

    findings = []
    if st["unseeded_generators"] and not st["seed_reaches_a_generator"]:
        lines = ", ".join(str(c["line"]) for c in st["unseeded_generators"])
        findings.append({
            "id": "SEED-01", "severity": "block",
            "description": (f"The config declares a seed and metrics.json reports it, but no random generator in "
                            f"train.py receives it: unseeded generator at line(s) {lines}. The reported seed is "
                            f"declared, not effective."),
            "evidence": {"file": str(src_path), "field_or_line": f"line {lines}", "command": command},
            "fix": "Pass the config seed to every generator (np.random.default_rng(cfg['seed'])) and save the "
                   "effective seed with the results.",
            "supports_claim": False})
    if not same_split or spread > tol:
        findings.append({
            "id": "SEED-02", "severity": "block",
            "description": (f"Two runs with the same config produced different test sets (same_test_set="
                            f"{same_split}) and R2 values {', '.join(f'{v:.4f}' for v in r2s)} "
                            f"(spread {spread:.4f}). The quoted R2 is one draw of a random split."),
            "evidence": {"file": str(raw_path), "field_or_line": "reruns, r2_spread", "command": command},
            "fix": "Fix the seed; report the mean and spread over several seeds rather than one draw.",
            "supports_claim": True})
    artifact = {"front": "ml-seed-reproducibility", "target": str(project / "results" / "metrics.json"),
                "verdict": "block" if findings else "pass", "findings": findings,
                "coverage": {"verified": ["AST scan of random generators in train.py",
                                          f"{runs} re-runs with the same config"],
                             "not_verified": ["framework-level determinism flags"],
                             "reason": "the project uses NumPy only; no GPU framework is involved"},
                "file": str(out / "ml-seed-reproducibility.json")}
    (out / "ml-seed-reproducibility.json").write_text(json.dumps(artifact, indent=1), encoding="utf-8")
    return artifact, raw


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=2)
    a = ap.parse_args(argv)
    art, raw = run(a.project, a.out, a.runs)
    print(json.dumps({"verdict": art["verdict"], "findings": [f["id"] for f in art["findings"]],
                      "r2_reruns": [round(r["r2"], 4) for r in raw["reruns"]]}))


if __name__ == "__main__":
    main()
