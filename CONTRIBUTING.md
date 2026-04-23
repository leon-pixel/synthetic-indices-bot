# Contributing

This repo is set up so anyone can **clone → install → backtest** (see [GETTING_STARTED.md](GETTING_STARTED.md)). Follow the rules below so changes stay reviewable and safe.

## Workflow

1. **Fork** the repository (if you are not a direct collaborator), or create a **branch** from `main`.
2. **One focused change per PR** — e.g. fix a bug, add a metric, or document a step. Avoid mixing refactors with strategy changes.
3. **Test before you push** (minimum):
   - `python3 -m sidx.research.run_backtest --csv testdata/sample_ticks.csv --out-dir reports/ci`
   - Or with `PYTHONPATH=.` if you did not `pip install -e .`
4. **Open a Pull Request** with a short description of *what* changed and *why*.
5. **Never commit secrets** — `.env`, API tokens, or account-specific paths.

## Strategy and risk changes

- Prefer **parameters** in `sidx/config.py` (or a small new config module) over hardcoding.
- If you change entry/exit rules, update:
  - `sidx/strategy.py` (and/or `sidx/research/simulation.py` if exit logic must match)
  - [docs/SPEC.md](docs/SPEC.md) or [docs/TRADINGVIEW_MAPPING.md](docs/TRADINGVIEW_MAPPING.md) if behavior is user-visible
- Run a backtest (and walk-forward if the change affects optimization) and paste key numbers in the PR (trades, PF, max DD from `summary.json`).

## Code style

- Match existing patterns: type hints where already used, small functions, no unrelated files.
- Keep dependencies in `requirements.txt` and `pyproject.toml` / `setup.cfg` in sync if you add packages.

## Releases and versioning

- `sidx/__init__.py` holds `__version__` — bump when you cut a meaningful release tag.
- Tag format: `v0.1.0`, `v0.2.0`, etc.

## Questions

Open a **GitHub Issue** for bugs, unclear docs, or proposed features. For quick doc fixes, a PR is welcome.
