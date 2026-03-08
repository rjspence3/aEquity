"""Tests for batch.py — mocks analyze_ticker and the DB layer."""

import sqlite3
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from batch import load_tickers, run_batch
from db.init import init_db, get_latest_analysis, upsert_analysis
from models import CompanyAnalysis, GuruScorecard, MetricDrillDown, PillarAnalysis


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _metric() -> MetricDrillDown:
    return MetricDrillDown(
        metric_name="ROIC", raw_value=18.0, normalized_score=80,
        source="calculated", evidence="ROIC=18%", confidence="high",
    )


def _pillar(name: str = "The Engine") -> PillarAnalysis:
    return PillarAnalysis(
        pillar_name=name,  # type: ignore[arg-type]
        score=75, metrics=[_metric()], summary="Good.", red_flags=[],
    )


def _guru(name: str = "Warren Buffett") -> GuruScorecard:
    return GuruScorecard(
        guru_name=name,  # type: ignore[arg-type]
        score=72, verdict="Buy", rationale="Strong.", key_metrics=[_metric()],
    )


def _analysis(ticker: str, score: int = 70, today: bool = True) -> CompanyAnalysis:
    return CompanyAnalysis(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        analysis_date=date.today() if today else date(2025, 1, 1),
        filing_date=date(2024, 11, 1),
        filing_type="10-K",
        pillars=[_pillar("The Engine"), _pillar("The Moat"), _pillar("The Fortress"), _pillar("Alignment")],
        gurus=[_guru("Warren Buffett"), _guru("Peter Lynch"), _guru("Ben Graham"), _guru("Aswath Damodaran")],
        overall_score=score,
        confidence="high",
    )


@pytest.fixture()
def mem_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


# ── load_tickers ──────────────────────────────────────────────────────────────

def test_load_tickers_returns_list() -> None:
    tickers = load_tickers()
    assert isinstance(tickers, list)
    assert len(tickers) > 100
    assert "AAPL" in tickers


def test_load_tickers_are_uppercase_strings() -> None:
    tickers = load_tickers()
    assert all(isinstance(t, str) for t in tickers)
    assert all(t == t.upper() for t in tickers)


# ── run_batch ─────────────────────────────────────────────────────────────────

def test_run_batch_calls_analyze_for_each_ticker(mem_conn: sqlite3.Connection) -> None:
    tickers = ["AAPL", "MSFT", "NVDA"]

    with (
        patch("batch.analyze_ticker", side_effect=[_analysis(t) for t in tickers]) as mock_analyze,
        patch("batch.open_db") as mock_open_db,
        patch("batch.upsert_analysis") as mock_upsert,
        patch("batch.get_latest_analysis", return_value=None),
        patch("batch.time.sleep"),
    ):
        mock_open_db.return_value.__enter__ = MagicMock(return_value=mem_conn)
        mock_open_db.return_value.__exit__ = MagicMock(return_value=False)

        run_batch(tickers)

    assert mock_analyze.call_count == 3
    assert mock_upsert.call_count == 3


def test_run_batch_persists_results(mem_conn: sqlite3.Connection) -> None:
    tickers = ["AAPL", "MSFT"]

    with (
        patch("batch.analyze_ticker", side_effect=[_analysis(t) for t in tickers]),
        patch("batch.open_db") as mock_open_db,
        patch("batch.time.sleep"),
    ):
        mock_open_db.return_value.__enter__ = MagicMock(return_value=mem_conn)
        mock_open_db.return_value.__exit__ = MagicMock(return_value=False)

        run_batch(tickers)

    assert get_latest_analysis(mem_conn, "AAPL") is not None
    assert get_latest_analysis(mem_conn, "MSFT") is not None


def test_run_batch_continues_after_failed_ticker(mem_conn: sqlite3.Connection) -> None:
    def fail_on_msft(ticker: str) -> CompanyAnalysis:
        if ticker == "MSFT":
            raise RuntimeError("simulated failure")
        return _analysis(ticker)

    tickers = ["AAPL", "MSFT", "NVDA"]

    with (
        patch("batch.analyze_ticker", side_effect=fail_on_msft),
        patch("batch.open_db") as mock_open_db,
        patch("batch.time.sleep"),
    ):
        mock_open_db.return_value.__enter__ = MagicMock(return_value=mem_conn)
        mock_open_db.return_value.__exit__ = MagicMock(return_value=False)

        run_batch(tickers)  # should not raise

    assert get_latest_analysis(mem_conn, "AAPL") is not None
    assert get_latest_analysis(mem_conn, "MSFT") is None
    assert get_latest_analysis(mem_conn, "NVDA") is not None


def test_run_batch_resume_skips_already_analysed_today(mem_conn: sqlite3.Connection) -> None:
    upsert_analysis(mem_conn, _analysis("AAPL", today=True))

    with (
        patch("batch.analyze_ticker") as mock_analyze,
        patch("batch.open_db") as mock_open_db,
        patch("batch.time.sleep"),
    ):
        mock_open_db.return_value.__enter__ = MagicMock(return_value=mem_conn)
        mock_open_db.return_value.__exit__ = MagicMock(return_value=False)

        run_batch(["AAPL"], resume=True)

    mock_analyze.assert_not_called()


def test_run_batch_resume_reruns_stale_ticker(mem_conn: sqlite3.Connection) -> None:
    upsert_analysis(mem_conn, _analysis("AAPL", today=False))  # yesterday

    with (
        patch("batch.analyze_ticker", return_value=_analysis("AAPL")) as mock_analyze,
        patch("batch.open_db") as mock_open_db,
        patch("batch.time.sleep"),
    ):
        mock_open_db.return_value.__enter__ = MagicMock(return_value=mem_conn)
        mock_open_db.return_value.__exit__ = MagicMock(return_value=False)

        run_batch(["AAPL"], resume=True)

    mock_analyze.assert_called_once_with("AAPL")


def test_run_batch_sleeps_between_tickers() -> None:
    tickers = ["AAPL", "MSFT", "NVDA"]

    with (
        patch("batch.analyze_ticker", side_effect=[_analysis(t) for t in tickers]),
        patch("batch.open_db") as mock_open_db,
        patch("batch.time.sleep") as mock_sleep,
    ):
        mock_open_db.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_open_db.return_value.__exit__ = MagicMock(return_value=False)

        run_batch(tickers)

    # sleeps between tickers but not after the last one
    assert mock_sleep.call_count == len(tickers) - 1
