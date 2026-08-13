"""
WP1 - Static Group compressor.

Reimplements rtk's (github.com/rtk-ai/rtk) *documented* behavior for test
runner output, since rtk itself is a Rust binary and we need a Python-side
proxy to compress captured logs deterministically for the benchmark.

Documented rtk behavior we mirror (see docs/rtk_reference_notes.md):
  - "cargo test (200+ lines on failure) -> rtk test cargo test (~20 lines)":
    passing tests collapse to a single count; failing tests are reduced to
    one line each: `test_name: <short reason>`.
  - "cargo test with 262 passing tests: 4,823 tokens down to 11 ... the
    agent just needs to know everything passed" -> when ALL tests pass we
    emit only a one-line summary.
  - Full tracebacks, intermediate stack frames, and multi-line value dumps
    (array/JSON/diff bodies) are the parts rtk drops to hit 60-90% reduction;
    we drop the same categories here.

This is a heuristic re-implementation (not rtk's source), so exact byte
counts differ from the real binary, but the *class* of information
destroyed matches its publicly documented behavior.
"""
import re
from dataclasses import dataclass, field


@dataclass
class CompressionResult:
    compressed_text: str
    raw_chars: int
    compressed_chars: int
    dropped_categories: list = field(default_factory=list)

    @property
    def reduction_pct(self):
        if self.raw_chars == 0:
            return 0.0
        return 100.0 * (1 - self.compressed_chars / self.raw_chars)


TEST_LINE = re.compile(
    r"^(?P<name>\S+::\S+)\s+(?P<status>PASSED|FAILED)\s*(\[\s*\d+%\])?$"
)
ASSERTION_HEADER = re.compile(r"^E\s+(?P<msg>\w*Error.*|Not equal to tolerance.*)")


def compress_pytest_output(raw_text: str, ultra_compact: bool = False) -> CompressionResult:
    lines = raw_text.splitlines()
    dropped = []

    statuses = {}
    for line in lines:
        m = TEST_LINE.match(line.strip())
        if m:
            statuses[m.group("name")] = m.group("status")

    n_passed = sum(1 for v in statuses.values() if v == "PASSED")
    n_failed = sum(1 for v in statuses.values() if v == "FAILED")
    failed_names = [k for k, v in statuses.items() if v == "FAILED"]

    if n_failed == 0 and statuses:
        summary = f"[rtk] {n_passed} passed, 0 failed. All tests green — no detail retained."
        dropped.append("all passing-test bodies (collapsed to a bare count)")
        return CompressionResult(summary, len(raw_text), len(summary), dropped)

    # For each failing test, keep ONLY the first assertion header line as the
    # "short reason" (mirrors rtk's `test_overflow: panic at utils.rs:18`
    # one-liner). Everything else in the FAILURES block -- full tracebacks,
    # intermediate call-stack frames, and multi-line array/diff value dumps
    # -- is dropped.
    reasons = {}
    current_test = None
    in_failures_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("=") and "FAILURES" in stripped:
            in_failures_block = True
            continue
        if in_failures_block and stripped.startswith("_") and stripped.endswith("_") and len(stripped) > 4:
            current_test = stripped.strip("_ ")
            continue
        if in_failures_block and current_test and current_test not in reasons:
            m = ASSERTION_HEADER.match(stripped)
            if m:
                reasons[current_test] = m.group("msg").strip()
        if stripped.startswith("=") and "short test summary" in stripped:
            in_failures_block = False

    dropped.append("full tracebacks (call-stack frames from assertion site to fault)")
    dropped.append("multi-line array/value diffs (the actual expected-vs-actual mismatch)")
    dropped.append("per-element mismatch statistics beyond the first summary line")

    out = [f"[rtk] {n_passed} passed, {n_failed} failed."]
    for name in failed_names:
        reason = None
        short = name.split("::")[-1].split("[")[0]
        for k, v in reasons.items():
            if short in k or k in name:
                reason = v
                break
        reason = reason or "assertion failed (detail suppressed by rtk)"
        out.append(f"FAILED {name}: {reason}")

    compressed_text = "\n".join(out)
    if ultra_compact:
        compressed_text = re.sub(r"\s+", " ", compressed_text).strip()

    return CompressionResult(
        compressed_text=compressed_text,
        raw_chars=len(raw_text),
        compressed_chars=len(compressed_text),
        dropped_categories=dropped,
    )


if __name__ == "__main__":
    import sys
    raw = sys.stdin.read()
    r = compress_pytest_output(raw)
    print(r.compressed_text)
    print(f"\n--- reduction: {r.reduction_pct:.1f}% "
          f"({r.raw_chars} -> {r.compressed_chars} chars) ---", file=sys.stderr)
    print("--- info categories dropped ---", file=sys.stderr)
    for c in r.dropped_categories:
        print(f"  - {c}", file=sys.stderr)
