"""
WP1 - Task 2: run the localization benchmark in two modes.

  Control Group: agent sees raw, unedited terminal output.
  Static Group : agent sees rtk-style compressed terminal output.

For each instance we run BOTH modes against the *same* agent and repo
snapshot, and record whether the top-K ranked functions include a real
ground-truth function (from fetch_instances.py's diff-derived ground truth).

Requires: ANTHROPIC_API_KEY in the environment, and a repo checked out at
each instance's base_commit under --repos-dir/<repo_name>. Use
`git clone <repo> && git checkout <base_commit>` per instance, or write a
small helper that does this from data/instances.jsonl (left out here since
it is a straightforward loop -- see README).
"""
import argparse
import json
from pathlib import Path

from agent_localizer import LLM, RDFS, localize
from rtk_compressor import compress_pytest_output


def top_k_hit(ranked, ground_truth_functions, k=5):
    ranked_short = {r.split("::")[-1] for r in ranked[:k]}
    gt_short = {g.split("::")[-1] for g in ground_truth_functions}
    return bool(ranked_short & gt_short)


def run_one(llm, repos_dir: Path, inst: dict, raw_log: str):
    repo_name = inst["repo"].split("/")[-1]
    repo_path = repos_dir / repo_name
    rdfs = RDFS()
    rdfs.build(repo_path)

    compressed = compress_pytest_output(raw_log)

    control = localize(llm, rdfs, inst["problem_statement"], raw_log)
    static = localize(llm, rdfs, inst["problem_statement"], compressed.compressed_text)

    control_hit = top_k_hit(control["ranked_functions"], inst["ground_truth_functions"])
    static_hit = top_k_hit(static["ranked_functions"], inst["ground_truth_functions"])

    return {
        "instance_id": inst["instance_id"],
        "ground_truth_functions": inst["ground_truth_functions"],
        "control": {**control, "hit": control_hit},
        "static": {**static, "hit": static_hit},
        "compression_reduction_pct": compressed.reduction_pct,
        "dropped_categories": compressed.dropped_categories,
        "compression_tax": control_hit and not static_hit,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="data/instances.jsonl")
    ap.add_argument("--raw-logs", default="data/raw_logs.jsonl")
    ap.add_argument("--repos-dir", default="repos")
    ap.add_argument("--out", default="results/wp1_results.jsonl")
    args = ap.parse_args()

    insts = {json.loads(l)["instance_id"]: json.loads(l) for l in Path(args.instances).open()}
    logs = {json.loads(l)["instance_id"]: json.loads(l)["raw_stdout"] for l in Path(args.raw_logs).open()}

    llm = LLM()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_control_hit = n_static_hit = n_tax = 0
    with out_path.open("w") as f:
        for iid, inst in insts.items():
            raw_log = logs.get(iid)
            if not raw_log or raw_log.startswith("[OFFLINE PLACEHOLDER"):
                print(f"skip {iid}: no real raw log captured (run docker_harness.py first)")
                continue
            result = run_one(llm, Path(args.repos_dir), inst, raw_log)
            f.write(json.dumps(result) + "\n")
            n_control_hit += result["control"]["hit"]
            n_static_hit += result["static"]["hit"]
            n_tax += result["compression_tax"]
            print(f"{iid}: control_hit={result['control']['hit']} "
                  f"static_hit={result['static']['hit']} "
                  f"tax={result['compression_tax']}")

    print(f"\nTOTAL: control_hit_rate={n_control_hit}/{len(insts)}  "
          f"static_hit_rate={n_static_hit}/{len(insts)}  compression_tax_count={n_tax}")


if __name__ == "__main__":
    main()
