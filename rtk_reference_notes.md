# rtk — sourced behavior notes

`rtk` (github.com/rtk-ai/rtk, "Rust Token Killer") is a single-binary Rust
CLI proxy. It hooks into coding-agent Bash tool calls and rewrites commands
(e.g. `cargo test` → `rtk test cargo test`) so the agent reads compressed
output instead of the raw stream. Key documented facts used to design our
Static Group compressor:

- Claims 60–90% token reduction on common dev commands (git, cargo, npm,
  test runners, `cat`, `ls`, ...). Source: rtk-ai/rtk README.
- Worked example for test output specifically:
  `cargo test` (200+ lines on failure) → `rtk test cargo test` (~20 lines):
  ```
  running 15 tests
  FAILED: 2/15 tests
  test utils::test_parse ... ok
  test_edge_case: assertion failed
  test utils::test_format ... ok
  test_overflow: panic at utils.rs:18
  ```
  i.e. passing tests are reduced to a bare count/`ok`, and failing tests are
  reduced to a *one-line* reason with no surrounding value dump or stack
  trace. Source: MaTriXy/rtk-token-compressor README, rtk-ai/rtk README.
- Real-usage numbers reported by a user: `cargo test` with 262 passing
  tests went from 4,823 tokens to **11** tokens (99% reduction) — "the
  agent just needs to know everything passed." Source: rushis.com writeup.
- `cat src/main.rs` on a 1,295-line file: 10,176 → 504 tokens by extracting
  "the structural skeleton — imports, type definitions, function
  signatures" and collapsing everything else — the same "keep skeleton,
  drop detail" strategy applied to source reads, not just test output.
- A user-reported GitHub issue: rtk compressed Playwright E2E test output
  so aggressively the agent could not debug the failure, and the
  documented workaround is `rtk proxy <command>` to bypass compression
  entirely for that one call. Source: madplay.github.io writeup, citing a
  rtk-ai/rtk GitHub issue. **This is exactly WP1's "Compression Tax"
  phenomenon, independently reported by a real user before we ran a
  single experiment.**
- rtk's own CONTRIBUTING.md states the design principle: "RTK should never
  prevent a command from executing... every filter needs a fallback path,"
  and explicitly respects user/agent intent to see detailed output when a
  verbose flag is passed (e.g. `cargo test -- --nocapture`). This confirms
  compression is applied *by default* and only bypassed on request — i.e.
  an agent has to already suspect it's missing something to escape the
  compression, which is the crux of WP2's "Zoom-In" proposal.

## Why our `rtk_compressor.py` re-implementation, not the real binary

`rtk` is a Rust binary with no Python bindings, and its source is not
vendored into this environment. We re-implement the *documented output
shape* (bare pass/fail count + one-line failure reason, tracebacks and
value dumps dropped) in Python so the Control/Static comparison is
reproducible and inspectable in the benchmark harness. Exact byte-level
compression ratios will differ slightly from the real binary; the
*category* of information destroyed (full tracebacks, array/JSON value
diffs, per-sub-test detail, non-error log lines) is what we match, since
that is what determines whether an FL agent can still localize the bug.

Before scaling WP1 past the pilot, swap in the real `rtk` binary as the
proxy (`rtk proxy <test command>` vs `<test command>` directly) to remove
this approximation.
