# Phase 1 Monitoring Guide

This guide explains the first practical monitoring layer for the bot:

1. `paper.jsonl` as the event source of truth
2. Telegram alerts for key trade events
3. A local dashboard to visualize activity in real time

Use this on **demo/paper** first.

## 1) How monitoring works

The `run_paper` process emits structured events with `JsonlLogger`:

- `opened`
- `closed`
- `blocked`
- `open_failed`
- `close_failed`

Each event is appended to `logs/paper.jsonl`.

`JsonlLogger` now supports in-process subscribers:

- Telegram notifier subscribes and sends selected events to chat
- Dashboard reads the same JSONL file and renders live stats/events

This gives both machine-readable logs and human-friendly visibility.

## 2) Telegram setup (step-by-step)

### A. Create a bot with BotFather

1. Open Telegram and search for `@BotFather`
2. Run `/newbot`
3. Copy the bot token (looks like `123456789:ABCDEF...`)

### B. Get your chat ID

Quick method:

1. Start a chat with your new bot and send one message (e.g. `hi`)
2. Open this URL in browser (replace token):

```
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```

3. Find `"chat":{"id": ... }` and copy the numeric id.

### C. Put values into `.env`

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### D. Run paper bot with alerts

```bash
python3 -m sidx.bot.run_paper --log logs/paper.jsonl --telegram
```

You should receive messages when trades open/close or are blocked.

## 3) Dashboard setup

Start dashboard in another terminal:

```bash
python3 -m sidx.monitor.dashboard --log logs/paper.jsonl --port 8765
```

Open:

- `http://127.0.0.1:8765`

What you see:

- total opened / closed
- open positions count
- running net pnl (sum of `closed.pnl_money`)
- latest event stream

## 4) Recommended terminal layout

Use 2 terminals:

- **Terminal A**: paper bot loop
- **Terminal B**: dashboard

Optional 3rd terminal for quick log tail:

```bash
tail -f logs/paper.jsonl
```

## 5) Event fields reference

### `opened`

- `side`, `entry`, `tp`, `sl`, `contract_id`, `ts`

### `closed`

- `side`, `entry`, `exit`, `pnl_money`, `reason`, `ts`

### `blocked`

- `why`, `ts` (e.g. cooldown, outside session, daily cap)

### `open_failed` / `close_failed`

- `error`, `ts`, and possible contract identifiers

## 6) Operational best practices

- Keep `EXECUTION_MODE=sim` while validating alerts and dashboard
- Validate timezone assumptions (all timestamps are UTC-based)
- Never commit `.env` (already ignored)
- Use demo tokens, not live, until logs and behavior are stable

## 7) Troubleshooting

### No Telegram messages

- Confirm `--telegram` flag is used
- Confirm `TELEGRAM_ENABLED=true`
- Verify bot token/chat id are correct
- Ensure the bot has received at least one direct message from you

### Dashboard shows nothing

- Confirm paper bot is running and writing `logs/paper.jsonl`
- Confirm dashboard `--log` path matches bot log path
- Check file growth with `ls -lh logs/paper.jsonl`

### PnL looks odd

- Remember this is paper/sim by default
- `pnl_money` is model-based and not exchange statement PnL

