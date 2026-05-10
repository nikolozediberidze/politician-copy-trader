"""
Politician Copy Trading Bot
Targets: Tim Moore (M001236) + Terri Sewell (S001185)

Runs every 30 min via GitHub Actions (Mon-Fri).
Checks Capitol Trades, copies new trades to Alpaca paper account.
Sends Telegram notifications on every check and every trade.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import scraper
import trader
import notify

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


def run() -> None:
    log.info("=" * 60)
    log.info("Politician Copy Trader  —  %s", datetime.now().strftime("%Y-%m-%d %H:%M"))

    cfg = load_config()
    state = load_state()

    alpaca_cfg = cfg["alpaca"]
    targets = cfg["targets"]
    trading_cfg = cfg["trading"]

    if os.environ.get("ALPACA_API_KEY"):
        alpaca_cfg["api_key"] = os.environ["ALPACA_API_KEY"]
    if os.environ.get("ALPACA_API_SECRET"):
        alpaca_cfg["api_secret"] = os.environ["ALPACA_API_SECRET"]

    dry_run: bool = os.environ.get("DRY_RUN", "").lower() == "true" or trading_cfg.get("dry_run", False)
    trade_amount: float = float(os.environ.get("TRADE_AMOUNT_USD", trading_cfg.get("trade_amount_usd", 100)))
    days_back: int = int(trading_cfg.get("days_lookback", 7))

    if dry_run:
        log.info("DRY RUN MODE — no real orders will be placed")

    # --- Alpaca client ---
    client = trader.make_client(alpaca_cfg["api_key"], alpaca_cfg["api_secret"])

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

    # --- Send check notification (only on 2026-05-11 to verify setup) ---
    if datetime.now().strftime("%Y-%m-%d") == "2026-05-11":
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        target_names = " + ".join(t["name"] for t in targets)
        notify.send(
            f"🔍 <b>Checking trades...</b>\n"
            f"Time: {now_str}\n"
            f"Watching: {target_names}\n"
            f"Account equity: ${summary['equity']:,.2f}"
        )

    processed_ids: list = state["processed_trade_ids"]
    total_new = 0

    # --- Loop over all targets ---
    for target in targets:
        name = target["name"]
        pid = target["politician_id"]
        party = target["party"]
        state_abbr = target["state"]

        log.info("--- Checking %s (%s) ---", name, pid)
        trades = scraper.get_trades(pid, days_back=days_back)
        new_trades = [t for t in trades if t["id"] not in processed_ids]
        log.info("%d new trade(s) for %s", len(new_trades), name)
        total_new += len(new_trades)

        for trade in new_trades:
            ticker = trade["ticker"]
            action = trade["action"]
            asset_type = trade["asset_type"]
            trade_id = trade["id"]

            log.info(
                "Processing trade %s: %s %s (%s)  filed=%s",
                trade_id, action.upper(), ticker, asset_type,
                trade["filed_date"].strftime("%Y-%m-%d"),
            )

            if asset_type in ("option", "call", "put"):
                log.warning(
                    "Trade %s is an option — buying stock %s as proxy.", trade_id, ticker
                )

            result = {}
            try:
                if action == "buy":
                    result = trader.buy(client, ticker, trade_amount, dry_run=dry_run)
                else:
                    result = trader.sell_position(client, ticker, dry_run=dry_run)
            except Exception as exc:
                log.error("Order failed for %s %s: %s", action, ticker, exc)
                result = {"status": "error", "error": str(exc)}

            # Telegram notification per trade
            status = result.get("status", "unknown")
            politician_tag = f"{name} ({party[0]}-{state_abbr})"
            if status == "error":
                msg = (
                    f"❌ <b>Trade FAILED</b>\n"
                    f"Politician: {politician_tag}\n"
                    f"Action: {action.upper()} {ticker}\n"
                    f"Error: {result.get('error', 'unknown')}"
                )
            elif status == "skipped":
                msg = (
                    f"⏭ <b>Sell Skipped</b>\n"
                    f"Politician: {politician_tag}\n"
                    f"Ticker: {ticker}\n"
                    f"Reason: no position held"
                )
            else:
                emoji = "📈" if action == "buy" else "📉"
                label = f"BUY ${trade_amount:.0f}" if action == "buy" else "SELL (full position)"
                msg = (
                    f"{emoji} <b>Trade Copied!</b>\n"
                    f"Politician: {politician_tag}\n"
                    f"Action: {label} <b>{ticker}</b>\n"
                    f"Filed: {trade['filed_date'].strftime('%Y-%m-%d')}\n"
                    f"Status: {status}"
                )
            notify.send(msg)

            processed_ids.append(trade_id)
            state["trades_executed"].append({
                "trade_id": trade_id,
                "politician": name,
                "ticker": ticker,
                "action": action,
                "asset_type": asset_type,
                "executed_at": datetime.now().isoformat(),
                "result": result,
            })

    if total_new == 0:
        log.info("No new trades found across all targets.")

    state["processed_trade_ids"] = processed_ids
    state["last_checked"] = datetime.now().isoformat()
    save_state(state)
    log.info("Done.")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
