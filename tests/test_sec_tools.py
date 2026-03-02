"""Unit tests for SEC filing text extraction."""


from tools.sec_tools import (
    _MDNA_PATTERN,
    _RISK_FACTORS_PATTERN,
    _extract_section,
    _strip_html_tags,
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
