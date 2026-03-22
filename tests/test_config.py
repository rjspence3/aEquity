"""Tests for config.py — settings and log formatting."""

import logging

from config import RedactingFormatter, Settings


class TestRedactingFormatter:
    def _format_message(self, message: str) -> str:
        formatter = RedactingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=message, args=(), exc_info=None,
        )
        return formatter.format(record)

    def test_redacts_anthropic_api_key(self):
        result = self._format_message("key=sk-ant-api03-abc123XYZ-extra")
        assert "sk-ant" not in result
        assert "[REDACTED]" in result

    def test_redacts_bearer_token(self):
        result = self._format_message("Authorization: Bearer abc123token")
        assert "abc123token" not in result
        assert "[REDACTED]" in result

    def test_leaves_normal_messages_intact(self):
        result = self._format_message("Analysis complete for AAPL")
        assert result == "Analysis complete for AAPL"

    def test_redacts_multiple_secrets_in_one_message(self):
        msg = "key=sk-ant-secret and Bearer mytoken"
        result = self._format_message(msg)
        assert "sk-ant" not in result
        assert "mytoken" not in result
        assert result.count("[REDACTED]") == 2


class TestSettings:
    def test_defaults_are_sane(self):
        # Instantiate with no env file to test defaults
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.anthropic_api_key == ""
        assert settings.sec_user_agent_email == ""
        assert "aequity.db" in settings.database_url
        assert settings.log_level == "INFO"

    def test_no_dead_config_fields(self):
        Settings(_env_file=None)  # type: ignore[call-arg]
        field_names = set(Settings.model_fields.keys())
        assert "sec_api_key" not in field_names
        assert "sec_requests_per_second" not in field_names
        assert "llm_max_retries" not in field_names

    def test_analyze_access_token_defaults_empty(self):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.analyze_access_token == ""

    def test_analyze_access_token_read_from_env(self, monkeypatch):
        monkeypatch.setenv("ANALYZE_ACCESS_TOKEN", "secret-token-123")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.analyze_access_token == "secret-token-123"

    def test_analyze_access_token_gate_logic(self, monkeypatch):
        # Gate is active when token is non-empty, inactive when empty.
        monkeypatch.setenv("ANALYZE_ACCESS_TOKEN", "my-token")
        settings_with_token = Settings(_env_file=None)  # type: ignore[call-arg]
        assert bool(settings_with_token.analyze_access_token) is True

        monkeypatch.delenv("ANALYZE_ACCESS_TOKEN", raising=False)
        settings_without_token = Settings(_env_file=None)  # type: ignore[call-arg]
        assert bool(settings_without_token.analyze_access_token) is False
