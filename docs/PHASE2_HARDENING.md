# Phase 2 Hardening Guide

Phase 2 adds production-safety features for the paper/live loop:

1. Startup contract validation
2. Persistent runtime state
3. Broker reconciliation for open positions
4. Automatic daily summary events

These improvements reduce hidden failure modes when the process restarts or broker state diverges.

## 1) Startup contract validation

At startup, `run_paper` validates Deriv proposal compatibility for both sides:

- `CALL` (buy-side flow)
- `PUT` (sell-side flow)

If proposals fail, the bot exits early with a clear message.

### Control

- CLI: `--validate-startup` / `--no-validate-startup`
- Env default: `VALIDATE_STARTUP=true`

Recommended: keep this enabled.

## 2) Persistent runtime state

The bot now persists runtime state to JSON:

- Risk manager counters and cooldown state
- Current open position (if any)

Default state path:

- `logs/runtime_state.json`

### Why this matters

If the process restarts, risk controls and open-position context are restored instead of resetting silently.

### Control

- CLI: `--state logs/runtime_state.json`

## 3) Reconciliation loop

When a position is open, the bot periodically queries broker contract status (`proposal_open_contract`) and reconciles external closures.

If a contract is already sold externally:

- local position is closed
- a `closed` event is logged with reason `reconcile_closed`
- risk PnL is updated

This protects against zombie local positions after disconnects/restarts.

## 4) Daily summary events

The bot aggregates day-level activity and emits a `daily_summary` event on UTC day rollover:

- opened / closed trades
- wins / losses
- blocked count
- net PnL
- block reason breakdown

If Telegram alerts are enabled, daily summaries are also sent to chat.

## 5) Run commands

### Recommended hardened run

```bash
python3 -m sidx.bot.run_paper \
  --log logs/paper.jsonl \
  --state logs/runtime_state.json \
  --validate-startup \
  --telegram
```

### Debug mode (skip startup validation temporarily)

```bash
python3 -m sidx.bot.run_paper \
  --log logs/paper.jsonl \
  --state logs/runtime_state.json \
  --no-validate-startup
```

## 6) New/important events

- `startup_validation`
- `state_restored`
- `state_restore_failed`
- `reconcile_error`
- `closed` with reason `reconcile_closed`
- `daily_summary`

These are all written to `paper.jsonl` and visible in dashboard/event tails.

