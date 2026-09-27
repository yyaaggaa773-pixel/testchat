#!/usr/bin/env python3
"""
Local LAN Chat API for Roblox scripts.
Run:  python roblox_chat_api.py
Default: http://0.0.0.0:8765
"""

from __future__ import annotations

import socket
import threading
import time
from collections import deque
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS

# ── config ──────────────────────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 8765
COOLDOWN_SEC = 10.0
MAX_MESSAGES = 200
MAX_NAME_LEN = 32
MAX_TEXT_LEN = 200

app = Flask(__name__)
CORS(app)

_lock = threading.Lock()
_messages: deque[dict[str, Any]] = deque(maxlen=MAX_MESSAGES)
# player_name(lower) -> last send unix time
_last_send: dict[str, float] = {}
_msg_id = 0


def _now() -> float:
    return time.time()


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _clean_name(raw: Any) -> str | None:
    if raw is None:
        return None
    name = str(raw).strip()
    if not name:
        return None
    name = name[:MAX_NAME_LEN]
    # basic sanitize
    name = "".join(ch for ch in name if ch.isprintable() and ch not in "\r\n\t")
    return name or None


def _clean_text(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text[:MAX_TEXT_LEN]
    text = "".join(ch for ch in text if ch.isprintable() or ch in " ")
    text = " ".join(text.split())
    return text or None


@app.get("/")
def index():
    return jsonify(
        {
            "ok": True,
            "service": "Roblox Chat API",
            "endpoints": {
                "GET  /api/health": "status",
                "GET  /api/messages": "list messages (?after_id=N optional)",
                "POST /api/send": "send message {player, message}",
            },
            "cooldown_sec": COOLDOWN_SEC,
        }
    )


@app.get("/api/health")
def health():
    with _lock:
        count = len(_messages)
    return jsonify({"ok": True, "messages": count, "time": _now()})


@app.get("/api/messages")
def get_messages():
    """
    Query:
      after_id  - return only messages with id > after_id (for polling)
      limit     - max items (default 50, max 200)
    """
    try:
        after_id = int(request.args.get("after_id", 0) or 0)
    except ValueError:
        after_id = 0
    try:
        limit = int(request.args.get("limit", 50) or 50)
    except ValueError:
        limit = 50
    limit = max(1, min(limit, MAX_MESSAGES))

    with _lock:
        items = [m for m in _messages if m["id"] > after_id]
        items = items[-limit:]

    return jsonify({"ok": True, "messages": items, "count": len(items)})


@app.post("/api/send")
def send_message():
    """
    Body JSON (or form):
      player   - Roblox display / username (required)
      message  - chat text (required)
    """
    data = request.get_json(silent=True) or {}
    if not data:
        data = request.form.to_dict() if request.form else {}

    # also allow query-style for simple HttpGet abuse
    player = _clean_name(data.get("player") or request.args.get("player"))
    message = _clean_text(data.get("message") or request.args.get("message"))

    if not player:
        return jsonify({"ok": False, "error": "player is required"}), 400
    if not message:
        return jsonify({"ok": False, "error": "message is required"}), 400

    key = player.lower()
    now = _now()

    with _lock:
        last = _last_send.get(key, 0.0)
        left = COOLDOWN_SEC - (now - last)
        if left > 0:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "cooldown",
                        "retry_after": round(left, 2),
                        "cooldown_sec": COOLDOWN_SEC,
                    }
                ),
                429,
            )

        global _msg_id
        _msg_id += 1
        entry = {
            "id": _msg_id,
            "player": player,
            "message": message,
            "time": now,
        }
        _messages.append(entry)
        _last_send[key] = now

    return jsonify({"ok": True, "message": entry})


@app.post("/api/clear")
def clear_messages():
    """Optional admin clear — local use only."""
    with _lock:
        _messages.clear()
        _last_send.clear()
    return jsonify({"ok": True})


def main():
    ip = _local_ip()
    print("=" * 50)
    print("  Roblox Chat API  (LAN)")
    print("=" * 50)
    print(f"  Local:   http://127.0.0.1:{PORT}")
    print(f"  Network: http://{ip}:{PORT}")
    print(f"  Cooldown: {COOLDOWN_SEC:.0f}s per player")
    print()
    print("  POST /api/send   JSON: {\"player\":\"Name\",\"message\":\"hi\"}")
    print("  GET  /api/messages")
    print("=" * 50)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
