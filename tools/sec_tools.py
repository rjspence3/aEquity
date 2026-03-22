"""SEC EDGAR filing fetcher and section extractor."""

import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

from sec_edgar_downloader import Downloader

logger = logging.getLogger(__name__)

# Matches Item 1A Risk Factors through start of Item 1B / Item 2
_RISK_FACTORS_PATTERN = re.compile(
    r"(?:Item\s*1A[\.\s]*(?:Risk\s*Factors)?)(.*?)(?=Item\s*1B|Item\s*2)",
    re.DOTALL | re.IGNORECASE,
)

# Matches Item 7 MD&A through Item 7A / Item 8.
# The full "Management ... Discussion and Analysis" sequence is required explicitly
# (rather than optional as in the old pattern) to eliminate the double-non-greedy
# ambiguity where two consecutive .*? groups could both match empty strings.
# No \n requirement — _strip_html_tags collapses all whitespace to single spaces.
_MDNA_PATTERN = re.compile(
    r"Item\s+7\.?\s+Management['\u2019]?s?\s+Discussion\s+and\s+Analysis\b(.*?)(?=\bItem\s+7A\b|\bItem\s+8\b)",
    re.DOTALL | re.IGNORECASE,
)

_DOWNLOAD_DIR = Path("./filings_cache")
_MAX_SECTION_CHARS = 200_000  # ~50k tokens — stays within Sonnet's 200k context


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags, decode all HTML entities, collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")  # non-breaking space (&nbsp;) → regular space
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
    max_retries: int = 3,
) -> dict[str, str | None]:
    """
    Download the most recent 10-K for a ticker and extract key sections.

    Returns a dict with keys 'risk_factors' and 'mdna', values are extracted
    text strings or None if the section could not be found.

    Requires SEC_USER_AGENT_EMAIL to be set in settings (EDGAR terms of service).
    """
    from config import settings  # local import to avoid circular dependency at module load

    email = settings.sec_user_agent_email
    if not email:
        raise ValueError(
            "SEC_USER_AGENT_EMAIL is not set. "
            "EDGAR requires a real contact email in the User-Agent header. "
            "Add SEC_USER_AGENT_EMAIL=your-email@example.com to your .env file."
        )

    downloader = Downloader("aEquity", email, _DOWNLOAD_DIR)

    _EDGAR_TIMEOUT_SECS = 120

    for attempt in range(1, max_retries + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(downloader.get, "10-K", ticker, limit=1)
                future.result(timeout=_EDGAR_TIMEOUT_SECS)
            break
        except FuturesTimeoutError:
            logger.error(
                "EDGAR download timed out after %ds for %s (attempt %d/%d)",
                _EDGAR_TIMEOUT_SECS, ticker, attempt, max_retries,
            )
            if attempt == max_retries:
                return {"risk_factors": None, "mdna": None, "filing_date": None}
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
    date_match = re.match(r"(\d{4}-\d{2}-\d{2})", latest.name)
    if date_match:
        filing_date = date_match.group(1)
    else:
        logger.warning("Could not parse filing date from directory name: %s", latest.name)
        filing_date = None

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

    mdna = _extract_section(clean_text, _MDNA_PATTERN)
    # 1 000-char threshold distinguishes real narrative from table-of-contents
    # extractions (which typically run 200-400 chars). Full 10-K MD&A sections
    # are rarely under 2 000 words; anything shorter is almost certainly a TOC hit.
    if mdna is not None and len(mdna) < 1000:
        logger.warning(
            "MD&A extraction for %s appears to be a TOC match, not narrative "
            "(%d chars); ignoring",
            ticker, len(mdna),
        )
        mdna = None

    return {
        "risk_factors": _extract_section(clean_text, _RISK_FACTORS_PATTERN),
        "mdna": mdna,
        "filing_date": filing_date,
    }
