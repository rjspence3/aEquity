"""Tests for validation/_helpers.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestFetchAnalystRating:
    def test_fetch_analyst_rating_returns_none_on_missing(self):
        """Returns None when yfinance info has no recommendationMean."""
        mock_stock = MagicMock()
        mock_stock.info = {"longName": "Apple Inc."}  # no recommendationMean

        with patch("validation._helpers.yf.Ticker", return_value=mock_stock):
            from validation._helpers import fetch_analyst_rating
            result = fetch_analyst_rating("AAPL")

        assert result is None

    def test_fetch_analyst_rating_returns_float_when_present(self):
        """Returns float when recommendationMean is available."""
        mock_stock = MagicMock()
        mock_stock.info = {"recommendationMean": 2.1}

        with patch("validation._helpers.yf.Ticker", return_value=mock_stock):
            from validation._helpers import fetch_analyst_rating
            result = fetch_analyst_rating("AAPL")

        assert result == 2.1

    def test_fetch_analyst_rating_returns_none_on_exception(self):
        """Returns None when yfinance raises an exception."""
        with patch("validation._helpers.yf.Ticker", side_effect=Exception("network error")):
            from validation._helpers import fetch_analyst_rating
            result = fetch_analyst_rating("AAPL")

        assert result is None


class TestRunAnalysisSafe:
    def test_run_analysis_safe_catches_value_error(self):
        """Returns None when analyze_ticker raises ValueError."""
        import validation._helpers as helpers_mod
        original = helpers_mod.analyze_ticker
        try:
            helpers_mod.analyze_ticker = MagicMock(side_effect=ValueError("Ticker not found"))
            from validation._helpers import run_analysis_safe
            result = run_analysis_safe("INVALID")
        finally:
            helpers_mod.analyze_ticker = original

        assert result is None

    def test_run_analysis_safe_catches_generic_exception(self):
        """Returns None when analyze_ticker raises any exception."""
        import validation._helpers as helpers_mod
        original = helpers_mod.analyze_ticker
        try:
            helpers_mod.analyze_ticker = MagicMock(side_effect=RuntimeError("API error"))
            from validation._helpers import run_analysis_safe
            result = run_analysis_safe("AAPL")
        finally:
            helpers_mod.analyze_ticker = original

        assert result is None

    def test_run_analysis_safe_returns_analysis_on_success(self):
        """Returns CompanyAnalysis when analyze_ticker succeeds."""
        mock_analysis = MagicMock()
        mock_analysis.overall_score = 75

        import validation._helpers as helpers_mod
        original = helpers_mod.analyze_ticker
        try:
            helpers_mod.analyze_ticker = MagicMock(return_value=mock_analysis)
            from validation._helpers import run_analysis_safe
            result = run_analysis_safe("AAPL")
        finally:
            helpers_mod.analyze_ticker = original

        assert result is mock_analysis
        assert result.overall_score == 75


class TestEnsureOutputDir:
    def test_ensure_output_dir_creates_directory(self):
        """Creates the output directory if it does not exist and returns a Path that exists."""
        from validation._helpers import ensure_output_dir

        result = ensure_output_dir()

        assert isinstance(result, Path)
        assert result.exists()
        assert result.is_dir()

    def test_ensure_output_dir_returns_path_object(self):
        """Returns a Path object."""
        from validation._helpers import ensure_output_dir
        result = ensure_output_dir()
        assert isinstance(result, Path)


class TestGetCachedAnalysis:
    def test_get_cached_analysis_returns_none_when_missing(self):
        """Returns None when ticker is not in the database."""
        import validation._helpers as helpers_mod

        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        orig_open_db = helpers_mod.open_db
        orig_get_latest = helpers_mod.get_latest_analysis
        try:
            helpers_mod.open_db = MagicMock(return_value=mock_ctx)
            helpers_mod.get_latest_analysis = MagicMock(return_value=None)

            from validation._helpers import get_cached_analysis
            result = get_cached_analysis("AAPL", "sqlite:///./test.db")
        finally:
            helpers_mod.open_db = orig_open_db
            helpers_mod.get_latest_analysis = orig_get_latest

        assert result is None

    def test_get_cached_analysis_returns_analysis_when_found(self):
        """Returns CompanyAnalysis when ticker is found in the database."""
        import validation._helpers as helpers_mod

        mock_analysis = MagicMock()
        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        orig_open_db = helpers_mod.open_db
        orig_get_latest = helpers_mod.get_latest_analysis
        try:
            helpers_mod.open_db = MagicMock(return_value=mock_ctx)
            helpers_mod.get_latest_analysis = MagicMock(return_value=mock_analysis)

            from validation._helpers import get_cached_analysis
            result = get_cached_analysis("AAPL", "sqlite:///./test.db")
        finally:
            helpers_mod.open_db = orig_open_db
            helpers_mod.get_latest_analysis = orig_get_latest

        assert result is mock_analysis

    def test_get_cached_analysis_returns_none_on_db_error(self):
        """Returns None when the database raises an exception."""
        import validation._helpers as helpers_mod

        orig_open_db = helpers_mod.open_db
        try:
            helpers_mod.open_db = MagicMock(side_effect=Exception("DB connection failed"))

            from validation._helpers import get_cached_analysis
            result = get_cached_analysis("AAPL", "sqlite:///./test.db")
        finally:
            helpers_mod.open_db = orig_open_db

        assert result is None
