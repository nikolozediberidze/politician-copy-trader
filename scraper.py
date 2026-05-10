"""
Capitol Trades scraper — fetches recent trades for a politician.
Tries __NEXT_DATA__ JSON extraction first, falls back to HTML parsing.
"""

import re
import json
import hashlib
import logging
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://www.capitoltrades.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.capitoltrades.com/",
}


def get_trades(politician_id: str, days_back: int = 4) -> list[dict]:
    """Return a list of trade dicts filed within the last `days_back` days."""
    url = f"{BASE_URL}/trades"
    params = {"politician": politician_id, "pageSize": 50, "page": 1}

    log.info("Fetching Capitol Trades for politician %s ...", politician_id)
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    trades = _parse_next_data(resp.text)
    if trades:
        log.info("Parsed %d trades via __NEXT_DATA__", len(trades))
    else:
        log.info("__NEXT_DATA__ not found — falling back to HTML parsing")
        trades = _parse_html(resp.text)
        log.info("Parsed %d trades via HTML", len(trades))

    cutoff = datetime.now() - timedelta(days=days_back)
    recent = [t for t in trades if t["filed_date"] >= cutoff]
    log.info("%d trades are within the last %d days", len(recent), days_back)
    return recent


# ---------------------------------------------------------------------------
# Strategy 1: __NEXT_DATA__ JSON embedded by Next.js
# ---------------------------------------------------------------------------

def _parse_next_data(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag or not tag.string:
        return []

    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError:
        return []

    trades_raw = _dig(data, ["props", "pageProps", "trades", "data"]) \
        or _dig(data, ["props", "pageProps", "trades"]) \
        or _dig(data, ["props", "pageProps", "data"]) \
        or []

    if not isinstance(trades_raw, list):
        return []

    results = []
    for item in trades_raw:
        parsed = _parse_next_data_item(item)
        if parsed:
            results.append(parsed)
    return results


def _dig(obj, keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def _parse_next_data_item(item: dict) -> dict | None:
    try:
        ticker = (
            item.get("ticker")
            or _dig(item, ["issuer", "ticker"])
            or item.get("symbol")
            or ""
        ).replace(":US", "").strip().upper()

        if not ticker or len(ticker) > 6:
            return None

        raw_type = (
            item.get("transactionType")
            or item.get("type")
            or item.get("transaction")
            or ""
        ).lower()

        asset_type = (
            item.get("assetType")
            or item.get("asset_type")
            or "stock"
        ).lower()

        filed_str = item.get("filedDate") or item.get("dateRecv") or item.get("filed") or ""
        traded_str = item.get("txDate") or item.get("date") or item.get("traded") or ""

        trade_id = (
            str(item.get("id") or item.get("tradeId") or "")
            or hashlib.md5(f"{ticker}{raw_type}{traded_str}".encode()).hexdigest()[:12]
        )

        return {
            "id": trade_id,
            "ticker": ticker,
            "asset_type": asset_type,
            "action": "buy" if ("buy" in raw_type or "purchase" in raw_type) else "sell",
            "filed_date": _parse_date(filed_str),
            "traded_date": _parse_date(traded_str),
            "amount_low": item.get("amountLow") or 0,
            "amount_high": item.get("amountHigh") or 0,
        }
    except Exception as exc:
        log.debug("Skipping item: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Strategy 2: HTML parsing — find trade detail links and scrape surrounding text
# ---------------------------------------------------------------------------

AMOUNT_RE = re.compile(r"\$[\d,]+[KkMm]?")
DATE_PATTERNS = [
    "%d %b %Y",
    "%b %d, %Y",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
]
TICKER_RE = re.compile(r"\b([A-Z]{1,5}):US\b|\bTicker[:\s]+([A-Z]{1,5})\b")


def _parse_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    trade_links = soup.find_all("a", href=re.compile(r"^/trades/\d+$"))
    seen_ids = set()
    results = []

    for link in trade_links:
        trade_id = link["href"].split("/")[-1]
        if trade_id in seen_ids:
            continue
        seen_ids.add(trade_id)

        # Walk up to the closest container with enough context
        container = link
        for _ in range(6):
            parent = container.parent
            if parent is None:
                break
            container = parent
            text = container.get_text(" ", strip=True)
            if len(text) > 80:
                break

        text = container.get_text(" ", strip=True)

        ticker = _extract_ticker(text)
        if not ticker:
            continue

        action = "sell" if re.search(r"\bsell\b|\bsale\b", text, re.I) else "buy"

        dates = _extract_dates(text)
        filed_date = dates[0] if dates else datetime.now()
        traded_date = dates[1] if len(dates) > 1 else filed_date

        asset_type = "option" if re.search(r"\boption\b|\bcall\b|\bput\b", text, re.I) else "stock"

        results.append({
            "id": trade_id,
            "ticker": ticker,
            "asset_type": asset_type,
            "action": action,
            "filed_date": filed_date,
            "traded_date": traded_date,
            "amount_low": 0,
            "amount_high": 0,
        })

    return results


def _extract_ticker(text: str) -> str:
    m = TICKER_RE.search(text)
    if m:
        return (m.group(1) or m.group(2)).upper()
    # Fallback: look for isolated 1-5 uppercase letter word
    words = text.split()
    for w in words:
        clean = w.strip("$(),.")
        if re.fullmatch(r"[A-Z]{1,5}", clean):
            return clean
    return ""


def _extract_dates(text: str) -> list[datetime]:
    date_re = re.compile(
        r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}"
        r"|\d{4}-\d{2}-\d{2}"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}",
        re.I,
    )
    found = []
    for m in date_re.finditer(text):
        d = _parse_date(m.group())
        if d:
            found.append(d)
    return found


def _parse_date(s: str) -> datetime:
    if not s:
        return datetime.now()
    s = s.strip()
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return datetime.now()
