"""SQLite schema initialisation and upsert helpers for aEquity."""

import contextlib
import sqlite3
from collections.abc import Generator
from pathlib import Path

from models import CompanyAnalysis

_CREATE_ANALYSES = """
CREATE TABLE IF NOT EXISTS analyses (
    ticker          TEXT NOT NULL,
    analysis_date   TEXT NOT NULL,   -- ISO-8601 (YYYY-MM-DD)
    company_name    TEXT NOT NULL,
    overall_score   INTEGER NOT NULL,
    confidence      TEXT NOT NULL,
    partial         INTEGER NOT NULL, -- 0 or 1
    json_blob       TEXT NOT NULL,    -- full CompanyAnalysis JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, analysis_date)
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_analyses_date
    ON analyses (analysis_date DESC)
"""

_CREATE_STOCKS = """
CREATE TABLE IF NOT EXISTS stocks (
    id INTEGER PRIMARY KEY,
    ticker TEXT UNIQUE NOT NULL,
    name TEXT,
    sector TEXT,
    industry TEXT,
    market_cap REAL,
    current_price REAL,
    price_updated_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_INDEX_STOCKS_TICKER = """
CREATE INDEX IF NOT EXISTS idx_stocks_ticker ON stocks (ticker)
"""

_CREATE_FINANCIALS = """
CREATE TABLE IF NOT EXISTS financials (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    period_type TEXT NOT NULL DEFAULT 'ttm',
    period_end TEXT,
    roe REAL, roic REAL, roic_v2 REAL, roa REAL, roce REAL,
    operating_margin REAL, net_margin REAL, gross_margin REAL,
    fcf_conversion REAL, fcf_yield REAL, owner_earnings_yield REAL,
    pe_ratio REAL, price_to_book REAL, peg_ratio REAL,
    earnings_yield REAL, ev_fcf REAL,
    net_debt_ebitda REAL, current_ratio REAL, debt_to_equity REAL,
    revenue_growth REAL, eps_growth REAL, fcf_growth REAL, earnings_growth REAL,
    overall_grade TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(stock_id, period_type, period_end)
)
"""

_CREATE_WATCHLIST = """
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER UNIQUE NOT NULL REFERENCES stocks(id),
    status TEXT NOT NULL DEFAULT 'screening',
    must_buy_price REAL,
    compelling_buy_price REAL,
    accumulate_price REAL,
    fair_value_price REAL,
    notes TEXT,
    last_analysis_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_ALERTS = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    alert_type TEXT NOT NULL,
    target_price REAL NOT NULL,
    condition TEXT NOT NULL DEFAULT 'below',
    status TEXT NOT NULL DEFAULT 'active',
    triggered_at TEXT,
    triggered_price REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER UNIQUE NOT NULL REFERENCES stocks(id),
    shares REAL NOT NULL,
    avg_cost_basis REAL NOT NULL,
    total_cost REAL NOT NULL,
    entry_zone TEXT,
    original_thesis TEXT,
    first_purchase_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    stock_id INTEGER NOT NULL REFERENCES stocks(id),
    position_id INTEGER REFERENCES positions(id),
    transaction_type TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL NOT NULL,
    total_amount REAL NOT NULL,
    entry_zone TEXT,
    reason TEXT,
    realized_gain REAL,
    transaction_date TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def db_path_from_url(database_url: str) -> Path:
    """Parse a sqlite:/// URL to a filesystem Path."""
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"Expected sqlite:/// URL, got: {database_url!r}")
    raw = database_url[len("sqlite:///"):]
    return Path(raw)


@contextlib.contextmanager
def open_db(database_url: str) -> Generator[sqlite3.Connection, None, None]:
    """
    Open (and initialise) the SQLite database, yielding a connection.

    WAL mode is enabled so the Streamlit dashboard can read while batch.py writes.
    """
    path = db_path_from_url(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        init_db(conn)
        yield conn
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.execute(_CREATE_ANALYSES)
    conn.execute(_CREATE_INDEX)
    conn.execute(_CREATE_STOCKS)
    conn.execute(_CREATE_INDEX_STOCKS_TICKER)
    conn.execute(_CREATE_FINANCIALS)
    conn.execute(_CREATE_WATCHLIST)
    conn.execute(_CREATE_ALERTS)
    conn.execute(_CREATE_POSITIONS)
    conn.execute(_CREATE_TRANSACTIONS)
    conn.commit()


def upsert_analysis(conn: sqlite3.Connection, analysis: CompanyAnalysis) -> None:
    """Insert or replace a CompanyAnalysis row (keyed on ticker + analysis_date)."""
    conn.execute(
        """
        INSERT OR REPLACE INTO analyses
            (ticker, analysis_date, company_name, overall_score, confidence, partial, json_blob)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            analysis.ticker,
            analysis.analysis_date.isoformat(),
            analysis.company_name,
            analysis.overall_score,
            analysis.confidence,
            int(analysis.partial),
            analysis.model_dump_json(),
        ),
    )
    conn.commit()


def get_latest_analysis(conn: sqlite3.Connection, ticker: str) -> CompanyAnalysis | None:
    """Return the most recent CompanyAnalysis for a ticker, or None."""
    row = conn.execute(
        """
        SELECT json_blob FROM analyses
        WHERE ticker = ?
        ORDER BY analysis_date DESC
        LIMIT 1
        """,
        (ticker.upper(),),
    ).fetchone()
    return CompanyAnalysis.model_validate_json(row["json_blob"]) if row else None


def get_all_latest(conn: sqlite3.Connection) -> list[CompanyAnalysis]:
    """
    Return the most recent CompanyAnalysis for every ticker in the database.
    Used by the Streamlit screener to build the full score table.
    """
    rows = conn.execute(
        """
        SELECT json_blob FROM analyses
        WHERE (ticker, analysis_date) IN (
            SELECT ticker, MAX(analysis_date) FROM analyses GROUP BY ticker
        )
        ORDER BY overall_score DESC
        """,
    ).fetchall()
    return [CompanyAnalysis.model_validate_json(row["json_blob"]) for row in rows]


def upsert_stock(
    conn: sqlite3.Connection,
    ticker: str,
    name: str | None = None,
    current_price: float | None = None,
    **kwargs: object,
) -> int:
    """Insert or update a stock record, return its id."""
    ticker = ticker.upper()
    existing = conn.execute(
        "SELECT id FROM stocks WHERE ticker = ?", (ticker,)
    ).fetchone()

    if existing:
        updates: list[str] = ["updated_at = datetime('now')"]
        params: list[object] = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if current_price is not None:
            updates.append("current_price = ?")
            params.append(current_price)
            updates.append("price_updated_at = datetime('now')")
        for column in ("sector", "industry", "market_cap"):
            if column in kwargs and kwargs[column] is not None:
                updates.append(f"{column} = ?")
                params.append(kwargs[column])
        params.append(ticker)
        conn.execute(
            f"UPDATE stocks SET {', '.join(updates)} WHERE ticker = ?",  # noqa: S608
            params,
        )
        conn.commit()
        return int(existing["id"])

    conn.execute(
        """
        INSERT INTO stocks (ticker, name, sector, industry, market_cap, current_price, price_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? IS NOT NULL THEN datetime('now') ELSE NULL END)
        """,
        (
            ticker,
            name,
            kwargs.get("sector"),
            kwargs.get("industry"),
            kwargs.get("market_cap"),
            current_price,
            current_price,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM stocks WHERE ticker = ?", (ticker,)).fetchone()
    return int(row["id"])


def get_stock_id(conn: sqlite3.Connection, ticker: str) -> int | None:
    """Return the stock id for a ticker, or None."""
    row = conn.execute(
        "SELECT id FROM stocks WHERE ticker = ?", (ticker.upper(),)
    ).fetchone()
    return int(row["id"]) if row else None


def upsert_financial_snapshot(
    conn: sqlite3.Connection, stock_id: int, metrics: dict
) -> None:
    """Insert or replace TTM financials snapshot."""
    period_type = metrics.get("period_type", "ttm")
    period_end = metrics.get("period_end")

    # SQLite treats NULLs as distinct in UNIQUE constraints, so we can't rely on
    # INSERT OR REPLACE when period_end is NULL. Delete first, then insert.
    conn.execute(
        """
        DELETE FROM financials
        WHERE stock_id = ?
          AND period_type = ?
          AND (period_end = ? OR (period_end IS NULL AND ? IS NULL))
        """,
        (stock_id, period_type, period_end, period_end),
    )

    metric_fields = [
        "roe", "roic", "roic_v2", "roa", "roce",
        "operating_margin", "net_margin", "gross_margin",
        "fcf_conversion", "fcf_yield", "owner_earnings_yield",
        "pe_ratio", "price_to_book", "peg_ratio",
        "earnings_yield", "ev_fcf",
        "net_debt_ebitda", "current_ratio", "debt_to_equity",
        "revenue_growth", "eps_growth", "fcf_growth", "earnings_growth",
        "overall_grade",
    ]
    columns = ["stock_id", "period_type", "period_end"] + metric_fields
    values: list[object] = [stock_id, period_type, period_end]
    for field in metric_fields:
        values.append(metrics.get(field))

    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(columns)
    conn.execute(
        f"INSERT INTO financials ({col_list}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
