#!/usr/bin/env python3
"""
CLI bridge for batch processing — called by Node.js dashboard.
Persists state to data/batch_state.json so status/cancel work across invocations.

Commands (JSON on stdin):
  {"cmd": "start", "dua_ids": [...], "theme": "dark", "effect": "auto"}
  {"cmd": "status"}
  {"cmd": "cancel"}

Outputs JSON on stdout.
"""

import json
import logging
import os
import sys
import threading
import time
from queue import Queue

# Suppress all logging to keep stdout clean for JSON only
logging.disable(logging.CRITICAL)

# Ensure project root is on sys.path so we can import main
_PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

STATE_PATH = os.path.join(_PROJECT, "data", "batch_state.json")


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def _start_worker(state):
    """Launch daemon worker thread that processes the queue."""
    from main import DuaVideoPipeline

    def _worker():
        pipeline = DuaVideoPipeline()
        while True:
            item = state["queue"].pop(0) if state["queue"] else None
            if item is None:
                state["running"] = False
                _save_state(state)
                break

            dua_id = item["dua_id"]
            theme = item.get("theme", "dark")
            effect = item.get("effect", "auto")
            dry_run = item.get("dry_run", False)

            try:
                ok = pipeline.generate_video(dua_id, theme=theme, effect=effect, dry_run=dry_run)
            except Exception:
                ok = False

            state["done"] += 1
            if not ok:
                state["failed"] += 1
            state["results"].append({"dua_id": dua_id, "ok": ok})
            _save_state(state)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def main():
    try:
        raw = sys.stdin.read()
        req = json.loads(raw)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"bad input: {exc}"}))
        return

    cmd = req.get("cmd", "")

    try:
        if cmd == "start":
            state = _load_state()
            if state and state.get("running"):
                print(json.dumps({"ok": False, "error": "Batch already running"}))
                return

            dua_ids = req.get("dua_ids")  # None = all
            theme = req.get("theme", "dark")
            effect = req.get("effect", "auto")
            dry_run = req.get("dry_run", False)

            if dua_ids is None:
                from core.dua_database import DB

                duas = DB.get_all_duas()
                dua_ids = [d.get("id") for d in duas if d.get("id")]

            state = {
                "total": len(dua_ids),
                "done": 0,
                "failed": 0,
                "running": True,
                "results": [],
                "queue": [{"dua_id": did, "theme": theme, "effect": effect, "dry_run": dry_run} for did in dua_ids],
                "started_at": time.time(),
            }
            _save_state(state)
            _start_worker(state)
            print(json.dumps({"ok": True, "queued": len(dua_ids)}))

        elif cmd == "status":
            state = _load_state()
            if not state:
                print(
                    json.dumps(
                        {"ok": True, "total": 0, "done": 0, "failed": 0, "pending": 0, "running": False, "results": []}
                    )
                )
            else:
                pending = state["total"] - state["done"]
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "total": state["total"],
                            "done": state["done"],
                            "failed": state["failed"],
                            "pending": pending,
                            "running": state["running"],
                            "results": state["results"],
                        }
                    )
                )

        elif cmd == "cancel":
            state = _load_state()
            if not state:
                print(json.dumps({"ok": True}))
                return
            state["queue"] = []  # drain remaining
            state["running"] = False
            _save_state(state)
            print(json.dumps({"ok": True}))

        else:
            print(json.dumps({"ok": False, "error": f"unknown cmd: {cmd}"}))

    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))


if __name__ == "__main__":
    main()
