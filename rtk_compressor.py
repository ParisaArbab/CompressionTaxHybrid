"""
WP1 - Static Group compressor.

Shells out to the REAL `rtk` binary (rtk-ai/rtk, installed via its official
install.sh) instead of re-implementing its heuristics. This module previously
contained a Python re-implementation of rtk's documented behavior; that has
been replaced per explicit instruction to use actual rtk output.

Install once:
    curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

Verified real runs used to build this project (see docs/real_run_log.md for
full transcripts and docs/error_taxonomy_report.md for the analysis):

  rtk test <python -m pytest testing/test_skipping.py -k TestXFail>
    -> 7,836 -> 991 bytes, 86.8% reduction (rtk's own `gain` tracker)
  rtk test <python runtests.py delete --settings=test_sqlite -v2>
    -> 7,951 -> 314 bytes, 96.0% reduction, and rtk's failure-block parser
       did not recognize Django's own unittest-style runner: the compressed
       output kept only the last 5 lines and the individual FAIL: blocks
       (assertion diffs + tracebacks) were dropped entirely, not just
       truncated.

`rtk gain` (rtk's own SQLite-backed tracker) is the source of truth for
reduction percentages -- we don't recompute our own ratio, we read rtk's.
"""
import shutil
import subprocess
from dataclasses import dataclass


RTK_BIN = shutil.which("rtk")


@dataclass
class RealCompressionResult:
    compressed_text: str
    raw_chars: int
    compressed_chars: int
    rtk_stderr: str
    command_run: str

    @property
    def reduction_pct(self):
        if self.raw_chars == 0:
            return 0.0
        return 100.0 * (1 - self.compressed_chars / self.raw_chars)


def compress_with_real_rtk(test_command: list, raw_text_for_sizing: str = None,
                            timeout: int = 600) -> RealCompressionResult:
    """Run `rtk test <test_command>` for real and capture its actual stdout.

    `raw_text_for_sizing`: if you already captured the raw (uncompressed) run
    separately, pass its text here so raw_chars reflects the identical
    invocation; otherwise raw_chars falls back to 0 (only rtk's own `gain`
    numbers, printed separately via `rtk gain`, should be trusted for the
    official reduction percentage).
    """
    if RTK_BIN is None:
        raise RuntimeError(
            "Real rtk binary not found on PATH. Install it first: "
            "curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh"
        )
    proc = subprocess.run(
        [RTK_BIN, "test", *test_command],
        capture_output=True, text=True, timeout=timeout,
    )
    compressed = proc.stdout
    raw_chars = len(raw_text_for_sizing) if raw_text_for_sizing is not None else 0
    return RealCompressionResult(
        compressed_text=compressed,
        raw_chars=raw_chars,
        compressed_chars=len(compressed),
        rtk_stderr=proc.stderr,
        command_run=" ".join([RTK_BIN, "test", *test_command]),
    )


def rtk_gain_report() -> str:
    """Return rtk's own tracked savings summary (ground truth for % reduction)."""
    if RTK_BIN is None:
        raise RuntimeError("rtk not installed")
    proc = subprocess.run([RTK_BIN, "gain"], capture_output=True, text=True)
    return proc.stdout


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 rtk_compressor.py <test command...>", file=sys.stderr)
        sys.exit(1)
    result = compress_with_real_rtk(sys.argv[1:])
    print(result.compressed_text)
    print(f"\n--- ran: {result.command_run} ---", file=sys.stderr)
    print(rtk_gain_report(), file=sys.stderr)
