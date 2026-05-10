"""
Alpaca paper trading wrapper.
Uses alpaca-py SDK (TradingClient).
"""

import logging
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

log = logging.getLogger(__name__)


def make_client(api_key: str, api_secret: str) -> TradingClient:
    return TradingClient(api_key, api_secret, paper=True)


def is_market_open(client: TradingClient) -> bool:
    """Return True if the US stock market is currently open."""
    clock = client.get_clock()
    log.info("Market is %s. Next open: %s", "OPEN" if clock.is_open else "CLOSED", clock.next_open)
    return clock.is_open


def get_account_summary(client: TradingClient) -> dict:
    acct = client.get_account()
    return {
        "equity": float(acct.equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
    }


def get_position(client: TradingClient, ticker: str) -> float:
    """Return quantity held, or 0 if no position."""
    try:
        pos = client.get_open_position(ticker)
        return float(pos.qty)
    except Exception:
        return 0.0


def buy(client: TradingClient, ticker: str, amount_usd: float, dry_run: bool = False) -> dict:
    """Submit a notional buy order for `amount_usd` dollars worth of `ticker`."""
    log.info("BUY %s  $%.2f%s", ticker, amount_usd, "  [DRY RUN]" if dry_run else "")
    if dry_run:
        return {"status": "dry_run", "ticker": ticker, "notional": amount_usd, "side": "buy"}

    order = MarketOrderRequest(
        symbol=ticker,
        notional=round(amount_usd, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    result = client.submit_order(order)
    log.info("Order submitted: id=%s status=%s", result.id, result.status)
    return {"status": str(result.status), "id": str(result.id), "ticker": ticker, "side": "buy"}


def sell_position(client: TradingClient, ticker: str, dry_run: bool = False) -> dict:
    """Close the entire position in `ticker` if one exists."""
    qty = get_position(client, ticker)
    if qty <= 0:
        log.info("SELL %s skipped — no position held", ticker)
        return {"status": "skipped", "ticker": ticker, "reason": "no position"}

    log.info("SELL %s  qty=%.4f%s", ticker, qty, "  [DRY RUN]" if dry_run else "")
    if dry_run:
        return {"status": "dry_run", "ticker": ticker, "qty": qty, "side": "sell"}

    result = client.close_position(ticker)
    log.info("Position closed: id=%s status=%s", result.id, result.status)
    return {"status": str(result.status), "id": str(result.id), "ticker": ticker, "side": "sell"}
