"""SEC EDGAR filing fetcher and section extractor."""

import logging
import re
import time
from pathlib import Path

from sec_edgar_downloader import Downloader

logger = logging.getLogger(__name__)

# Matches Item 1A Risk Factors through start of Item 1B / Item 2
_RISK_FACTORS_PATTERN = re.compile(
    r"(?:Item\s*1A[\.\s]*(?:Risk\s*Factors)?)(.*?)(?=Item\s*1B|Item\s*2)",
    re.DOTALL | re.IGNORECASE,
)

# Matches Item 7 MD&A through Item 7A / Item 8
_MDNA_PATTERN = re.compile(
    r"(?:Item\s*7[\.\s]*(?:Management['\u2019]?s\s*Discussion)?.*?)(.*?)(?=Item\s*7A|Item\s*8)",
    re.DOTALL | re.IGNORECASE,
)

_DOWNLOAD_DIR = Path("./filings_cache")
_MAX_SECTION_CHARS = 200_000  # ~50k tokens — stays within Sonnet's 200k context


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags, collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_section(text: str, pattern: re.Pattern) -> str | None:
    """Extract a section from filing text using the provided regex pattern."""
    match = pattern.search(text)
    if not match:
        return None
    extracted = match.group(1).strip()
    return extracted[:_MAX_SECTION_CHARS] if extracted else None


def fetch_10k_sections(
    ticker: str,
    user_agent_email: str = "research@aequity.local",
    max_retries: int = 3,
) -> dict[str, str | None]:
    """
    Download the most recent 10-K for a ticker and extract key sections.

    Returns a dict with keys 'risk_factors' and 'mdna', values are extracted
    text strings or None if the section could not be found.
    """
    downloader = Downloader("aEquity", user_agent_email, _DOWNLOAD_DIR)

    for attempt in range(1, max_retries + 1):
        try:
            downloader.get("10-K", ticker, limit=1)
            break
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning(
                "Download attempt %d/%d failed for %s: %s — retrying in %ds",
                attempt, max_retries, ticker, exc, wait,
            )
            if attempt == max_retries:
                logger.error("All %d download attempts failed for %s", max_retries, ticker)
                return {"risk_factors": None, "mdna": None, "filing_date": None}
            time.sleep(wait)

    # Find the downloaded filing directory
    filing_dir = _DOWNLOAD_DIR / "sec-edgar-filings" / ticker / "10-K"
    if not filing_dir.exists():
        logger.warning("Filing directory not found for %s", ticker)
        return {"risk_factors": None, "mdna": None, "filing_date": None}

    # Get the most recent filing subdirectory
    subdirs = sorted(filing_dir.iterdir(), reverse=True)
    if not subdirs:
        return {"risk_factors": None, "mdna": None, "filing_date": None}

    latest = subdirs[0]
    filing_date = latest.name[:10] if len(latest.name) >= 10 else None

    # Find the primary document (prefer .htm/.html, fall back to any text)
    filing_text = ""
    for suffix in [".htm", ".html", ".txt"]:
        candidates = list(latest.glob(f"*{suffix}"))
        if candidates:
            # Prefer the largest file (most likely the full 10-K)
            primary = max(candidates, key=lambda p: p.stat().st_size)
            try:
                filing_text = primary.read_text(encoding="utf-8", errors="replace")
                break
            except OSError as exc:
                logger.warning("Could not read %s: %s", primary, exc)

    if not filing_text:
        logger.warning("No readable filing found for %s", ticker)
        return {"risk_factors": None, "mdna": None, "filing_date": filing_date}

    clean_text = _strip_html_tags(filing_text)

    return {
        "risk_factors": _extract_section(clean_text, _RISK_FACTORS_PATTERN),
        "mdna": _extract_section(clean_text, _MDNA_PATTERN),
        "filing_date": filing_date,
    }
