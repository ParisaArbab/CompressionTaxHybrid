# Work Package 1 — Baseline Auditing & The "Compression Tax"

Evaluates whether `rtk`-style terminal-output compression helps or hurts
LLM bug localization on `princeton-nlp/SWE-bench_Lite`, using a
FlexFL + GraphLocator hybrid agent as the localizer.

## What actually ran in this session — real, live, verifiable

1. **`fetch_instances.py`** — pulled real `SWE-bench_Lite` (300 instances)
   from Hugging Face, sampled 15, derived function-level ground truth from
   each gold patch. Output: `data/instances.jsonl`.
2. **The real `rtk` binary (v0.45.0)** — installed via its official
   `install.sh`, no re-implementation. Run against **two genuinely captured
   failing test suites** (not reconstructed logs): `pytest-dev__pytest-7490`
   and `django__django-12747`, each cloned at the exact SWE-bench
   `base_commit`, with the real gold `test_patch` applied, on a real Python
   3.9 interpreter (fetched with `uv`, since these instances predate
   Python 3.12 support). Every byte is in `data/real_runs/`; see
   `docs/real_run_log.md` for the exact reproduction steps.
3. **A real, if small, finding**: rtk compresses recognized runners
   (pytest) down to a one-line-per-failure summary (86.8% reduction, real
   `rtk gain` number), but on an unrecognized runner (Django's own test
   runner) it falls back to a generic tail-truncation that drops **all**
   failure detail — not even the names of the 3 failing tests survive
   (96.0% reduction). See `docs/error_taxonomy_report.md` Section 3.
4. **One real, blind localization trial** (`pytest-dev__pytest-7490`):
   I explored the actual repo and made genuine Control-vs-Static
   predictions *before* looking at the gold patch. Result, plus an honest
   discussion of why it's a manual proxy and not the automated benchmark,
   is in `docs/error_taxonomy_report.md` Section 4.

## What needs credentials/compute to scale up (code is complete, untested live)

- **`agent_localizer.py`** — the FlexFL(Agent4SR/Agent4LR) + GraphLocator
  (RDFS + priority-driven CIG) hybrid localizer. Requires
  `ANTHROPIC_API_KEY` to run as an automated agent instead of the manual
  proxy trial above.
- **`run_wp1_benchmark.py`** — orchestrates Control vs Static runs per
  instance and writes `results/wp1_results.jsonl`. Ready to point at the
  same real-repo-capture workflow documented in `docs/real_run_log.md`.
- **`compression_tax_analyzer.py`** — turns `results/wp1_results.jsonl`
  into the populated per-instance taxonomy tables.
- **`docker_harness.py`** — an alternative capture path using the official
  `swebench` per-instance Docker images (needed for repos with heavy
  C-extension builds like astropy/scikit-learn/sympy, which failed to
  build directly in this sandbox). Not needed for pure-Python repos, which
  is what `docs/real_run_log.md`'s direct venv approach handles.

## To run the full pilot yourself

```bash
pip install -r requirements.txt
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
export ANTHROPIC_API_KEY=...
python3 fetch_instances.py --n 20 --single-file-only
# for each instance: follow docs/real_run_log.md to get a real raw + real
# rtk-compressed capture (or docker_harness.py for heavier repos)
python3 run_wp1_benchmark.py
python3 compression_tax_analyzer.py
```

## Design notes

- **Ground truth**: derived from each instance's gold `patch` diff, at the
  enclosing `def`/`class` granularity — the same "function-level" ground
  truth definition GraphLocator uses (Section 4.1 of that paper).
- **Localizer**: deliberately a *simplified* FlexFL+GraphLocator hybrid
  (no MBFL/SBFL space reduction, no fuzzy-name search tool) — WP1's job is
  to isolate the raw-vs-compressed effect, not to reproduce either paper's
  full benchmark numbers.
- **Compression**: uses the real `rtk` binary directly (`rtk_compressor.py`
  shells out to it), not a Python re-implementation.
