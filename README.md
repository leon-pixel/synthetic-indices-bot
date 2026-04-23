# Synthetic indices bot (Deriv)

Mean-reversion style bot for **Deriv synthetic indices**: shared tick → candle pipeline, **backtesting** / walk-forward, **risk limits**, and a **paper** streaming loop. Research uses **Deriv `ticks_history`** when you want broker-aligned results.

> **New here?** Start with **[GETTING_STARTED.md](GETTING_STARTED.md)** — clone, install, first backtest, optional Deriv + paper.  
> **First-time maintainer:** publish to GitHub with **[GITHUB_SETUP.md](GITHUB_SETUP.md)**.  
> **Contributing / updates:** see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Features

- M1 + M5 indicators (EMA, RSI, ATR regime), rule-based signals with reason codes
- Simulated execution with spread/slippage knobs; optional Deriv `proposal` / `buy` / `sell`
- Risk manager: session window, cooldown, daily loss, consecutive losses, kill switch
- Research CLI: CSV or `--fetch` ticks, `--walk-forward`, `--latency-bars` stress
- Optional TradingView Pine lab + mapping doc (non-authoritative vs Deriv ticks)

## Requirements

- Python **3.9+**
- See [requirements.txt](requirements.txt)

## Quick start (short)

```bash
git clone https://github.com/YOUR_USERNAME/synthetic-indices-bot.git
cd synthetic-indices-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
python3 -m sidx.research.run_backtest --csv testdata/sample_ticks.csv --out-dir reports/run1
```

Replace `YOUR_USERNAME` after you fork or create the GitHub repo. Full steps: **[GETTING_STARTED.md](GETTING_STARTED.md)**.

## Commands

| Goal | Command |
|------|---------|
| Backtest (offline sample) | `python3 -m sidx.research.run_backtest --csv testdata/sample_ticks.csv --out-dir reports/run1` |
| Fetch ticks from Deriv | `python3 -m sidx.research.run_backtest --fetch --n-ticks 50000 --out-dir reports/from_deriv` |
| Walk-forward + RSI grid | add `--walk-forward 4` |
| Stress (late signals) | add `--latency-bars 2` |
| Paper stream (needs token) | `python3 -m sidx.bot.run_paper --log logs/paper.jsonl` |
| Paper stream + Telegram | `python3 -m sidx.bot.run_paper --log logs/paper.jsonl --telegram` |
| Hardened paper run (Phase 2) | `python3 -m sidx.bot.run_paper --log logs/paper.jsonl --state logs/runtime_state.json --validate-startup --telegram` |
| Local live dashboard | `python3 -m sidx.monitor.dashboard --log logs/paper.jsonl --port 8765` |

If you skip `pip install -e .`, prefix with `PYTHONPATH=.` (see GETTING_STARTED).

## Phase 1 monitoring (concrete)

1. Start paper loop (terminal A):
   - `python3 -m sidx.bot.run_paper --log logs/paper.jsonl`
2. Start dashboard (terminal B):
   - `python3 -m sidx.monitor.dashboard --log logs/paper.jsonl --port 8765`
3. Open [http://127.0.0.1:8765](http://127.0.0.1:8765)
4. Optional Telegram alerts:
   - set `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` in `.env`
   - run paper loop with `--telegram`
   - detailed setup (BotFather + chat ID): `docs/PHASE1_MONITORING.md`

## Documentation

| Doc | Content |
|-----|---------|
| [GETTING_STARTED.md](GETTING_STARTED.md) | Step-by-step for anyone cloning the repo |
| [docs/SPEC.md](docs/SPEC.md) | Deriv symbols, contracts, risk defaults, TV parity |
| [docs/TRADINGVIEW_MAPPING.md](docs/TRADINGVIEW_MAPPING.md) | Pine vs Python |
| [docs/PHASE1_MONITORING.md](docs/PHASE1_MONITORING.md) | Detailed Telegram + local dashboard setup |
| [docs/PHASE2_HARDENING.md](docs/PHASE2_HARDENING.md) | Startup validation, persistence, reconciliation, daily summary |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How we update GitHub safely |

## Disclaimer

This is educational software. Trading involves risk. Past backtests do not guarantee future results. Use a **demo** account until you understand behavior, fees, and contract rules for your symbol.

## License

[MIT](LICENSE)
