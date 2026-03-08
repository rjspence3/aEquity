"""
Fetch the current S&P 500 constituent list from Wikipedia and write
config/sp500_tickers.json.  Run quarterly to keep the list current.

Usage:
    python scripts/refresh_sp500.py
"""

import json
import sys
from datetime import date
from pathlib import Path

import io

import pandas as pd
import requests

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
OUTPUT_PATH = Path(__file__).parent.parent / "config" / "sp500_tickers.json"

_HEADERS = {"User-Agent": "aEquity/1.0 (research tool; not scraping at scale)"}


def fetch_sp500_tickers() -> list[str]:
    response = requests.get(WIKIPEDIA_URL, headers=_HEADERS, timeout=15)
    response.raise_for_status()
    tables = pd.read_html(io.StringIO(response.text))
    # First table on the page is the constituent list; "Symbol" column has tickers.
    constituents = tables[0]
    tickers = constituents["Symbol"].str.replace(".", "-", regex=False).tolist()
    return sorted(tickers)


def main() -> None:
    print("Fetching S&P 500 constituents from Wikipedia...")
    try:
        tickers = fetch_sp500_tickers()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "updated": date.today().isoformat(),
        "source": "Wikipedia — List of S&P 500 companies (refreshed quarterly)",
        "count": len(tickers),
        "tickers": tickers,
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {len(tickers)} tickers to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
