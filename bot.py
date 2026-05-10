"""
Politician Copy Trading Bot
Target: Tim Moore (M001236) — Republican, NC — 52% gain in 2025

Run this script on a schedule (every 30 min via Windows Task Scheduler).
It checks for new Tim Moore trades on Capitol Trades, copies them via Alpaca paper account.
State is persisted in state.json to avoid double-trading.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import scraper
import trader

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"processed_trade_ids": [], "trades_executed": []}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main loop (single run — schedule externally)
# ---------------------------------------------------------------------------

def run() -> None:
    log.info("=" * 60)
    log.info("Politician Copy Trader  —  %s", datetime.now().strftime("%Y-%m-%d %H:%M"))

    cfg = load_config()
    state = load_state()

    alpaca_cfg = cfg["alpaca"]
    target = cfg["target"]
    trading_cfg = cfg["trading"]

    # Environment variables override config (used by GitHub Actions secrets)
    if os.environ.get("ALPACA_API_KEY"):
        alpaca_cfg["api_key"] = os.environ["ALPACA_API_KEY"]
    if os.environ.get("ALPACA_API_SECRET"):
        alpaca_cfg["api_secret"] = os.environ["ALPACA_API_SECRET"]

    dry_run: bool = os.environ.get("DRY_RUN", "").lower() == "true" or trading_cfg.get("dry_run", False)
    trade_amount: float = float(os.environ.get("TRADE_AMOUNT_USD", trading_cfg.get("trade_amount_usd", 500)))
    days_back: int = int(trading_cfg.get("days_lookback", 7))

    if dry_run:
        log.info("DRY RUN MODE — no real orders will be placed")

    # --- Alpaca client ---
    client = trader.make_client(alpaca_cfg["api_key"], alpaca_cfg["api_secret"])

    # Bail out if market is closed (no point placing orders)
    if not dry_run and not trader.is_market_open(client):
        log.info("Market is closed — skipping this run.")
        state["last_checked"] = datetime.now().isoformat()
        save_state(state)
        return

    summary = trader.get_account_summary(client)
    log.info(
        "Account: equity=$%.2f  cash=$%.2f  buying_power=$%.2f",
        summary["equity"], summary["cash"], summary["buying_power"],
    )

    if summary["buying_power"] < trade_amount and not dry_run:
        log.warning("Buying power $%.2f is below trade amount $%.2f", summary["buying_power"], trade_amount)

    # --- Fetch trades ---
    trades = scraper.get_trades(target["politician_id"], days_back=days_back)
    log.info("Found %d recent trade(s) for %s", len(trades), target["name"])

    processed_ids: list = state["processed_trade_ids"]
    new_trades = [t for t in trades if t["id"] not in processed_ids]
    log.info("%d are new (not yet copied)", len(new_trades))

    # --- Execute ---
    for trade in new_trades:
        ticker = trade["ticker"]
        action = trade["action"]
        asset_type = trade["asset_type"]
        trade_id = trade["id"]

        log.info(
            "Processing trade %s: %s %s (%s)  filed=%s  traded=%s",
            trade_id, action.upper(), ticker, asset_type,
            trade["filed_date"].strftime("%Y-%m-%d"),
            trade["traded_date"].strftime("%Y-%m-%d"),
        )

        if asset_type in ("option", "call", "put"):
            log.warning(
                "Trade %s is an option — Congress disclosures lack strike/expiry. "
                "Buying stock %s as proxy.", trade_id, ticker
            )
            # Fall through and treat as stock buy/sell

        result = {}
        try:
            if action == "buy":
                result = trader.buy(client, ticker, trade_amount, dry_run=dry_run)
            else:
                result = trader.sell_position(client, ticker, dry_run=dry_run)
        except Exception as exc:
            log.error("Order failed for %s %s: %s", action, ticker, exc)
            result = {"status": "error", "error": str(exc)}

        # Record what we did
        processed_ids.append(trade_id)
        state["trades_executed"].append({
            "trade_id": trade_id,
            "ticker": ticker,
            "action": action,
            "asset_type": asset_type,
            "executed_at": datetime.now().isoformat(),
            "result": result,
        })

    state["processed_trade_ids"] = processed_ids
    state["last_checked"] = datetime.now().isoformat()
    save_state(state)

    log.info("Done. State saved to %s", STATE_FILE)
    log.info("=" * 60)


if __name__ == "__main__":
    run()
