"""Tests for pipeline LLM and integration functions with mocked API calls."""

import json
from unittest.mock import MagicMock, patch

from pipeline import (
    _assess_moat_and_understandability,
    _call_claude,
    _generate_guru_rationales,
    _generate_pillar_summaries,
)


def _mock_client(response_text: str) -> MagicMock:
    """Create a mock Anthropic client that returns a canned response."""
    client = MagicMock()
    content_block = MagicMock()
    content_block.text = response_text
    client.messages.create.return_value.content = [content_block]
    return client


class TestCallClaude:
    def test_returns_text_response(self):
        client = _mock_client("Hello world")
        result = _call_claude(client, "claude-haiku-4-5-20251001", "sys", "user")
        assert result == "Hello world"

    def test_retries_on_rate_limit(self):
        import anthropic

        client = MagicMock()
        content_block = MagicMock()
        content_block.text = "success"
        # Fail twice with rate limit, then succeed
        client.messages.create.side_effect = [
            anthropic.RateLimitError(
                "rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={},
            ),
            anthropic.RateLimitError(
                "rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={},
            ),
            MagicMock(content=[content_block]),
        ]

        with patch("pipeline.time.sleep"):
            result = _call_claude(client, "model", "sys", "user", retries=3)
        assert result == "success"
        assert client.messages.create.call_count == 3


class TestAssessMoatAndUnderstandability:
    def test_returns_neutral_when_no_text(self):
        client = _mock_client("{}")  # won't be called
        result = _assess_moat_and_understandability(
            client, "AAPL", "Apple", None, None
        )
        assert result["moat_score"] == 50
        assert result["understandability_score"] == 50

    def test_parses_valid_json_response(self):
        payload = {
            "moat_score": 85,
            "moat_evidence": "Strong brand and ecosystem lock-in.",
            "understandability_score": 90,
            "understandability_evidence": "Sells phones and software.",
            "red_flags": ["Competition from Android"],
        }
        client = _mock_client(json.dumps(payload))
        result = _assess_moat_and_understandability(
            client, "AAPL", "Apple", "Risk factors text", "MD&A text"
        )
        assert result["moat_score"] == 85
        assert result["understandability_score"] == 90

    def test_handles_json_in_markdown_fence(self):
        payload = {"moat_score": 70, "understandability_score": 75,
                   "moat_evidence": "e", "understandability_evidence": "e",
                   "red_flags": []}
        response = f"```json\n{json.dumps(payload)}\n```"
        client = _mock_client(response)
        result = _assess_moat_and_understandability(
            client, "AAPL", "Apple", "Risk text", None
        )
        assert result["moat_score"] == 70

    def test_falls_back_on_invalid_json(self):
        client = _mock_client("not valid json at all {{{")
        result = _assess_moat_and_understandability(
            client, "AAPL", "Apple", "Risk text", "MD&A text"
        )
        assert result["moat_score"] == 50
        assert "failed" in str(result.get("moat_evidence", "")).lower()


class TestGenerateGuruRationales:
    def test_returns_rationales_dict(self):
        payload = {
            "Warren Buffett": "Strong moat with high ROIC.",
            "Peter Lynch": "PEG under 1, strong growth.",
            "Ben Graham": "P/B reasonable, conservative.",
            "Aswath Damodaran": "DCF implies margin of safety.",
        }
        client = _mock_client(json.dumps(payload))
        result = _generate_guru_rationales(
            client, "AAPL", "Apple",
            {"Warren Buffett": 80, "Peter Lynch": 75, "Ben Graham": 60, "Aswath Damodaran": 70},
            "ROIC: 20%\nPEG: 0.8",
        )
        assert result["Warren Buffett"] == "Strong moat with high ROIC."

    def test_fallback_on_invalid_json(self):
        client = _mock_client("bad json")
        result = _generate_guru_rationales(
            client, "AAPL", "Apple",
            {"Warren Buffett": 75},
            "metrics",
        )
        assert "Warren Buffett" in result
        assert "75/100" in result["Warren Buffett"]


class TestGeneratePillarSummaries:
    def test_returns_summaries_dict(self):
        payload = {
            "The Engine": "Strong business.",
            "The Moat": "Wide moat.",
            "The Fortress": "Low debt.",
            "Alignment": "Insider-aligned.",
        }
        client = _mock_client(json.dumps(payload))
        result = _generate_pillar_summaries(
            client, "AAPL", "Apple",
            {"The Engine": 80, "The Moat": 85, "The Fortress": 70, "Alignment": 60},
            "ROIC: 20%",
        )
        assert result["The Engine"] == "Strong business."

    def test_fallback_on_invalid_json(self):
        client = _mock_client("bad json")
        result = _generate_pillar_summaries(
            client, "AAPL", "Apple",
            {"The Engine": 80},
            "metrics",
        )
        assert "The Engine" in result
        assert "80/100" in result["The Engine"]
