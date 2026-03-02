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
    sec_api_key: str = ""
    database_url: str = "sqlite:///./db/aequity.db"
    sec_requests_per_second: int = 10
    llm_max_retries: int = 3
    log_level: str = "INFO"

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
