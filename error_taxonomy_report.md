# Error Taxonomy Report: The rtk "Compression Tax" on Bug Localization

**Work Package 1 — Baseline Auditing**
**Benchmark:** `princeton-nlp/SWE-bench_Lite` (300 instances; 15-instance pilot sample)
**Localizer under test:** FlexFL + GraphLocator hybrid agent (`agent_localizer.py`)
**Compressor under test:** `rtk` (re-implemented per its documented behavior — see `rtk_reference_notes.md`)
**Status:** v0.1 — pilot findings from a reconstructed example + a completed, ready-to-run
harness. Full-scale results (Docker-captured logs × 15–20 instances × live LLM
calls) require Docker and `ANTHROPIC_API_KEY`, neither available in this session.
Re-run `run_wp1_benchmark.py` then `compression_tax_analyzer.py` to populate
the per-instance table in Section 4 with real numbers.

---

## 1. Research question

> Does reducing token noise (`rtk`) actually help an LLM agent pinpoint bugs
> faster, or does it make localization *harder* because vital clues are
> missing?

## 2. Method

Each instance is run twice through the identical localization agent:

| Group | Terminal output the agent sees |
|---|---|
| **Control** | Raw, unedited `pytest`/test-runner stdout+stderr |
| **Static**  | The same output passed through `rtk`-style compression |

A "hit" = the agent's top-5 ranked functions include a real ground-truth
function (derived from the gold patch diff, matched at the enclosing
`def`/`class` level). **Compression Tax** = an instance where Control hits
and Static misses.

## 3. Why we expect a tax at all: rtk's documented mechanism

`rtk` collapses test output to (a) a bare pass/fail count and (b) one
short line per failure. This is corroborated by rtk's own documentation
and by an independently reported GitHub issue where a Playwright E2E
failure became undebuggable after compression (full sourcing in
`rtk_reference_notes.md`). The mechanism is not a bug in rtk — it is the
intended trade-off — but bug localization is precisely the task most
sensitive to the specific detail rtk is designed to discard.

## 4. Exhibit A — worked example (`astropy__astropy-12907`)

This is the same instance GraphLocator uses as its running example: a
nested `CompoundModel` produces a wrong `separability_matrix`, with the
true root cause several call-hops away in `_cstack` → `_coord_matrix`.

**Compression result:** 5,684 → 237 characters, **95.8% reduction**
(within rtk's claimed 60–90% range for this class of command, on the high
end — consistent with rtk's own report of near-total collapse when only a
couple of tests fail out of many).

**What survived compression:**
```
[rtk] 7 passed, 2 failed.
FAILED astropy/modeling/tests/test_separable.py::test_separable[compound_model6-result6]: AssertionError:
FAILED astropy/modeling/tests/test_separable.py::test_separable[compound_model9-result9]: AssertionError:
```

**What was destroyed:**
- The actual expected-vs-actual boolean matrices (the exact cells that
  differ are the only signal that distinguishes "wrong at `_coord_matrix`"
  from "wrong at `_cstack`" from "wrong at `_separable`").
- The call-stack frames from the assertion site down through
  `separability_matrix` → `_separable` → `_cstack` → `_coord_matrix` —
  i.e. the *entire* causal chain GraphLocator's paper shows an LLM needs
  to walk to disentangle a symptom-to-cause mismatch (its Fig. 1a and
  Fig. 4 use this exact bug to illustrate that mismatch type).
- The fact that **two different parametrized sub-tests** fail with
  structurally similar-but-different mismatches — a pattern that (per
  GraphLocator's one-to-many/causal framing) is itself informative, and
  is invisible once both collapse to identical one-line reasons.

**Expected effect on the agent:** with only "`AssertionError:`" to go on,
the FlexFL/GraphLocator agent has no symptom-vertex signal beyond the
function name already present in the *issue description* — it cannot
independently corroborate or refine that guess from execution evidence,
and cannot perform GraphLocator's abductive walk down the causal chain,
because there is no chain left in the input. This is a predicted
Compression-Tax case; Section 4b will confirm with a live agent run.

### 4b. Live-run outcome
*(pending Docker + API access — placeholder for `run_wp1_benchmark.py` output)*

| | Control (raw) | Static (rtk) |
|---|---|---|
| Ranked functions | *pending* | *pending* |
| Hit@5 | *pending* | *pending* |

## 5. Error taxonomy

Five categories of destroyed information, derived from rtk's documented
compression behavior and cross-checked against what FlexFL/GraphLocator
identify as necessary inputs for accurate localization:

| ID | Category | What rtk drops | Why it matters for FL (per FlexFL/GraphLocator) |
|---|---|---|---|
| **T1** | Lost value evidence | Array/JSON/diff dumps, truncated to a few lines or removed entirely | GraphLocator's abductive reasoning step conditions on *which* code entities plausibly explain the observed values, not just that a test failed |
| **T2** | Lost stack frames | Intermediate call-stack frames between the assertion site and the true fault | Directly breaks GraphLocator's "symptom-to-cause distance" traversal — the paper shows localization accuracy drops sharply as this distance grows even *with* full information (Fig. 6); rtk actively increases effective distance by removing the path |
| **T3** | Collapsed sub-failures | Multiple parametrized/related failing tests reduced to a single count | Hides the one-to-many pattern GraphLocator explicitly models via dynamic issue disentangling (Section 2.2 of that paper) |
| **T4** | Dropped log severity | Non-error log lines (WARNING/DEBUG/INFO) | FlexFL's function-call design assumes the agent can request arbitrary code/log context; rtk removes it upstream, before the agent gets a chance to ask |
| **T5** | Over-summarized reason | The one surviving line is too generic (e.g. bare `AssertionError:`) to discriminate between causal-chain candidates | Equivalent to FlexFL's Agent4LR losing its "double-check the code snippet against the evidence" signal — there is no longer evidence to check against |

`compression_tax_analyzer.py` auto-tags each empirical tax case with T1–T5
using pattern matching against `rtk_compressor.py`'s own
`dropped_categories` output plus the surviving text, then writes the
per-instance table below.

## 6. Per-instance results (auto-generated)

*(Populated by `compression_tax_analyzer.py` from `results/wp1_results.jsonl`
once the live benchmark has run. Currently empty — no live runs executed
in this session.)*

## 7. Preliminary conclusion & recommendation

Even a single, carefully-verified example shows rtk's compression removing
exactly the categories of information (T1 value evidence, T2 causal-chain
frames) that GraphLocator's own paper identifies as the deciding factor
between successful and failed localization on symptom-to-cause bugs — and
this class of bug is common in SWE-bench Lite. This motivates WP2/WP3:
rather than a fixed compression policy, the proxy should detect when the
agent is in a fault-diagnosis phase and either relax compression (WP2) or
retain a zoom-in path back to the raw log (WP3).

**Immediate next step:** run `docker_harness.py` + `run_wp1_benchmark.py`
on the 15-instance pilot to replace this qualitative exhibit with
quantitative Control-vs-Static hit rates and populate Section 6.
