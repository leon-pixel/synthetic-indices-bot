from __future__ import annotations

import argparse
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, max_events: int = 400) -> None:
        self._lock = threading.Lock()
        self.events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self.total_opened = 0
        self.total_closed = 0
        self.net_pnl = 0.0
        self.open_positions = 0
        self.last_event_ts = ""

    def add(self, evt: dict[str, Any]) -> None:
        with self._lock:
            self.events.appendleft(evt)
            self.last_event_ts = str(evt.get("ts", ""))
            event = str(evt.get("event", ""))
            if event == "opened":
                self.total_opened += 1
                self.open_positions += 1
            elif event == "closed":
                self.total_closed += 1
                self.open_positions = max(0, self.open_positions - 1)
                try:
                    self.net_pnl += float(evt.get("pnl_money", 0.0))
                except Exception:
                    pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stats": {
                    "total_opened": self.total_opened,
                    "total_closed": self.total_closed,
                    "open_positions": self.open_positions,
                    "net_pnl": round(self.net_pnl, 8),
                    "last_event_ts": self.last_event_ts,
                },
                "events": list(self.events),
            }


HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SIDX Live Monitor</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 20px; background: #0f1115; color: #e7e9ee; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .card { background: #171b22; border: 1px solid #2a313d; border-radius: 10px; padding: 12px; }
    .title { font-size: 12px; color: #aab2c5; margin-bottom: 4px; }
    .value { font-size: 20px; font-weight: 700; }
    table { width: 100%; border-collapse: collapse; background: #171b22; border: 1px solid #2a313d; border-radius: 8px; overflow: hidden; }
    th, td { text-align: left; border-bottom: 1px solid #2a313d; padding: 8px; font-size: 13px; vertical-align: top; }
    th { color: #aab2c5; font-weight: 600; }
    .ok { color: #74d99f; } .bad { color: #ff8d8d; } .muted { color: #aab2c5; }
    code { color: #c6d2ff; }
  </style>
</head>
<body>
  <h2>SIDX Live Monitor</h2>
  <p class="muted">Polling <code>/api/state</code> every 2s from local JSONL events.</p>
  <div class="grid">
    <div class="card"><div class="title">Opened</div><div class="value" id="opened">0</div></div>
    <div class="card"><div class="title">Closed</div><div class="value" id="closed">0</div></div>
    <div class="card"><div class="title">Open Positions</div><div class="value" id="open_pos">0</div></div>
    <div class="card"><div class="title">Net PnL</div><div class="value" id="pnl">0.0</div></div>
  </div>
  <table>
    <thead><tr><th>Time</th><th>Event</th><th>Details</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
<script>
async function refresh() {
  try {
    const resp = await fetch('/api/state');
    const data = await resp.json();
    const s = data.stats || {};
    document.getElementById('opened').textContent = s.total_opened ?? 0;
    document.getElementById('closed').textContent = s.total_closed ?? 0;
    document.getElementById('open_pos').textContent = s.open_positions ?? 0;
    const pnl = Number(s.net_pnl ?? 0);
    const pnlEl = document.getElementById('pnl');
    pnlEl.textContent = pnl.toFixed(5);
    pnlEl.className = 'value ' + (pnl >= 0 ? 'ok' : 'bad');

    const rows = document.getElementById('rows');
    rows.innerHTML = '';
    for (const e of (data.events || []).slice(0, 120)) {
      const tr = document.createElement('tr');
      const evt = e.event || '';
      let details = '';
      if (evt === 'opened') details = `side=${e.side} entry=${e.entry} tp=${e.tp} sl=${e.sl}`;
      else if (evt === 'closed') details = `side=${e.side} exit=${e.exit} pnl=${e.pnl_money} reason=${e.reason}`;
      else if (evt === 'blocked') details = `why=${e.why}`;
      else details = JSON.stringify(e);
      tr.innerHTML = `<td>${e.ts || ''}</td><td>${evt}</td><td>${details}</td>`;
      rows.appendChild(tr);
    }
  } catch (e) {}
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


def tail_jsonl(path: Path, store: EventStore, stop: threading.Event, from_start: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with path.open("r", encoding="utf-8") as fp:
        if not from_start:
            fp.seek(0, 2)
        while not stop.is_set():
            line = fp.readline()
            if not line:
                time.sleep(0.5)
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            if isinstance(evt, dict):
                store.add(evt)


def make_handler(store: EventStore):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/" or self.path.startswith("/index.html"):
                body = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/api/state"):
                payload = json.dumps(store.snapshot(), default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:  # keep stdout clean
            return

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description="Local dashboard for paper JSONL log")
    ap.add_argument("--log", type=str, default="logs/paper.jsonl")
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--from-start", action="store_true", help="Load full existing file instead of tail-only")
    args = ap.parse_args()

    store = EventStore()
    stop = threading.Event()
    t = threading.Thread(
        target=tail_jsonl,
        args=(Path(args.log), store, stop, bool(args.from_start)),
        daemon=True,
    )
    t.start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"Dashboard running at http://{args.host}:{args.port}  (log: {args.log})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()

