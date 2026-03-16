# aEquity — Autonomous Equity Analyst

aEquity analyzes S&P 500 stocks through four guru-driven lenses: business quality, competitive moat, financial health, and governance. It combines quantitative metrics from yfinance, qualitative signals from SEC 10-K filings, and Claude LLM scoring into a 0–100 scorecard.

## Prerequisites

- Python 3.11+
- [Anthropic API key](https://console.anthropic.com/)
- A real email address for SEC EDGAR access (required by EDGAR terms of service)

## Install

```bash
pip install -e ".[dev]"
cp .env.example .env
# Edit .env and fill in ANTHROPIC_API_KEY and SEC_USER_AGENT_EMAIL
```

## Quick Start

**Single stock (CLI):**
```bash
python main.py AAPL
```

**Streamlit dashboard:**
```bash
streamlit run app.py
```

**Batch analysis:**
```bash
python batch.py --limit 20          # analyze 20 S&P 500 companies
python batch.py --tickers AAPL MSFT GOOG
```

## Architecture

```
main.py          CLI entry point
app.py           Streamlit dashboard (Analyze / Screener / Macro Radar tabs)
batch.py         Batch runner — populates the SQLite DB
pipeline.py      Core analysis: fetch → calculate → LLM → score → assemble
config.py        Settings loaded from .env via pydantic-settings
models.py        Pydantic schemas (CompanyAnalysis, PillarAnalysis, GuruScorecard)
scoring_config.py  All tunable constants (weights, thresholds, model IDs)

tools/
  calculator_tools.py  Financial ratio calculations (yfinance)
  sec_tools.py         SEC EDGAR 10-K downloader and section extractor
  validator.py         Ticker symbol validation

db/
  init.py        SQLite helpers (open_db, save_analysis, get_all_latest)
```

### Four Pillars

| Pillar | What it measures |
|--------|-----------------|
| The Engine | Business quality — ROIC, gross margin |
| The Moat | Competitive defensibility — LLM analysis of 10-K text |
| The Fortress | Financial health — FCF conversion, net debt/EBITDA |
| Alignment | Governance — insider ownership, shareholder yield |

### Virtual Investment Committee

Each stock is scored from the perspective of four legendary investors:
- **Warren Buffett** — ROIC, FCF conversion, moat, leverage
- **Peter Lynch** — PEG ratio, earnings growth, business understandability
- **Ben Graham** — P/B ratio, current ratio, earnings stability
- **Aswath Damodaran** — ROIC, PEG, leverage (proxy for reverse-DCF)

## Configuration

All tunable constants (weights, normalization ranges, model IDs, verdict boundaries) live in `scoring_config.py`. See `.env.example` for environment variables.

## Development

```bash
ruff check .                          # lint
mypy --ignore-missing-imports .       # type check
pytest tests/ -v                      # run tests
pytest tests/ --cov=. --cov-report=term-missing  # with coverage
```

## Further Reading

See `docs/Plan.md` for the full design rationale and roadmap.
