"""Unit tests for SEC filing text extraction."""

from concurrent.futures import TimeoutError as FuturesTimeoutError
from unittest.mock import MagicMock, patch

from tools.sec_tools import (
    _MDNA_PATTERN,
    _RISK_FACTORS_PATTERN,
    _extract_section,
    _strip_html_tags,
    fetch_10k_sections,
)


class TestStripHtmlTags:
    def test_removes_simple_tags(self):
        assert _strip_html_tags("<b>Hello</b>") == "Hello"

    def test_replaces_nbsp(self):
        result = _strip_html_tags("a&nbsp;b")
        assert result == "a b"

    def test_collapses_whitespace(self):
        result = _strip_html_tags("a   b\t\tc")
        assert result == "a b c"

    def test_preserves_text_content(self):
        result = _strip_html_tags("<p>Risk Factors</p><p>Some text.</p>")
        assert "Risk Factors" in result
        assert "Some text." in result


class TestSectionExtraction:
    _SAMPLE_FILING = """
    ITEM 1A. RISK FACTORS

    Our business is subject to numerous risks including competition,
    regulation, and technology changes.

    ITEM 1B. UNRESOLVED STAFF COMMENTS

    None.

    ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS

    Revenue increased 12% year-over-year to $100 billion.
    Gross margin improved to 43%.

    ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES

    Interest rate risk is managed through...
    """

    def test_extracts_risk_factors(self):
        result = _extract_section(self._SAMPLE_FILING, _RISK_FACTORS_PATTERN)
        assert result is not None
        assert "competition" in result.lower() or "regulation" in result.lower()

    def test_extracts_mdna(self):
        result = _extract_section(self._SAMPLE_FILING, _MDNA_PATTERN)
        assert result is not None
        assert "Revenue" in result or "revenue" in result

    def test_returns_none_when_section_missing(self):
        result = _extract_section("No relevant content here.", _RISK_FACTORS_PATTERN)
        assert result is None

    def test_truncates_to_max_length(self):
        long_text = "Item 1A Risk Factors " + ("x " * 200_000) + " Item 1B"
        result = _extract_section(long_text, _RISK_FACTORS_PATTERN)
        # Should be truncated
        assert result is not None
        assert len(result) <= 200_000


class TestFetch10kSectionsTimeout:
    """Test that EDGAR download timeouts degrade gracefully."""

    def test_timeout_returns_none_sections(self, monkeypatch):
        """A FuturesTimeoutError on all retries should return None for both sections."""
        monkeypatch.setenv("SEC_USER_AGENT_EMAIL", "test@example.com")

        mock_future = MagicMock()
        mock_future.result.side_effect = FuturesTimeoutError()

        mock_executor = MagicMock()
        mock_executor.__enter__ = MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = MagicMock(return_value=False)
        mock_executor.submit.return_value = mock_future

        with patch("tools.sec_tools.ThreadPoolExecutor", return_value=mock_executor):
            result = fetch_10k_sections("AAPL", max_retries=1)

        assert result["risk_factors"] is None
        assert result["mdna"] is None
        assert result.get("filing_date") is None

    def test_timeout_retries_before_giving_up(self, monkeypatch):
        """With max_retries=3 and all timeouts, executor.submit is called 3 times."""
        monkeypatch.setenv("SEC_USER_AGENT_EMAIL", "test@example.com")

        mock_future = MagicMock()
        mock_future.result.side_effect = FuturesTimeoutError()

        mock_executor = MagicMock()
        mock_executor.__enter__ = MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = MagicMock(return_value=False)
        mock_executor.submit.return_value = mock_future

        with patch("tools.sec_tools.ThreadPoolExecutor", return_value=mock_executor):
            fetch_10k_sections("MSFT", max_retries=3)

        assert mock_executor.submit.call_count == 3
