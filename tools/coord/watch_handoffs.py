"""Handoff monitor: print one line whenever new work for an agent appears. Checks every 2 minutes.

Watches, for the given agent (claude | codex):
  - handoff files in .coordination/handoffs/ with `To: <agent>` and `Status: pending`
  - queue rows in .coordination/STATUS.md whose state is `queued`: rows marked "(claude)" belong to
    Claude, all other queued rows to Codex
Each item is reported once per run (already-pending items are reported at start, prefixed "pending").

Usage: python tools/coord/watch_handoffs.py <claude|codex> [--interval 120] [--once]
Stdlib only. Run it in the background; each printed line is an event to act on.
"""
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COORD = ROOT / ".coordination"


def pending_handoffs(agent):
    out = set()
    for f in sorted((COORD / "handoffs").glob("*.md")):
        try:
            head = f.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            continue
        if re.search(rf"^To:\s*{agent}\b", head, re.M | re.I) and re.search(r"^Status:\s*pending", head, re.M | re.I):
            out.add(f"handoff {f.name}")
    return out


def queued_rows(agent):
    out = set()
    try:
        text = (COORD / "STATUS.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|(.*)\|\s*([^|]*)\|\s*$", line)
        if not m:
            continue
        number, body, state = m.group(1), m.group(2), m.group(3).strip().lower()
        if not state.startswith("queued"):
            continue
        mine = "(claude)" in (body + state).lower()
        if (agent == "claude") == mine:
            task = body.split("|")[0].strip()
            out.add(f"queue #{number}: {task[:120]}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("agent", choices=["claude", "codex"])
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--once", action="store_true", help="print what is pending now and exit")
    a = ap.parse_args()
    seen = set()
    first = True
    while True:
        items = pending_handoffs(a.agent) | queued_rows(a.agent)
        for item in sorted(items - seen):
            print(f"{'pending' if first else 'NEW'} for {a.agent}: {item}", flush=True)
        seen |= items
        if a.once:
            return
        first = False
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
