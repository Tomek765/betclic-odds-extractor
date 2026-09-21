# APEX Context Engine — maintenance contract

This directory is the single authoritative source tree for the Windows product.

## Product map

- `gui.py` — GUI and frozen entry point.
- `core.py`, `parser.py`, `exhaustive.py` — Betclic collection, accounting, and packet generation.
- `context_engine_adapter.py`, `apex_context_engine/` — deterministic Context Engine integration.
- `diagnostics.py` — writable runtime data paths and diagnostic output.
- `test_suite.py`, `test_*.py`, `tests_context/` — regression and contract tests.
- `BetclicFullOddsExtractor.spec`, `build_exe.py`, `installer.iss` — reproducible Windows release build.
- `diagnostics/` — only the small, immutable replay fixtures required by tests may remain here.

## Invariants

- Preserve exact source provenance, accounting, identity, period, settlement, and deterministic output.
- Never silently discard ambiguity. Unsupported or unproven semantics must remain explicit and fail closed.
- Do not introduce AI inference, a database, automated betting, or network dependencies beyond the Betclic capture requested by the operator.
- A release must run without a development Python installation and use its bundled official Playwright Chromium.
- Frozen runtime data belongs under `%LOCALAPPDATA%\APEX Context Engine` (or `APEX_DATA_DIR` in controlled tests), never under Program Files or the release directory.

## Required validation

Run from this directory:

```powershell
python -m unittest discover -q
python -m pytest -q
python -m compileall -q .
```

After a release build, test the extracted portable package and installed application outside this source tree, including a real GUI launch and a live `--release-e2e` extraction.
