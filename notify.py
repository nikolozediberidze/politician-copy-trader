"""Telegram push notifications."""

import logging
import os
import requests
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _load_from_config() -> tuple[str, str]:
    """Fallback: read token/chat_id from config.json."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(config_path, encoding="utf-8") as f:
            import json
            cfg = json.load(f)
        tg = cfg.get("telegram", {})
        return tg.get("token", ""), tg.get("chat_id", "")
    except Exception:
        return "", ""


def send(message: str) -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram not configured — skipping notification")
        return
    try:
        resp = requests.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Telegram notification sent")
    except Exception as exc:
        log.warning("Telegram notification failed: %s", exc)
