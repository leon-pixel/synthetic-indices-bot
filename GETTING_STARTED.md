# Getting started (for new contributors)

Follow these steps in order. You will go from **zero** to a **working backtest**, then optionally connect **Deriv** for data and paper trading.

**Repository owners:** the first time you put this on GitHub, use **[GITHUB_SETUP.md](GITHUB_SETUP.md)** (create empty repo, add `origin`, `git push`).

## 0. Prerequisites

- **Python 3.9+** ([python.org](https://www.python.org/downloads/) or `pyenv`)
- A **Git** client
- (Optional) **Deriv** demo account + [API token](https://app.deriv.com/account/api-token) for live tick history and paper trading

## 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/synthetic-indices-bot.git
cd synthetic-indices-bot
```

Replace `YOUR_USERNAME` with the GitHub owner (org or user) shown on the repo page.

## 2. Create a virtual environment

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Developer install (recommended so `sidx` is on the path):

```bash
pip install -e .
```

If you skip the editable install, set for every session:

```bash
export PYTHONPATH=.
```

On Windows (PowerShell):

```powershell
$env:PYTHONPATH = "."
```

## 4. Environment variables (Deriv)

```bash
cp .env.example .env
```

Edit `.env`:

- **`DERIV_API_TOKEN`** — required for `--fetch` and for `sidx.bot.run_paper`. Use a **demo / virtual** token until you trust the stack.
- **`DERIV_SYMBOL`** — e.g. `R_75`, `R_100` (must match what your account can trade).
- **`EXECUTION_MODE`** — use `sim` for research and safe paper (no real `buy`/`sell`). Use `deriv` only after you validate contracts on demo.

Never commit `.env` (it is gitignored).

## 5. Run your first backtest (no API key)

Uses bundled sample ticks:

```bash
python3 -m sidx.research.run_backtest --csv testdata/sample_ticks.csv --out-dir reports/run1
```

If you did not run `pip install -e .`, use:

```bash
PYTHONPATH=. python3 -m sidx.research.run_backtest --csv testdata/sample_ticks.csv --out-dir reports/run1
```

Check:

- `reports/run1/summary.json` — metrics and parameter hashes  
- `reports/run1/trade_ledger.csv` — trade list (if any trades)

## 6. Pull real history from Deriv (optional)

```bash
python3 -m sidx.research.run_backtest --fetch --n-ticks 50000 --out-dir reports/deriv_sample
```

This needs a valid `DERIV_API_TOKEN`. Ticks are cached under `reports/deriv_sample/ticks_cache.csv` for repeat runs.

## 7. Walk-forward + stress (optional)

```bash
python3 -m sidx.research.run_backtest --csv testdata/sample_ticks.csv --out-dir reports/wf --walk-forward 4
```

Latency stress (shifts features by *N* M1 bars):

```bash
python3 -m sidx.research.run_backtest --csv testdata/sample_ticks.csv --out-dir reports/stress --latency-bars 2
```

## 8. Paper streaming loop (optional)

Requires token and network. Stops on **Ctrl+C** (or SIGTERM).

```bash
python3 -m sidx.bot.run_paper --log logs/paper.jsonl
```

Read [docs/SPEC.md](docs/SPEC.md) for symbols, contract caveats, and TradingView parity notes.

## 9. Where to read next

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Overview and commands |
| [docs/SPEC.md](docs/SPEC.md) | Deriv symbols, risk defaults, TV parity |
| [docs/TRADINGVIEW_MAPPING.md](docs/TRADINGVIEW_MAPPING.md) | Pine vs Python mapping (non-authoritative lab) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How we update this repo |

## Common issues

- **`ModuleNotFoundError: sidx`** — run `pip install -e .` or set `PYTHONPATH=.` to the repo root.
- **`DERIV_API_TOKEN required`** — add token to `.env` for `--fetch` / `run_paper`.
- **Proposal / buy errors on Deriv** — contract `duration` and types vary by symbol; tune `ExecutionConfig` in `sidx/config.py` and test on **demo** only.
