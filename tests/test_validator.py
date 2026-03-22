"""Unit tests for input validation."""

import pytest

from tools.validator import validate_ticker, validate_tickers_batch


class TestValidateTicker:
    def test_valid_ticker_uppercase(self):
        assert validate_ticker("AAPL") == "AAPL"

    def test_lowercased_input_is_normalized(self):
        assert validate_ticker("aapl") == "AAPL"

    def test_strips_whitespace(self):
        assert validate_ticker("  MSFT  ") == "MSFT"

    def test_single_char_valid(self):
        assert validate_ticker("F") == "F"

    def test_five_char_valid(self):
        assert validate_ticker("GOOGL") == "GOOGL"

    def test_six_char_raises(self):
        with pytest.raises(ValueError, match="Invalid ticker"):
            validate_ticker("TOOLONG")

    def test_digits_raise(self):
        with pytest.raises(ValueError, match="Invalid ticker"):
            validate_ticker("ABC1")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid ticker"):
            validate_ticker("")

    def test_special_chars_raise(self):
        with pytest.raises(ValueError, match="Invalid ticker"):
            validate_ticker("A.1")  # digit after dot is invalid

    def test_dot_suffix_valid(self):
        assert validate_ticker("BRK.A") == "BRK.A"

    def test_dot_suffix_lowercase_normalized(self):
        assert validate_ticker("brk.a") == "BRK.A"

    def test_double_dot_suffix_raises(self):
        with pytest.raises(ValueError, match="Invalid ticker"):
            validate_ticker("BRK.AB")  # two letters after dot is invalid


class TestValidateBatch:
    def test_valid_batch(self):
        result = validate_tickers_batch(["AAPL", "MSFT", "GOOG"])
        assert result == ["AAPL", "MSFT", "GOOG"]

    def test_exceeds_max_raises(self):
        with pytest.raises(ValueError, match="Batch size"):
            validate_tickers_batch(["AAPL"] * 101, max_batch=100)

    def test_custom_max(self):
        result = validate_tickers_batch(["AAPL", "MSFT"], max_batch=2)
        assert len(result) == 2
