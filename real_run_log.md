# How the real data in this project was produced

No simulation, no docker (unavailable in this sandbox) — direct repo
checkout + venv + real interpreter + real `rtk` binary.

## 1. Install real rtk
```bash
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
rtk --version   # rtk 0.45.0
```

## 2. Get a Python version old enough for the target instance
SWE-bench Lite instances from ~2020 often don't run on Python 3.12 (e.g.
pytest 6.0's own AST-rewrite machinery breaks on 3.12's stricter `ast`
module). `uv` fetches a real interpreter with no compilation:
```bash
uv python install 3.9
PY39=$(uv python find 3.9)
```

## 3. Clone the repo at the SWE-bench base_commit, install, apply the gold test_patch
```bash
git clone https://github.com/<org>/<repo>.git repo && cd repo
git checkout <base_commit>          # may need `git fetch --unshallow` first
$PY39 -m venv ../venv
../venv/bin/pip install -e .
git apply <test_patch.diff>         # from the SWE-bench_Lite record
```

## 4. Capture the real raw failing run, and the real rtk-compressed run
```bash
../venv/bin/python -m pytest <path> -v > raw_output.txt 2>&1     # Control
rtk test ../venv/bin/python -m pytest <path>                     # Static
rtk gain                                                          # ground-truth % reduction
```

## What we actually ran (see data/real_runs/ for every byte)
- `pytest-dev__pytest-7490`: real xfail-marker regression, Python 3.9,
  pytest 6.0.0rc2 built from the exact buggy commit. 2/34 tests genuinely
  fail after applying the gold test_patch, matching SWE-bench's
  `FAIL_TO_PASS` list exactly.
- `django__django-12747`: real QuerySet.delete() bug, Python 3.9, Django
  3.1 built from the exact buggy commit. 3/53 tests genuinely fail after
  applying the gold test_patch, matching `FAIL_TO_PASS` exactly.

## Known limitation of this pilot
Only 2 instances were run live (time/compute budget in this session), and
only 1 could be used as a clean blind localization trial (see
`error_taxonomy_report.md` Section 4 for why the other was disqualified).
Scaling to the full 15–20 instance subset needs: (a) more wall-clock time
per instance for the older/heavier repos (astropy, scikit-learn, sympy
need C-extension builds that failed in this sandbox), and (b) an
`ANTHROPIC_API_KEY` so `run_wp1_benchmark.py` can drive `agent_localizer.py`
automatically instead of a human-in-the-loop proxy.
