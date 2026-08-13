"""
WP1 - Task 3: turn run_wp1_benchmark.py's results.jsonl into the formal
Error Taxonomy Report deliverable.

Categories (derived from rtk's documented compression behavior, see
docs/rtk_reference_notes.md, cross-checked against what GraphLocator/FlexFL
identify as necessary for causal-chain reasoning):

  T1  Lost value evidence     - array/JSON/diff dumps truncated, so the
                                 agent can no longer tell *which* elements/
                                 fields diverged (blocks GraphLocator-style
                                 symptom-to-cause tracing).
  T2  Lost stack frames       - intermediate call-stack frames dropped, so
                                 the causal path from assertion site to the
                                 true root cause is broken.
  T3  Collapsed sub-failures  - multiple related failing sub-tests/params
                                 collapsed into a single count, hiding the
                                 pattern across cases (one-to-many mismatch,
                                 in GraphLocator's terms).
  T4  Dropped log severity    - non-error log lines (WARNING/DEBUG/INFO)
                                 removed, even when they contained the only
                                 mention of the offending code path.
  T5  Over-summarized reason  - the one-line "reason" rtk keeps is too
                                 generic (e.g. bare "AssertionError:") to
                                 discriminate between causal-chain candidates.
"""
import argparse
import json
from collections import Counter
from pathlib import Path


def classify(result: dict):
    cats = set()
    dropped = set(result.get("dropped_categories", []))
    if any("array" in d or "diff" in d for d in dropped):
        cats.add("T1")
    if any("traceback" in d or "stack" in d for d in dropped):
        cats.add("T2")
    if any("passing" in d or "collapsed" in d for d in dropped):
        cats.add("T3")
    # T4/T5 need the actual static text, checked heuristically:
    static_text = ""
    if "static" in result:
        static_text = json.dumps(result["static"])
    if result.get("compression_tax") and static_text.count("AssertionError:") and \
            len(static_text) < 400:
        cats.add("T5")
    return sorted(cats) or ["unclassified"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results/wp1_results.jsonl")
    ap.add_argument("--out", default="docs/error_taxonomy_findings.md")
    args = ap.parse_args()

    results = [json.loads(l) for l in Path(args.results).open()] if Path(args.results).exists() else []
    tax_cases = [r for r in results if r.get("compression_tax")]

    cat_counter = Counter()
    for r in tax_cases:
        for c in classify(r):
            cat_counter[c] += 1

    lines = ["# WP1 Compression Tax — Empirical Findings\n",
             f"Instances evaluated: {len(results)}",
             f"Compression-tax instances (raw succeeded, rtk-compressed failed): {len(tax_cases)}\n",
             "## Category counts\n"]
    for cat, n in cat_counter.most_common():
        lines.append(f"- **{cat}**: {n} instance(s)")
    lines.append("\n## Per-instance detail\n")
    for r in tax_cases:
        lines.append(f"### {r['instance_id']}")
        lines.append(f"- ground truth: {r['ground_truth_functions']}")
        lines.append(f"- control ranked: {r['control']['ranked_functions']}")
        lines.append(f"- static ranked:  {r['static']['ranked_functions']}")
        lines.append(f"- categories: {classify(r)}")
        lines.append(f"- compression reduction: {r['compression_reduction_pct']:.1f}%\n")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"Wrote {out_path} ({len(tax_cases)} tax cases classified)")


if __name__ == "__main__":
    main()
