"""Price update job: refresh current prices and check alerts.

Fetches current prices for all actively-monitored watchlist tickers,
fires triggered alerts to the log, and runs watchlist auto-transitions.

Scheduling (cron, market-close weekdays):
    0 20 * * 1-5  /path/to/.venv/bin/python /path/to/jobs/update_prices.py

Or run ad-hoc:
    python jobs/update_prices.py
"""

import logging
import sqlite3

import yfinance as yf

from config import settings
from db.init import open_db
from services.alerts import check_alerts, format_alert_output
from services.watchlist import check_auto_transitions

logger = logging.getLogger(__name__)

# Statuses that represent active interest requiring price monitoring
_ACTIVE_STATUSES = ("screening", "analyzing", "watching", "buying", "owned")


def update_watchlist_prices(conn: sqlite3.Connection) -> dict:
    """
    Refresh current prices for all actively-monitored watchlist tickers.

    Steps:
    1. Fetch tickers in active watchlist statuses
    2. Batch-fetch current prices via yfinance
    3. Update stocks.current_price + price_updated_at
    4. Run check_alerts() and log triggered alerts
    5. Run check_auto_transitions()
    6. Return summary dict
    """
    placeholders = ", ".join("?" * len(_ACTIVE_STATUSES))
    rows = conn.execute(
        f"""
        SELECT DISTINCT s.id AS stock_id, s.ticker
        FROM watchlist w
        JOIN stocks s ON s.id = w.stock_id
        WHERE w.status IN ({placeholders})
        """,
        _ACTIVE_STATUSES,
    ).fetchall()

    if not rows:
        logger.info("No active watchlist tickers to update.")
        return {"updated": 0, "triggered_alerts": [], "auto_transitions": []}

    ticker_to_stock_id: dict[str, int] = {row["ticker"]: row["stock_id"] for row in rows}
    tickers = list(ticker_to_stock_id.keys())
    logger.info("Fetching prices for %d tickers: %s", len(tickers), tickers)

    prices = _fetch_prices_batch(tickers)

    updated_count = 0
    for ticker, price in prices.items():
        if price is None:
            continue
        stock_id = ticker_to_stock_id.get(ticker)
        if stock_id is None:
            continue
        conn.execute(
            """
            UPDATE stocks
            SET current_price = ?,
                price_updated_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (price, stock_id),
        )
        updated_count += 1

    conn.commit()
    logger.info("Updated prices for %d tickers", updated_count)

    triggered_alerts = check_alerts(conn)
    for alert in triggered_alerts:
        logger.warning(format_alert_output(alert))

    auto_transitions = check_auto_transitions(conn)
    for transition in auto_transitions:
        logger.info(
            "Auto-transition [%s]: %s -> %s (price=%.2f, trigger=%s)",
            transition["ticker"],
            transition["from_status"],
            transition["to_status"],
            transition["current_price"],
            transition["trigger"],
        )

    return {
        "updated": updated_count,
        "triggered_alerts": triggered_alerts,
        "auto_transitions": auto_transitions,
    }


def _fetch_prices_batch(tickers: list[str]) -> dict[str, float | None]:
    """Batch-fetch latest prices for a list of tickers via yfinance.

    Returns a dict mapping ticker -> price (or None on failure).
    Falls back to per-ticker fetch when the batch result is missing a ticker.
    """
    prices: dict[str, float | None] = {t: None for t in tickers}

    if not tickers:
        return prices

    try:
        ticker_str = " ".join(tickers)
        data = yf.download(
            tickers=ticker_str,
            period="1d",
            progress=False,
            auto_adjust=True,
        )
        close = data.get("Close")
        if close is not None and not close.empty:
            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        # Single-ticker download returns a Series, not a DataFrame
                        value = close.iloc[-1]
                    else:
                        col = close.get(ticker)
                        value = col.dropna().iloc[-1] if col is not None and not col.dropna().empty else None
                    if value is not None:
                        prices[ticker] = float(value)
                except (KeyError, IndexError, ValueError):
                    logger.warning("Could not extract price for %s from batch data", ticker)
    except Exception:
        logger.warning("Batch yfinance download failed; falling back to per-ticker fetch", exc_info=True)

    # Per-ticker fallback for any ticker still missing a price
    missing = [t for t, p in prices.items() if p is None]
    for ticker in missing:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if price is not None:
                prices[ticker] = float(price)
            else:
                logger.warning("No price found for %s via per-ticker fetch", ticker)
        except Exception:
            logger.warning("Per-ticker fetch failed for %s", ticker, exc_info=True)

    return prices


def main() -> None:
    """CLI entry point."""
    with open_db(settings.database_url) as conn:
        summary = update_watchlist_prices(conn)
        logger.info("Price update complete: %s", summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
