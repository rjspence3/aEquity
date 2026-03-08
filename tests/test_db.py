"""Unit tests for db/init.py — schema, upsert, and query helpers."""

import sqlite3
from datetime import date

import pytest

from pathlib import Path

from db.init import (
    get_all_latest,
    get_latest_analysis,
    init_db,
    open_db,
    upsert_analysis,
    db_path_from_url,
)
from models import CompanyAnalysis, GuruScorecard, MetricDrillDown, PillarAnalysis


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _metric() -> MetricDrillDown:
    return MetricDrillDown(
        metric_name="ROIC",
        raw_value=18.5,
        normalized_score=89,
        source="calculated",
        evidence="ROIC = 18.5%",
        confidence="high",
    )


def _pillar(name: str = "The Engine", score: int = 75) -> PillarAnalysis:
    return PillarAnalysis(
        pillar_name=name,  # type: ignore[arg-type]
        score=score,
        metrics=[_metric()],
        summary="Summary.",
        red_flags=[],
    )


def _guru(name: str = "Warren Buffett", score: int = 72) -> GuruScorecard:
    return GuruScorecard(
        guru_name=name,  # type: ignore[arg-type]
        score=score,
        verdict="Buy",
        rationale="Strong moat.",
        key_metrics=[_metric()],
    )


def _analysis(ticker: str = "AAPL", overall_score: int = 74, analysis_date: date | None = None) -> CompanyAnalysis:
    return CompanyAnalysis(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        analysis_date=analysis_date or date(2026, 3, 1),
        filing_date=date(2025, 11, 1),
        filing_type="10-K",
        pillars=[_pillar("The Engine"), _pillar("The Moat", 60), _pillar("The Fortress", 80), _pillar("Alignment", 70)],
        gurus=[_guru("Warren Buffett"), _guru("Peter Lynch", 65), _guru("Ben Graham", 55), _guru("Aswath Damodaran", 70)],
        overall_score=overall_score,
        confidence="high",
    )


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory SQLite connection with schema initialised."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    init_db(c)
    yield c
    c.close()


# ── db_path_from_url ──────────────────────────────────────────────────────────

def test_db_path_from_url_relative() -> None:
    path = db_path_from_url("sqlite:///./db/aequity.db")
    assert path == Path("./db/aequity.db")  # Path normalises away the leading ./


def test_db_path_from_url_absolute() -> None:
    path = db_path_from_url("sqlite:////tmp/test.db")
    assert str(path) == "/tmp/test.db"


def test_db_path_from_url_invalid() -> None:
    with pytest.raises(ValueError, match="sqlite:///"):
        db_path_from_url("postgresql://localhost/aequity")


# ── init_db ───────────────────────────────────────────────────────────────────

def test_init_db_creates_table(conn: sqlite3.Connection) -> None:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {row["name"] for row in tables}
    assert "analyses" in names


def test_init_db_idempotent(conn: sqlite3.Connection) -> None:
    init_db(conn)  # second call should not raise
    init_db(conn)


# ── upsert_analysis ───────────────────────────────────────────────────────────

def test_upsert_inserts_row(conn: sqlite3.Connection) -> None:
    upsert_analysis(conn, _analysis())
    count = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    assert count == 1


def test_upsert_stores_correct_columns(conn: sqlite3.Connection) -> None:
    a = _analysis(ticker="MSFT", overall_score=82)
    upsert_analysis(conn, a)
    row = conn.execute("SELECT * FROM analyses WHERE ticker='MSFT'").fetchone()
    assert row["ticker"] == "MSFT"
    assert row["overall_score"] == 82
    assert row["confidence"] == "high"
    assert row["partial"] == 0
    assert row["company_name"] == "MSFT Inc."
    assert row["analysis_date"] == "2026-03-01"


def test_upsert_replaces_on_same_key(conn: sqlite3.Connection) -> None:
    upsert_analysis(conn, _analysis(ticker="AAPL", overall_score=60))
    upsert_analysis(conn, _analysis(ticker="AAPL", overall_score=75))  # same date
    count = conn.execute("SELECT COUNT(*) FROM analyses WHERE ticker='AAPL'").fetchone()[0]
    row = conn.execute("SELECT overall_score FROM analyses WHERE ticker='AAPL'").fetchone()
    assert count == 1
    assert row["overall_score"] == 75


def test_upsert_multiple_dates_kept(conn: sqlite3.Connection) -> None:
    upsert_analysis(conn, _analysis(ticker="AAPL", analysis_date=date(2026, 1, 1)))
    upsert_analysis(conn, _analysis(ticker="AAPL", analysis_date=date(2026, 3, 1)))
    count = conn.execute("SELECT COUNT(*) FROM analyses WHERE ticker='AAPL'").fetchone()[0]
    assert count == 2


# ── get_latest_analysis ───────────────────────────────────────────────────────

def test_get_latest_returns_none_for_unknown_ticker(conn: sqlite3.Connection) -> None:
    assert get_latest_analysis(conn, "ZZZZ") is None


def test_get_latest_returns_most_recent(conn: sqlite3.Connection) -> None:
    upsert_analysis(conn, _analysis(ticker="AAPL", overall_score=60, analysis_date=date(2026, 1, 1)))
    upsert_analysis(conn, _analysis(ticker="AAPL", overall_score=80, analysis_date=date(2026, 3, 1)))
    result = get_latest_analysis(conn, "AAPL")
    assert result is not None
    assert result.overall_score == 80


def test_get_latest_returns_company_analysis_type(conn: sqlite3.Connection) -> None:
    upsert_analysis(conn, _analysis())
    result = get_latest_analysis(conn, "AAPL")
    assert isinstance(result, CompanyAnalysis)
    assert result.ticker == "AAPL"


# ── get_all_latest ────────────────────────────────────────────────────────────

def test_get_all_latest_empty(conn: sqlite3.Connection) -> None:
    assert get_all_latest(conn) == []


def test_get_all_latest_one_per_ticker(conn: sqlite3.Connection) -> None:
    upsert_analysis(conn, _analysis("AAPL", analysis_date=date(2026, 1, 1)))
    upsert_analysis(conn, _analysis("AAPL", analysis_date=date(2026, 3, 1)))
    upsert_analysis(conn, _analysis("MSFT", analysis_date=date(2026, 3, 1)))
    results = get_all_latest(conn)
    tickers = [r.ticker for r in results]
    assert len(tickers) == 2
    assert set(tickers) == {"AAPL", "MSFT"}


def test_get_all_latest_ordered_by_score(conn: sqlite3.Connection) -> None:
    upsert_analysis(conn, _analysis("AAPL", overall_score=50))
    upsert_analysis(conn, _analysis("MSFT", overall_score=90))
    upsert_analysis(conn, _analysis("NVDA", overall_score=70))
    results = get_all_latest(conn)
    scores = [r.overall_score for r in results]
    assert scores == sorted(scores, reverse=True)


# ── open_db ───────────────────────────────────────────────────────────────────

def test_open_db_creates_file(tmp_path: pytest.TempPathFactory) -> None:
    db_file = tmp_path / "test.db"
    url = f"sqlite:///{db_file}"
    with open_db(url) as conn:
        upsert_analysis(conn, _analysis())
    assert db_file.exists()
