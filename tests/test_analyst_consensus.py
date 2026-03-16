"""Tests for validation/analyst_consensus.py."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _make_df(tickers: list[str], composite_scores: list[int], analyst_means: list[float]) -> pd.DataFrame:
    """Build a synthetic DataFrame for consensus tests."""
    analyst_inverted = [(6.0 - m) / 4.0 * 100.0 for m in analyst_means]
    return pd.DataFrame({
        "ticker": tickers,
        "composite_score": composite_scores,
        "analyst_mean": analyst_means,
        "analyst_inverted": analyst_inverted,
    })


class TestFindOutliers:
    def test_find_outliers_returns_correct_direction(self):
        """Top delta = we love it; bottom delta = analysts love it."""
        from validation.analyst_consensus import find_outliers

        df = _make_df(
            tickers=["AAPL", "MSFT", "AMZN", "TSLA", "GOOG"],
            composite_scores=[90, 80, 40, 30, 70],
            analyst_means=[3.5, 2.0, 1.2, 1.5, 2.5],
        )

        we_love, analysts_love = find_outliers(df, n=2)

        # AAPL has high composite (90) but poor analyst rating (3.5 → inverted=62.5)
        # delta = 90 - 62.5 = +27.5  →  we love it
        we_love_tickers = we_love["ticker"].tolist()
        analysts_love_tickers = analysts_love["ticker"].tolist()

        assert "AAPL" in we_love_tickers or "TSLA" in we_love_tickers

        # AMZN has high analyst rating (1.2 → inverted=120 capped... well: (6-1.2)/4*100=120)
        # but low composite (40)  → delta = 40 - 120 = -80  → analysts love it
        assert "AMZN" in analysts_love_tickers

    def test_find_outliers_delta_column_present(self):
        """Result DataFrames contain a delta column."""
        from validation.analyst_consensus import find_outliers

        df = _make_df(
            tickers=["AAPL", "MSFT", "JNJ"],
            composite_scores=[80, 60, 50],
            analyst_means=[2.5, 2.0, 3.0],
        )

        we_love, analysts_love = find_outliers(df, n=1)
        assert "delta" in we_love.columns
        assert "delta" in analysts_love.columns

    def test_find_outliers_top_has_highest_delta(self):
        """we_love DataFrame has highest deltas."""
        from validation.analyst_consensus import find_outliers

        df = _make_df(
            tickers=["A", "B", "C", "D"],
            composite_scores=[90, 50, 30, 80],
            analyst_means=[4.0, 2.5, 1.5, 3.0],
        )

        we_love, analysts_love = find_outliers(df, n=2)
        # We love: highest delta values
        assert we_love["delta"].min() >= analysts_love["delta"].max()


class TestComputeCorrelations:
    def test_compute_correlations_with_known_data(self):
        """Perfect positive correlation → pearson ≈ 1.0."""
        from validation.analyst_consensus import compute_correlations

        df = pd.DataFrame({
            "composite_score": [10, 20, 30, 40, 50, 60, 70, 80],
            "analyst_inverted": [10, 20, 30, 40, 50, 60, 70, 80],
        })
        result = compute_correlations(df)

        assert abs(result["pearson"] - 1.0) < 0.001
        assert abs(result["spearman"] - 1.0) < 0.001
        assert result["n"] == 8

    def test_compute_correlations_with_perfect_negative(self):
        """Perfect negative correlation → pearson ≈ -1.0."""
        from validation.analyst_consensus import compute_correlations

        df = pd.DataFrame({
            "composite_score": [80, 70, 60, 50, 40, 30, 20, 10],
            "analyst_inverted": [10, 20, 30, 40, 50, 60, 70, 80],
        })
        result = compute_correlations(df)

        assert abs(result["pearson"] - (-1.0)) < 0.001

    def test_compute_correlations_returns_n(self):
        """Returns correct n count."""
        from validation.analyst_consensus import compute_correlations

        df = _make_df(
            tickers=["A", "B", "C", "D", "E"],
            composite_scores=[70, 60, 55, 45, 50],
            analyst_means=[2.0, 2.5, 3.0, 3.5, 2.8],
        )
        result = compute_correlations(df)
        assert result["n"] == 5

    def test_compute_correlations_handles_small_dataset(self):
        """Returns safe defaults when fewer than 3 data points."""
        from validation.analyst_consensus import compute_correlations

        df = pd.DataFrame({
            "composite_score": [70],
            "analyst_inverted": [60],
        })
        result = compute_correlations(df)
        assert result["pearson"] == 0.0
        assert result["n"] == 1


class TestFetchSp500WithRatings:
    def test_fetch_sp500_skips_tickers_with_no_analyst_data(self):
        """Skips tickers where analyst rating is unavailable."""
        from validation.analyst_consensus import fetch_sp500_with_ratings

        mock_analysis = MagicMock()
        mock_analysis.overall_score = 75

        def mock_analyst_rating(ticker: str) -> float | None:
            ratings = {"AAPL": 2.1, "MSFT": None, "JNJ": 1.8}
            return ratings.get(ticker)

        with (
            patch("validation.analyst_consensus.fetch_analyst_rating", side_effect=mock_analyst_rating),
            patch("validation.analyst_consensus.get_cached_analysis", return_value=mock_analysis),
            patch("validation.analyst_consensus.rate_limited_sleep"),
        ):
            result = fetch_sp500_with_ratings(
                ["AAPL", "MSFT", "JNJ"],
                db_url="sqlite:///./test.db",
                skip_new=True,
                delay=0,
            )

        assert len(result) == 2
        assert "MSFT" not in result["ticker"].tolist()
        assert "AAPL" in result["ticker"].tolist()
        assert "JNJ" in result["ticker"].tolist()

    def test_fetch_sp500_skips_when_no_analysis_and_skip_new(self):
        """When skip_new=True and no cached analysis, ticker is skipped."""
        from validation.analyst_consensus import fetch_sp500_with_ratings

        with (
            patch("validation.analyst_consensus.fetch_analyst_rating", return_value=2.0),
            patch("validation.analyst_consensus.get_cached_analysis", return_value=None),
            patch("validation.analyst_consensus.run_analysis_safe") as mock_run,
            patch("validation.analyst_consensus.rate_limited_sleep"),
        ):
            result = fetch_sp500_with_ratings(
                ["AAPL"],
                db_url="sqlite:///./test.db",
                skip_new=True,
                delay=0,
            )

        # run_analysis_safe should NOT be called when skip_new=True
        mock_run.assert_not_called()
        assert len(result) == 0

    def test_fetch_sp500_includes_analyst_inverted_column(self):
        """Result DataFrame includes analyst_inverted column."""
        from validation.analyst_consensus import fetch_sp500_with_ratings

        mock_analysis = MagicMock()
        mock_analysis.overall_score = 65

        with (
            patch("validation.analyst_consensus.fetch_analyst_rating", return_value=1.0),
            patch("validation.analyst_consensus.get_cached_analysis", return_value=mock_analysis),
            patch("validation.analyst_consensus.rate_limited_sleep"),
        ):
            result = fetch_sp500_with_ratings(
                ["AAPL"],
                db_url="sqlite:///./test.db",
                skip_new=True,
                delay=0,
            )

        assert "analyst_inverted" in result.columns
        # analyst_mean=1.0 → inverted = (6 - 1) / 4 * 100 = 125.0
        assert result.iloc[0]["analyst_inverted"] == pytest.approx(125.0)
