"""Input validation utilities."""

import re

TICKER_PATTERN = re.compile(r"^[A-Z]{1,6}(\.[A-Z])?$")


def validate_ticker(ticker: str) -> str:
    """Sanitize and validate a stock ticker symbol."""
    ticker = ticker.upper().strip()
    if not TICKER_PATTERN.match(ticker):
        raise ValueError(f"Invalid ticker format: {ticker!r}")
    return ticker


def validate_tickers_batch(tickers: list[str], max_batch: int = 100) -> list[str]:
    """Validate a batch of tickers with an upper size limit."""
    if len(tickers) > max_batch:
        raise ValueError(f"Batch size {len(tickers)} exceeds max {max_batch}")
    return [validate_ticker(t) for t in tickers]
