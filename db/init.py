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
