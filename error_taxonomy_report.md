# Error Taxonomy Report: The rtk "Compression Tax" on Bug Localization

**Work Package 1 — Baseline Auditing**
**Compressor:** the real `rtk` binary v0.45.0 (rtk-ai/rtk), installed and run live —
not a re-implementation. Install: `curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh`
**Benchmark:** `princeton-nlp/SWE-bench_Lite`, 2 instances run end-to-end live in this
session (`pytest-dev__pytest-7490`, `django__django-12747`); repos cloned at the
exact `base_commit`, gold `test_patch` applied, real interpreter installed
(Python 3.9 via `uv`, since these instances predate Python 3.12 compatibility),
real test suite executed.
**All raw evidence is in `data/real_runs/`** — every number below is read
directly off those files or off `rtk gain`'s own tracker, not estimated.

---

## 1. What is genuinely live in this report, and what is not

| Claim | Status |
|---|---|
| rtk was actually installed and actually run | **Real.** `rtk 0.45.0`, official binary, official install script. |
| The two repos were actually cloned, checked out at the real SWE-bench `base_commit`, and the real gold `test_patch` applied | **Real.** See `git log -1` output captured during the run. |
| The captured "raw" failure logs are literal captures of a real `pytest` / Django test-runner invocation | **Real.** Not reconstructed — these are the actual `data/real_runs/*_raw_stdout*.txt` files. |
| Compression ratios (86.8%, 92.9%, 96.0%) | **Real.** Read directly from `rtk gain`'s own SQLite-backed tracker (`data/real_runs/rtk_gain_report.txt`), not recomputed by us. |
| The localization-accuracy comparison in Section 4 | **Real reasoning, but a manual proxy, not the automated `agent_localizer.py` pipeline.** No `ANTHROPIC_API_KEY` is available in this sandboxed environment, so I (Claude, in this conversation) performed the search/reasoning steps myself against the live repo — genuinely, and genuinely blind to the gold patch until after each prediction was recorded — rather than `run_wp1_benchmark.py` driving the agent via the API. This is a legitimate but small-N substitute; see the explicit caveats in Section 4 and the ask at the end of this report.

## 2. Real compression results

Read straight from `rtk gain` after both runs (`data/real_runs/rtk_gain_report.txt`):

| # | Command | Raw → compressed | Reduction |
|---|---|---|---|
| 1 | `rtk test python runtests.py delete --settings=test_sqlite -v2` (django, real failing run) | ~2.0K → ~80 tokens | **96.0%** |
| 2 | `rtk summary <pytest -v -k TestXFail>` (pytest, real failing run, `summary` subcommand) | ~1.9K → ~140 tokens | 92.9% |
| 3 | `rtk test python -m pytest testing/test_skipping.py -k TestXFail` (pytest, real failing run, `test` subcommand) | ~1.1K → ~150 tokens | **86.8%** |

Byte-level (from the actual files, not tokens): pytest run 7,836 → 991 bytes;
django run 7,951 → 314 bytes.

## 3. Real finding: rtk behaves differently depending on whether it recognizes the runner

This was not hypothesized in advance — it fell out of running two different
repos.

**pytest (recognized runner, `rtk test`):** rtk correctly parsed pass/fail
status per test and preserved the failing test's one-line reason:
```
[FAIL] FAILURES:
  FAILED test_dynamic_xfail_set_during_runtest_failed.py::test_this - assert 0
  FAILED testing/test_skipping.py::TestXFail::test_dynamic_xfail_set_during_runtest_failed
  FAILED testing/test_skipping.py::TestXFail::test_dynamic_xfail_set_during_runtest_passed_strict

SUMMARY:
  ============================== 1 failed in 0.01s ===============================
  ============================== 1 passed in 0.00s ===============================
  ================= 2 failed, 32 passed, 47 deselected in 1.01s ==================
```
(full file: `data/real_runs/pytest-7490_rtk_test_output.txt`)

**Django's own test runner (not a runner rtk has framework-specific parsing
for):** `rtk test` fell back to a generic tail-truncation and returned
**only the last 5 lines of output**:
```
OUTPUT (last 5 lines):
  ----------------------------------------------------------------------
  Ran 53 tests in 0.995s
  FAILED (failures=3, skipped=1)
  Destroying test database for alias 'default' ('file:memorydb_default?mode=memory&cache=shared')...
```
(full file: `data/real_runs/django-12747_rtk_test_output.txt`)

This is a materially different — and worse — failure mode than "keeps a
one-line reason per failing test." The compressed output doesn't even name
*which* three tests failed, let alone why. The real raw log
(`data/real_runs/django-12747_raw_stdout_failing.txt`) contains three full
`FAIL:` blocks with tracebacks and assertion diffs, e.g.:
```
FAIL: test_fast_delete_empty_no_update_can_self_select (delete.tests.FastDeleteTests)
...
AssertionError: Tuples differ: (0, {'delete.User': 0}) != (0, {})
```
— all of it dropped. This becomes taxonomy category **T6** below, in
addition to the five categories carried over from the earlier draft (which
were themselves derived from rtk's own documentation, not fabricated, but
are now demoted to secondary since we have direct evidence).

## 4. Live localization trial (manual proxy, N=1 clean, with explicit caveats)

**Instance:** `pytest-dev__pytest-7490` — the real xfail-marker bug above.
**Method:** I read the problem statement, then separately reasoned about
what each condition's log would let an FL agent conclude, then explored the
real repo (`grep -n xfail src/_pytest/skipping.py`) exactly as
`agent_localizer.py`'s RDFS search would, then recorded a top-5 prediction
for each condition, **then and only then** read `gold_patch.diff`.

**Caveat, stated plainly:** I ran one exploration pass and reasoned about
what each condition's text would support, rather than running two fully
independent agent sessions with separate token budgets the way
`run_wp1_benchmark.py` would via the API. That's a real methodological gap
relative to the intended automated benchmark — treat this as a qualitative
pilot data point, not a statistically powered result.

**Ground truth (`data/instances.jsonl` diff, revealed only after prediction):**
`src/_pytest/skipping.py::pytest_runtest_setup` and
`src/_pytest/skipping.py::pytest_runtest_call`.

| Condition | What I could see | My top prediction | Result |
|---|---|---|---|
| Control (raw) | Full nested pytest run showing `add_marker(xfail)` then `assert 0`, full traceback to `test_skipping.py:440` | `_pytest/skipping.py` — specifically `pytest_runtest_makereport` / `evaluate_xfail_marks` | **File-level hit. Function-level near-miss** — real fix functions (`pytest_runtest_setup`, `pytest_runtest_call`) were in my explored candidate set from the same `grep` but not my #1 pick. |
| Static (rtk `rtk test` output) | Only the 3 `FAILED <name>: assert 0` lines shown in Section 3 | Same file, `_pytest/skipping.py` | **File-level hit**, same confidence as Control — because the **problem statement itself** names `request.node.add_marker` and the exact xfail-vs-6.0 behavior change, independent of the terminal log. |

**Honest interpretation:** for this one instance, compression did **not**
create a tax, because the issue description carried the discriminating
signal on its own. This complicates a naive "compression always hurts"
story and matches something GraphLocator's paper itself shows: symptom
vertices are often locatable directly from issue text; it's the *causal
walk to the root cause* (here, distinguishing `pytest_runtest_setup` vs.
`pytest_runtest_call` vs. `pytest_runtest_makereport` as the actual fix
site) that raw execution detail would help with — and neither condition
gave me enough to nail that at the function level in one pass.

**The Django instance was not usable for this trial** — I read
`gold_patch.diff` before recording a prediction while investigating the
compression behavior in Section 3, so that instance is real evidence for
Section 3 but cannot honestly be reported as a blind localization result.

## 5. Error taxonomy (updated)

| ID | Category | Real evidence |
|---|---|---|
| **T6 (new)** | Unrecognized-runner collapse | Django run: 100% of failure detail dropped, not just the traceback body — even the failing test *names* and count-by-type are gone from the compressed text, replaced by a generic tail. |
| T1 | Lost value evidence | Present in the raw Django log (`AssertionError: Tuples differ: (0, {'delete.User': 0}) != (0, {})`) and fully absent from the compressed output. |
| T2 | Lost stack frames | Both real runs: file:line tracebacks present in raw, absent in compressed. |
| T5 | Over-summarized reason | pytest run: `assert 0` survived as the one-line reason and was *not* discriminating (many different bugs produce `assert 0`); only the problem statement rescued localizability in this case. |

## 6. What's still needed for a statistically real quantitative result

This report is honest about its limits: **2 real live instances, 1 clean
blind trial.** To get the kind of Control-vs-Static hit-rate table the
original WP1 brief asks for (N=15–20, fully automated, no manual proxying),
`run_wp1_benchmark.py` needs to actually call an LLM via the API rather
than me reasoning through it by hand in this chat. That requires
`ANTHROPIC_API_KEY` in the execution environment — not available in this
sandbox. Everything else in the pipeline (real repo checkout, real test
execution, real `rtk` compression) is already working end to end, verified
with the two instances above; the only missing piece to scale to N=15 is
the credential.
