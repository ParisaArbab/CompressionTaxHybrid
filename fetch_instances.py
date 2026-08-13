"""
WP1 - Task 1: pull a real subset of princeton-nlp/SWE-bench_Lite and derive
function-level ground truth locations from each instance's gold patch.

Usage:
    python fetch_instances.py --n 20 --seed 7 --out data/instances.jsonl
"""
import argparse
import json
import random
import re
from pathlib import Path

from datasets import load_dataset


def extract_ground_truth_functions(patch_text: str):
    """Very lightweight diff parser: returns (file, enclosing def/class) pairs
    touched by the gold patch. This mirrors the 'function-level' ground truth
    extraction used by GraphLocator/FlexFL (diff -> enclosing structural unit).
    """
    locations = []
    current_file = None
    current_func = None
    def_re = re.compile(r"^\+?\s*(def|class)\s+(\w+)")
    hunk_re = re.compile(r"^@@ .* @@\s*(?:def|class)?\s*(\w+)?")
    for line in patch_text.splitlines():
        if line.startswith("diff --git"):
            continue
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            continue
        if line.startswith("@@"):
            m = hunk_re.match(line)
            current_func = m.group(1) if m and m.group(1) else current_func
            continue
        if current_file and line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            m = def_re.match(line[1:])
            if m:
                current_func = m.group(2)
            if current_file and current_func:
                loc = f"{current_file}::{current_func}"
                if loc not in locations:
                    locations.append(loc)
    return locations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="subset size")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/instances.jsonl")
    ap.add_argument("--single-file-only", action="store_true",
                     help="restrict to single-file gold patches (cleaner ground truth)")
    args = ap.parse_args()

    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    rows = list(ds)
    random.Random(args.seed).shuffle(rows)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    kept = 0
    with out_path.open("w") as f:
        for row in rows:
            gt = extract_ground_truth_functions(row["patch"])
            n_files = len({loc.split("::")[0] for loc in gt})
            if args.single_file_only and n_files != 1:
                continue
            if not gt:
                continue
            rec = {
                "instance_id": row["instance_id"],
                "repo": row["repo"],
                "base_commit": row["base_commit"],
                "problem_statement": row["problem_statement"],
                "hints_text": row.get("hints_text", ""),
                "FAIL_TO_PASS": json.loads(row["FAIL_TO_PASS"]) if isinstance(row["FAIL_TO_PASS"], str) else row["FAIL_TO_PASS"],
                "PASS_TO_PASS": json.loads(row["PASS_TO_PASS"]) if isinstance(row["PASS_TO_PASS"], str) else row["PASS_TO_PASS"],
                "test_patch": row["test_patch"],
                "gold_patch": row["patch"],
                "ground_truth_functions": gt,
            }
            f.write(json.dumps(rec) + "\n")
            kept += 1
            if kept >= args.n:
                break

    print(f"Wrote {kept} instances to {out_path}")


if __name__ == "__main__":
    main()
