"""
Overnight S&P 500 batch runner.

Iterates through config/sp500_tickers.json, runs the full analysis pipeline
for each ticker, and persists results to SQLite.

Usage:
    python batch.py                    # full S&P 500 run
    python batch.py --tickers AAPL MSFT NVDA   # specific tickers
    python batch.py --limit 20         # first N tickers (smoke test)
    python batch.py --resume           # skip tickers already analysed today
"""

import argparse
import json
import logging
import time
from datetime import date
from pathlib import Path

from config import settings
from db.init import get_latest_analysis, open_db, upsert_analysis
from pipeline import analyze_ticker

logger = logging.getLogger(__name__)

_TICKERS_PATH = Path(__file__).parent / "config" / "sp500_tickers.json"
_INTER_TICKER_SLEEP = 2.0  # seconds between tickers — respects SEC rate limits


def load_tickers() -> list[str]:
    data = json.loads(_TICKERS_PATH.read_text())
    return data["tickers"]


def run_batch(
    tickers: list[str],
    resume: bool = False,
) -> None:
    total = len(tickers)
    succeeded = 0
    failed = 0
    skipped = 0

    with open_db(settings.database_url) as conn:
        for index, ticker in enumerate(tickers, start=1):
            if resume:
                existing = get_latest_analysis(conn, ticker)
                if existing and existing.analysis_date == date.today():
                    logger.info("[%d/%d] %s — skipping (already analysed today)", index, total, ticker)
                    skipped += 1
                    continue

            logger.info("[%d/%d] Analysing %s ...", index, total, ticker)
            try:
                analysis = analyze_ticker(ticker)
                upsert_analysis(conn, analysis)
                succeeded += 1
                logger.info(
                    "[%d/%d] %s — score=%d confidence=%s partial=%s",
                    index, total, ticker,
                    analysis.overall_score,
                    analysis.confidence,
                    analysis.partial,
                )
            except Exception as exc:
                failed += 1
                logger.error("[%d/%d] %s — FAILED: %s", index, total, ticker, exc)

            if index < total:
                time.sleep(_INTER_TICKER_SLEEP)

    logger.info(
        "Batch complete. succeeded=%d failed=%d skipped=%d total=%d",
        succeeded, failed, skipped, total,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="aEquity S&P 500 batch runner")
    parser.add_argument(
        "--tickers", nargs="+", metavar="TICKER",
        help="Analyse specific tickers instead of the full S&P 500 list",
    )
    parser.add_argument(
        "--limit", type=int, metavar="N",
        help="Analyse only the first N tickers (useful for smoke tests)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip tickers that already have a result for today",
    )
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.upper().strip() for t in args.tickers]
    else:
        tickers = load_tickers()

    if args.limit:
        tickers = tickers[: args.limit]

    logger.info(
        "Starting batch run: %d tickers, resume=%s, db=%s",
        len(tickers), args.resume, settings.database_url,
    )
    run_batch(tickers, resume=args.resume)


if __name__ == "__main__":
    main()
