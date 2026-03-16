"""Shared utilities used by all validation scripts."""

import logging
import time
from pathlib import Path

import yfinance as yf

from db.init import get_latest_analysis, open_db
from pipeline import analyze_ticker

logger = logging.getLogger(__name__)

# Bundled static fallback list of ~480 S&P 500 tickers (used when Wikipedia is unreachable).
_STATIC_SP500 = [
    "A", "AAL", "AAP", "AAPL", "ABBV", "ABC", "ABMD", "ABT", "ACN", "ADBE",
    "ADI", "ADM", "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIZ",
    "AJG", "AKAM", "ALB", "ALGN", "ALK", "ALL", "ALLE", "AMAT", "AMCR", "AMD",
    "AME", "AMGN", "AMP", "AMT", "AMZN", "ANET", "ANSS", "AON", "AOS", "APA",
    "APD", "APH", "APTV", "ARE", "ATO", "ATVI", "AVB", "AVGO", "AVY", "AWK",
    "AXP", "AZO", "BA", "BAC", "BALL", "BAX", "BBWI", "BBY", "BDX", "BEN",
    "BG", "BIIB", "BIO", "BK", "BKNG", "BKR", "BLK", "BMY", "BR", "BSX",
    "BWA", "BXP", "C", "CAG", "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE",
    "CCI", "CCL", "CDAY", "CDNS", "CDW", "CE", "CEG", "CF", "CFG", "CHD",
    "CHRW", "CHTR", "CI", "CINF", "CL", "CLX", "CMA", "CMCSA", "CME", "CMG",
    "CMI", "CMS", "CNC", "CNP", "COF", "COO", "COP", "COST", "CPB", "CPRT",
    "CPT", "CRL", "CRM", "CSCO", "CSX", "CTAS", "CTLT", "CTRA", "CTSH", "CTVA",
    "CVS", "CVX", "CZR", "D", "DAL", "DD", "DE", "DFS", "DG", "DGX",
    "DHI", "DHR", "DIS", "DISH", "DLR", "DLTR", "DOV", "DOW", "DPZ", "DRI",
    "DTE", "DUK", "DVA", "DVN", "DXC", "DXCM", "EA", "EBAY", "ECL", "ED",
    "EFX", "EIX", "EL", "EMN", "EMR", "ENPH", "EOG", "EPAM", "EQIX", "EQR",
    "EQT", "ES", "ESS", "ETN", "ETR", "ETSY", "EVRG", "EW", "EXC", "EXPD",
    "EXPE", "EXR", "F", "FANG", "FAST", "FBHS", "FCX", "FDS", "FE", "FFIV",
    "FIS", "FISV", "FITB", "FLT", "FMC", "FOX", "FOXA", "FRC", "FRT", "FTNT",
    "FTV", "GD", "GE", "GEHC", "GEN", "GILD", "GIS", "GL", "GLW", "GM",
    "GNRC", "GOOG", "GOOGL", "GPC", "GPN", "GRMN", "GS", "GWW", "HAL", "HAS",
    "HBAN", "HCA", "HD", "HES", "HIG", "HII", "HLT", "HOLX", "HON", "HPE",
    "HPQ", "HRL", "HSIC", "HST", "HSY", "HUM", "HWM", "IBM", "ICE", "IDXX",
    "IEX", "IFF", "ILMN", "INCY", "INTC", "INTU", "INVH", "IP", "IPG", "IQV",
    "IR", "IRM", "ISRG", "IT", "ITW", "IVZ", "J", "JBHT", "JCI", "JKHY",
    "JNJ", "JNPR", "JPM", "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KLAC",
    "KMB", "KMI", "KMX", "KO", "KR", "L", "LDOS", "LEN", "LH", "LHX",
    "LIN", "LKQ", "LLY", "LMT", "LNC", "LNT", "LOW", "LRCX", "LULU", "LUV",
    "LVS", "LW", "LYB", "LYV", "MA", "MAA", "MAR", "MAS", "MCD", "MCHP",
    "MCK", "MCO", "MDLZ", "MDT", "MET", "META", "MGM", "MHK", "MKC", "MKTX",
    "MLM", "MMC", "MMM", "MNST", "MO", "MOH", "MOS", "MPC", "MPWR", "MRK",
    "MRNA", "MRO", "MS", "MSCI", "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU",
    "NCLH", "NDAQ", "NDSN", "NEE", "NEM", "NFLX", "NI", "NKE", "NOC", "NOW",
    "NRG", "NSC", "NTAP", "NTRS", "NUE", "NVDA", "NVR", "NWL", "NWS", "NWSA",
    "NXPI", "O", "OGN", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY",
    "PARA", "PAYC", "PAYX", "PCAR", "PCG", "PEAK", "PEG", "PEP", "PFE", "PFG",
    "PG", "PGR", "PH", "PHM", "PKG", "PKI", "PLD", "PM", "PNC", "PNR",
    "PNW", "POOL", "PPG", "PPL", "PRU", "PSA", "PSX", "PTC", "PWR", "PXD",
    "PYPL", "QCOM", "QRVO", "RCL", "RE", "REG", "REGN", "RF", "RJF", "RL",
    "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX", "SBAC", "SBUX", "SEDG",
    "SEE", "SHW", "SJM", "SLB", "SNA", "SNPS", "SO", "SPG", "SPGI", "SRE",
    "STE", "STT", "STX", "STZ", "SWK", "SWKS", "SYF", "SYK", "SYY", "T",
    "TAP", "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TFX", "TGT", "TJX",
    "TMO", "TMUS", "TPR", "TRMB", "TROW", "TRV", "TSCO", "TSLA", "TSN", "TT",
    "TTWO", "TXN", "TXT", "TYL", "UAL", "UDR", "UHS", "ULTA", "UNH", "UNP",
    "UPS", "URI", "USB", "V", "VFC", "VICI", "VLO", "VMC", "VNO", "VRSK",
    "VRSN", "VRTX", "VTR", "VTRS", "VZ", "WAB", "WAT", "WBA", "WDC", "WEC",
    "WELL", "WFC", "WHR", "WM", "WMB", "WMT", "WRB", "WRK", "WST", "WTW",
    "WY", "WYNN", "XEL", "XOM", "XRAY", "XYL", "YUM", "ZBH", "ZBRA", "ZION",
    "ZTS", "UBER", "PLTR",
]


def load_sp500_tickers() -> list[str]:
    """
    Return S&P 500 ticker list.

    Source: Wikipedia List of S&P 500 companies via pandas read_html.
    Falls back to a bundled static list if Wikipedia is unreachable.
    Filters out tickers with dots (BRK.B, BF.B) — validate_ticker() rejects them.
    """
    try:
        import pandas as pd  # noqa: PLC0415 — optional dep, only needed when called
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        tickers = tables[0]["Symbol"].tolist()
        filtered = [t for t in tickers if "." not in str(t)]
        logger.info("Loaded %d tickers from Wikipedia (%d total)", len(filtered), len(tickers))
        return filtered
    except Exception as exc:
        logger.warning("Wikipedia fetch failed (%s), using static list", exc)
        return list(_STATIC_SP500)


def get_cached_analysis(ticker: str, db_url: str):  # type: ignore[return]
    """
    Look up the most recent analysis for ticker from SQLite.

    Returns None if not found.
    """
    try:
        with open_db(db_url) as conn:
            return get_latest_analysis(conn, ticker)
    except Exception as exc:
        logger.warning("DB lookup failed for %s: %s", ticker, exc)
        return None


def fetch_analyst_rating(ticker: str) -> float | None:
    """
    Pull recommendationMean from yfinance info dict.

    Returns float in range 1.0-5.0, or None if unavailable.
    """
    try:
        stock = yf.Ticker(ticker)
        rating = stock.info.get("recommendationMean")
        return float(rating) if rating is not None else None
    except Exception as exc:
        logger.warning("Analyst rating fetch failed for %s: %s", ticker, exc)
        return None


def run_analysis_safe(ticker: str):  # type: ignore[return]
    """
    Call pipeline.analyze_ticker(ticker) with full exception handling.

    Returns None on any failure (ValueError, AuthenticationError, network, etc.).
    Logs errors at WARNING level — never raises.
    """
    try:
        return analyze_ticker(ticker)
    except Exception as exc:
        logger.warning("Analysis failed for %s: %s", ticker, exc)
        return None


def rate_limited_sleep(seconds: float = 0.5) -> None:
    """Sleep between yfinance calls to avoid throttling."""
    time.sleep(seconds)


def ensure_output_dir() -> Path:
    """Create validation/output/ if it doesn't exist. Return Path."""
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir
