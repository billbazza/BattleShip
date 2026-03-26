#!/usr/bin/env python3
"""
Telegram notification utility for Battleship Reset.
Handles sending messages, photos, inline keyboards, and polling callbacks.

Usage:
  from scripts.telegram_notify import send_message, send_photo_with_keyboard, poll_callbacks
"""

import json
import requests
from pathlib import Path

VAULT_ROOT   = Path(__file__).parent.parent
OFFSET_FILE  = VAULT_ROOT / "clients" / "telegram_offset.txt"
BASE_URL     = "https://api.telegram.org/bot{token}/{method}"


def _env() -> dict:
    env = {}
    env_path = Path.home() / ".battleship.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _creds() -> tuple:
    env = _env()
    return env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")


def _muted() -> bool:
    return _env().get("TELEGRAM_MUTED", "0").strip() == "1"


def _post(method: str, **kwargs) -> dict:
    token, _ = _creds()
    if not token:
        print("  ⚠️  TELEGRAM_BOT_TOKEN not set")
        return {}
    if _muted():
        print("  🔇  Telegram muted (TELEGRAM_MUTED=1)")
        return {"ok": False, "muted": True}
    resp = requests.post(
        BASE_URL.format(token=token, method=method),
        timeout=30,
        **kwargs
    )
    return resp.json() if resp.status_code == 200 else {"ok": False, "error": resp.text}


def send_message(text: str, parse_mode: str = "HTML") -> dict:
    """Send a plain text message."""
    _, chat_id = _creds()
    if not chat_id:
        return {}
    return _post("sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


def send_inline_keyboard(text: str, buttons: list) -> dict:
    """
    Send a message with inline keyboard.
    buttons: [[{"text": "✅ Yes", "callback_data": "approve_photo_001"}, ...], ...]
    """
    _, chat_id = _creds()
    if not chat_id:
        return {}
    return _post("sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons}
    })


def send_photo_with_keyboard(image_path: str, caption: str, buttons: list) -> dict:
    """Send a photo with inline keyboard buttons."""
    _, chat_id = _creds()
    if not chat_id:
        return {}
    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML",
        "reply_markup": json.dumps({"inline_keyboard": buttons})
    }
    if _muted():
        print("  🔇  Telegram muted (TELEGRAM_MUTED=1)")
        return {"ok": False, "muted": True}
    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                BASE_URL.format(token=_creds()[0], method="sendPhoto"),
                data=data,
                files={"photo": f},
                timeout=30
            )
        return resp.json() if resp.status_code == 200 else {"ok": False}
    except Exception as e:
        print(f"  ⚠️  Telegram photo send failed: {e}")
        return {}


def answer_callback(callback_query_id: str, text: str = "Got it") -> dict:
    return _post("answerCallbackQuery", json={"callback_query_id": callback_query_id, "text": text})


def poll_callbacks(offset_file: Path = None) -> list:
    """
    Poll for button-press callbacks since last check.
    Returns list of {"callback_id", "data", "from_user"}.
    Updates offset file to avoid reprocessing.
    """
    if offset_file is None:
        offset_file = OFFSET_FILE

    offset = 0
    if offset_file.exists():
        try:
            offset = int(offset_file.read_text().strip())
        except Exception:
            offset = 0

    token, _ = _creds()
    if not token:
        return []

    resp = requests.get(
        BASE_URL.format(token=token, method="getUpdates"),
        params={"offset": offset, "timeout": 5, "allowed_updates": ["callback_query", "message"]},
        timeout=15
    )
    if resp.status_code != 200:
        return []

    updates = resp.json().get("result", [])
    callbacks = []
    new_offset = offset

    for update in updates:
        uid = update.get("update_id", 0)
        new_offset = max(new_offset, uid + 1)
        cq = update.get("callback_query")
        if cq:
            callbacks.append({
                "callback_id": cq["id"],
                "data": cq.get("data", ""),
                "from_user": cq.get("from", {}).get("first_name", "Will"),
                "message_id": cq.get("message", {}).get("message_id"),
            })
            answer_callback(cq["id"])

    if new_offset > offset:
        offset_file.parent.mkdir(parents=True, exist_ok=True)
        offset_file.write_text(str(new_offset))

    return callbacks
