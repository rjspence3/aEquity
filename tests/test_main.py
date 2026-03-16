"""Tests for the main.py CLI entry point."""

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from main import main


def _make_analysis_result():
    """Return a minimal mock CompanyAnalysis-like object."""
    result = MagicMock()
    result.company_name = "Apple Inc."
    result.ticker = "AAPL"
    result.overall_score = 72
    result.confidence = "high"
    result.filing_date = "2024-09-30"
    result.pillars = []
    result.gurus = []
    result.errors = []
    result.model_dump.return_value = {"ticker": "AAPL", "overall_score": 72}
    return result


class TestMainCLI:
    def test_help_exits_cleanly(self):
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["main.py", "--help"]):
                main()
        assert exc_info.value.code == 0

    def test_successful_run_prints_output(self, capsys):
        result = _make_analysis_result()
        with patch("main.analyze_ticker", return_value=result):
            with patch("sys.argv", ["main.py", "AAPL"]):
                with patch("builtins.open", MagicMock()):
                    main()

        captured = capsys.readouterr()
        assert "Apple Inc." in captured.out
        assert "72/100" in captured.out

    def test_value_error_exits_nonzero(self, capsys):
        with patch("main.analyze_ticker", side_effect=ValueError("Ticker ZZZZ not found")):
            with patch("sys.argv", ["main.py", "ZZZZ"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Ticker ZZZZ not found" in captured.err

    def test_auth_error_shows_api_key_hint(self, capsys):
        auth_error = anthropic.AuthenticationError(
            "invalid api key",
            response=MagicMock(status_code=401, headers={}),
            body={},
        )
        with patch("main.analyze_ticker", side_effect=auth_error):
            with patch("sys.argv", ["main.py", "AAPL"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ANTHROPIC_API_KEY" in captured.err

    def test_default_ticker_is_aapl(self, capsys):
        result = _make_analysis_result()
        with patch("main.analyze_ticker", return_value=result) as mock_analyze:
            with patch("sys.argv", ["main.py"]):
                with patch("builtins.open", MagicMock()):
                    main()
        mock_analyze.assert_called_once_with("AAPL")
