"""Application configuration loaded from environment variables."""

import logging
import re

from pydantic_settings import BaseSettings

REDACT_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9\-_]+"),
    re.compile(r"Bearer [a-zA-Z0-9\-_]+"),
]


class RedactingFormatter(logging.Formatter):
    """Log formatter that redacts secrets from log output."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for pattern in REDACT_PATTERNS:
            message = pattern.sub("[REDACTED]", message)
        return message


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    sec_user_agent_email: str = ""
    database_url: str = "sqlite:///./db/aequity.db"
    log_level: str = "INFO"
    # When set, the Analyze tab requires this token before running analyses.
    # Prevents unbounded API spend on the public Railway deployment.
    # Leave empty to rely on the session-state rate limiter only (local dev).
    analyze_access_token: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# Configure root logger
_handler = logging.StreamHandler()
_handler.setFormatter(
    RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=[_handler],
)
