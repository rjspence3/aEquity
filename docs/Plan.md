# Plan.md: The Autonomous Equity Analyst Platform

> **Note (2026-03-05):** Sections 11 and 12 (Model Selection, CrewAI Configuration,
> and Environment Variables) reflect the original design and are **superseded**.
> The implementation uses Claude Haiku 4.5 and Claude Sonnet 4.5 via the Anthropic
> SDK directly (no CrewAI, no OpenAI). See `config.py` and `pipeline.py` for the
> current model configuration.

## 1. Executive Summary
**Goal:** Build an agentic system that autonomously fetches financial data (10-Ks, Transcripts, Market Data) for the S&P 500, analyzes it using a "Virtual Investment Committee" of legendary investors (Buffett, Lynch, etc.), and presents the findings in a structured, clickable dashboard.

**Core Value:** Transforms raw compliance documents into "Decision-Grade" intelligence. It doesn't just summarize; it scores, critiques, and highlights risks.

---

## 2. System Architecture

### A. The Tech Stack
* **Orchestrator:** Direct Python (simple sequential pipeline, no framework)
* **LLM Backend:**
    * *Analysis/Synthesis:* Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`)
    * *Bulk Reading/Extraction:* Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)
    * *Provider:* Anthropic SDK (direct API calls)
* **Data Sources:**
    * `yfinance`: Market data, basic financials.
    * `sec-edgar-downloader`: 10-K/10-Q text.
    * *Hardcoded JSON:* S&P 500 Constituent List (`config/sp500_tickers.json`, refreshed quarterly).
* **Database:** SQLite (MVP) -> PostgreSQL (Production).
* **Frontend:** Streamlit (single-page with collapsible sections).

### B. The Analysis Pipeline (Sequential)
1.  **Step 1: Data Fetching**
    * Fetch latest 10-K from SEC EDGAR
    * Extract sections: "Risk Factors" (Item 1A), "MD&A" (Item 7)
    * Fetch financials from yfinance (income statement, balance sheet, cash flow)
2.  **Step 2: Financial Calculations**
    * Compute ROIC, FCF conversion, debt ratios, PEG, P/B
    * Normalize to 0-100 scores using defined thresholds
3.  **Step 3: LLM Analysis (Claude Sonnet)**
    * Single API call with entire 10-K Risk + MD&A sections (leverage 200K context)
    * Structured output using Pydantic schemas
    * Assess moat, understandability, red flags using rubric-based prompts
4.  **Step 4: Guru Scoring**
    * Apply Buffett/Lynch/Graham/Damodaran formulas
    * Generate verdicts and rationales
    * Combine into overall score (equal weight: 25% each)

---

## 3. The Scorecard Logic (The "Brain")

The system does not output text blobs. It outputs structured `Pydantic` objects.

### Core Pillars (0-100 Score)
| Pillar | Focus | Key Metrics (Drill-Downs) |
| :--- | :--- | :--- |
| **1. The Engine** | Business Quality | ROIC Trend, Gross Margin Stability, Pricing Power evidence. |
| **2. The Moat** | Defensibility | Market Share, Switching Costs, Network Effects (Text evidence). |
| **3. The Fortress** | Financial Health | Net Debt/EBITDA, Altman Z-Score, Free Cash Flow Conversion. |
| **4. Alignment** | Governance | Insider Ownership, Shareholder Yield (Buybacks + Divs), Capital Allocation. |

### The "Hall of Fame" Verdicts
* **Warren Buffett:** Focus on *Moat* + *Owner Earnings*.
* **Peter Lynch:** Focus on *PEG Ratio* (< 1.0) + *Growth Durability*.
* **Ben Graham:** Focus on *Book Value* + *Margin of Safety*.
* **Aswath Damodaran:** Focus on *Valuation* (Reverse DCF Tool).

---

## 4. Implementation Roadmap

### Phase 1: The "Single Stock" MVP (Weekend Build)
- [ ] **Setup:** Initialize `poetry` project, install `crewai`, `yfinance`, `pydantic`.
- [ ] **Quant Agent:** Write script to pull `yfinance` data and calculate ROIC/Margins.
- [ ] **Filing Agent:** Write script to download a 10-K text file for "AAPL".
- [ ] **Crew Assembly:** Connect Agent 1 & 2. Prompt them to output a JSON summary.
- [ ] **Output:** Print the analysis to the console.

### Phase 2: The "Drill-Down" & UI
- [ ] **Pydantic Schemas:** Define `MetricDrillDown`, `PillarAnalysis`, and `GuruScorecard`.
- [ ] **Task Enforcement:** Update CrewAI tasks to `output_pydantic`.
- [ ] **Streamlit App:** Build the basic dashboard.
    - [ ] Input box for Ticker.
    - [ ] "Run Analysis" button.
    - [ ] Visual Gauge Charts for the 4 Pillars.
    - [ ] Expander sections for the Drill-Down evidence.

### Phase 3: The "Guru" Logic
- [ ] **Custom Tool:** Write the `calculate_intrinsic_value_simple` (Damodaran DCF) Python tool.
- [ ] **Guru Agent:** Create the specific prompt for the "Virtual Committee."
- [ ] **Integration:** Add the "Hall of Fame" cards to the Streamlit UI (Green/Red indicators).

### Phase 4: Scaling to S&P 500
- [ ] **The Loop:** Write `polite_fetch` script to iterate through the S&P 500 list.
- [ ] **Database:** Setup SQLite to store results (`ticker`, `date_analyzed`, `json_blob`).
- [ ] **The "Intern" Optimization:** Refactor to use GPT-4o-mini for reading the 10-K text chunks to save API costs.
- [ ] **Batch Run:** Let it run overnight.

### Phase 5: The "Alpha" Modes (Bonus)
- [ ] **Macro Radar:** Aggregate "Risk Factors" across all 500 companies to find trends.
- [ ] **Screener UI:** Add filters to Streamlit ("Show me Lynch Score > 80").

---

## 5. Directory Structure

```text
/equity-analyst-agent
├── agents.yaml             # Definition of Agent Personas
├── tasks.yaml              # Specific instructions for each analysis task
├── main.py                 # Entry point for CrewAI
├── models.py               # Pydantic schemas (The Drill-Down structure)
├── tools/
│   ├── calculator_tools.py # DCF & Ratio math
│   └── sec_tools.py        # 10-K Fetcher
├── db/
│   └── sp500_data.db       # SQLite storage
└── app.py                  # Streamlit Dashboard
```

---

## 6. SEC API Strategy

### Rate Limits
- SEC EDGAR: 10 requests/second (no auth required)
- Implement exponential backoff: 1s → 2s → 4s on 429 errors
- Batch requests with 150ms delay between calls

### Filing Types (MVP)
| Type | Frequency | Use Case |
|------|-----------|----------|
| 10-K | Annual | Full analysis (Risk Factors, MD&A, Financials) |
| 10-Q | Quarterly | Delta detection, trend validation |

### Section Extraction Markers
Target sections identified by Item numbers in filing HTML:
- **Risk Factors:** `Item 1A` → `Item 1B`
- **MD&A:** `Item 7` → `Item 7A`
- **Financial Statements:** `Item 8` → `Item 9`

Regex pattern:
```python
SECTION_PATTERN = r'(?:Item\s*1A[.\s]*Risk\s*Factors)(.*?)(?:Item\s*1B|Item\s*2)'
```

---

## 7. Token & Chunking Strategy

### Problem
10-Ks range from 50k-250k tokens. Context limits require chunking.

### Approach
1. **Pre-filter:** Extract only target sections (reduces to ~20-40k tokens)
2. **Chunk size:** 8,000 tokens per chunk with 500 token overlap
3. **Summarize-then-analyze:**
   - GPT-4o-mini summarizes each chunk → bullet points
   - GPT-4o synthesizes summaries into final analysis

### Token Budget per Company
| Stage | Model | Max Tokens |
|-------|-------|------------|
| Section extraction | None (regex) | 0 |
| Chunk summarization | GPT-4o-mini | 40,000 input |
| Final synthesis | GPT-4o | 8,000 input |
| **Total cost estimate** | | ~$0.08/company |

---

## 8. Guru Scoring Formulas (Explicit)

All scores normalized to 0-100. Final score = weighted average.

### Warren Buffett Score
Focus: Durable competitive advantage + owner earnings
```python
buffett_score = (
    0.30 * roic_score +           # ROIC > 15% = 100, < 8% = 0
    0.25 * fcf_conversion_score + # FCF/NetIncome > 1.0 = 100
    0.25 * moat_score +           # LLM-assessed from 10-K text (0-100)
    0.20 * debt_score             # NetDebt/EBITDA < 1 = 100, > 4 = 0
)
```

### Peter Lynch Score
Focus: Growth at reasonable price
```python
lynch_score = (
    0.40 * peg_score +            # PEG < 1.0 = 100, > 2.0 = 0
    0.30 * earnings_growth +      # 5yr EPS CAGR (15%+ = 100)
    0.30 * understandability      # LLM: "Can a 12-year-old explain this business?"
)
```

### Ben Graham Score
Focus: Margin of safety
```python
graham_score = (
    0.35 * price_to_book +        # P/B < 1.5 = 100, > 3.0 = 0
    0.35 * current_ratio +        # CR > 2.0 = 100, < 1.0 = 0
    0.30 * earnings_stability     # Positive EPS for 10 years = 100
)
```

### Aswath Damodaran Score
Focus: Intrinsic value vs market price
```python
damodaran_score = (
    0.50 * dcf_margin_of_safety + # (Intrinsic - Price) / Price * 100
    0.30 * growth_sustainability + # Reinvestment rate * ROIC
    0.20 * risk_adjusted_return    # Expected return vs WACC
)
```

### Metric Normalization Functions
```python
def normalize_roic(roic: float) -> int:
    """ROIC > 20% = 100, < 5% = 0, linear between"""
    return max(0, min(100, int((roic - 5) / 15 * 100)))

def normalize_peg(peg: float) -> int:
    """PEG < 0.5 = 100, > 2.5 = 0"""
    if peg <= 0: return 0  # Negative earnings
    return max(0, min(100, int((2.5 - peg) / 2.0 * 100)))

def normalize_debt_ratio(net_debt_ebitda: float) -> int:
    """NetDebt/EBITDA < 1 = 100, > 4 = 0"""
    if net_debt_ebitda < 0: return 100  # Net cash position
    return max(0, min(100, int((4 - net_debt_ebitda) / 3 * 100)))

def normalize_fcf_conversion(fcf_to_net_income: float) -> int:
    """FCF/NetIncome > 1.2 = 100, < 0.5 = 0"""
    return max(0, min(100, int((fcf_to_net_income - 0.5) / 0.7 * 100)))
```

---

## 9. Error Handling & Fallbacks

| Error | Detection | Fallback |
|-------|-----------|----------|
| Ticker not found | yfinance returns empty | Skip, log to `errors.json` |
| Filing unavailable | SEC returns 404 | Use most recent available filing, flag as stale |
| API rate limit | 429 response | Exponential backoff, max 3 retries |
| LLM timeout | >60s response | Retry once, then mark analysis as "incomplete" |
| Token overflow | Chunk count > 10 | Summarize only Risk Factors + MD&A, skip others |
| Missing financials | Key metric is null | Score that pillar as "N/A", exclude from average |

### Graceful Degradation
If a company cannot be fully analyzed:
1. Attempt partial analysis (quant-only if filing unavailable)
2. Store partial result with `confidence: "low"`
3. Continue to next ticker (don't halt batch)

### Error Log Schema
```python
class AnalysisError(BaseModel):
    ticker: str
    timestamp: datetime
    error_type: Literal["not_found", "filing_unavailable", "rate_limit", "timeout", "token_overflow", "missing_data"]
    message: str
    partial_result: Optional[dict] = None
```

---

## 10. Pydantic Schema Definitions (Complete)

```python
# models.py

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date

class MetricDrillDown(BaseModel):
    """Evidence and calculation details for a single metric."""
    metric_name: str                              # e.g., "ROIC"
    raw_value: float                              # e.g., 0.18 (18%)
    normalized_score: int = Field(ge=0, le=100)   # 0-100
    source: Literal["yfinance", "10-K", "calculated"]
    evidence: str                                 # Supporting quote or calculation
    confidence: Literal["high", "medium", "low"]

class PillarAnalysis(BaseModel):
    """Score and evidence for one of the four pillars."""
    pillar_name: Literal["The Engine", "The Moat", "The Fortress", "Alignment"]
    score: int = Field(ge=0, le=100)
    metrics: list[MetricDrillDown]
    summary: str                                  # 2-3 sentence synthesis
    red_flags: list[str]                          # Concerns identified

class GuruScorecard(BaseModel):
    """Complete analysis for one legendary investor's perspective."""
    guru_name: Literal["Warren Buffett", "Peter Lynch", "Ben Graham", "Aswath Damodaran"]
    score: int = Field(ge=0, le=100)
    verdict: Literal["Strong Buy", "Buy", "Hold", "Avoid", "Strong Avoid"]
    rationale: str                                # 3-5 sentence explanation
    key_metrics: list[MetricDrillDown]

class CompanyAnalysis(BaseModel):
    """Complete analysis output for a single company."""
    ticker: str
    company_name: str
    analysis_date: date
    filing_date: date
    filing_type: Literal["10-K", "10-Q"]
    pillars: list[PillarAnalysis]
    gurus: list[GuruScorecard]
    overall_score: int = Field(ge=0, le=100)
    confidence: Literal["high", "medium", "low"]
    errors: list[str] = []
    partial: bool = False                         # True if analysis is incomplete
```

---

## 11. LLM Configuration (Resolved)

### Model Selection
| Role | Model | Provider | Rationale |
|------|-------|----------|-----------|
| Manager (Synthesis) | `gpt-4o-2024-08-06` | OpenAI | Best reasoning for investment analysis |
| Intern (Bulk Reading) | `gpt-4o-mini` | OpenAI | Cost-effective for extraction tasks |

### CrewAI Configuration
```yaml
# agents.yaml

filing_hunter:
  role: "Senior Data Engineer"
  goal: "Extract clean, structured text from SEC filings"
  backstory: "You specialize in parsing complex financial documents..."
  llm: "gpt-4o-mini"
  max_tokens: 2000

forensic_accountant:
  role: "Quantitative Analyst"
  goal: "Calculate and interpret financial ratios with precision"
  backstory: "You have 20 years of experience in equity research..."
  llm: "gpt-4o-mini"
  max_tokens: 1500

risk_assessor:
  role: "Chief Risk Officer"
  goal: "Identify and quantify business and financial risks"
  backstory: "You've seen multiple market cycles and company failures..."
  llm: "gpt-4o"
  max_tokens: 2000

virtual_committee:
  role: "Investment Committee Chair"
  goal: "Synthesize analysis through the lens of legendary investors"
  backstory: "You embody the wisdom of Buffett, Lynch, Graham, and Damodaran..."
  llm: "gpt-4o"
  max_tokens: 3000
```

---

## 12. Environment & Secrets Configuration

### Environment Variables
```bash
# .env.example

# OpenAI (Required)
OPENAI_API_KEY=sk-...

# SEC API (Optional - for premium API access)
SEC_API_KEY=                      # Leave blank for free EDGAR access

# Database
DATABASE_URL=sqlite:///db/sp500_data.db   # SQLite for MVP
# DATABASE_URL=postgresql://user:pass@host:5432/equity_analyst  # Production

# Streamlit
STREAMLIT_SERVER_PORT=8501

# Rate Limiting
SEC_REQUESTS_PER_SECOND=10
LLM_MAX_RETRIES=3
```

### Secrets Management
For MVP (local development):
- Store in `.env` file (gitignored)
- Load via `python-dotenv` or Pydantic Settings

For Production:
- Use AWS Secrets Manager or similar
- Inject as environment variables at runtime

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str
    sec_api_key: str = ""  # Optional
    database_url: str = "sqlite:///db/sp500_data.db"
    sec_requests_per_second: int = 10
    llm_max_retries: int = 3

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 13. Testing Requirements

### Unit Tests
| Module | Test Cases |
|--------|------------|
| `calculator_tools.py` | ROIC calculation, PEG normalization, edge cases (negative values, division by zero) |
| `sec_tools.py` | Section extraction regex, filing type detection, error handling |
| `models.py` | Pydantic validation, score boundaries |

### Integration Tests
| Scenario | Validation |
|----------|------------|
| Single stock analysis | Full pipeline for AAPL produces valid `CompanyAnalysis` |
| Missing data handling | Company with null financials produces partial result |
| Rate limit recovery | Simulated 429 triggers backoff and retry |

### Test Fixtures
```python
# tests/fixtures/aapl_yfinance.json - Cached yfinance response
# tests/fixtures/aapl_10k_excerpt.txt - Sample 10-K section
# tests/fixtures/expected_analysis.json - Known-good output
```

### Coverage Target
- Minimum: 70% line coverage
- Critical paths (scoring, error handling): 90%

### Test Commands
```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run specific module
pytest tests/test_calculator.py -v
```

### CI/CD Integration

```yaml
# .github/workflows/test.yml
name: aEquity Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Run tests with coverage
        run: pytest tests/ --cov=. --cov-report=xml --cov-fail-under=70
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          fail_ci_if_error: true
      - name: Lint
        run: ruff check .
```

---

## 14. yfinance Field Mappings (ROIC Derivation)

yfinance does not provide ROIC directly. Derive as follows:

```python
# tools/calculator_tools.py

def calculate_roic(ticker: str) -> float | None:
    """
    ROIC = NOPAT / Invested Capital

    Returns decimal (e.g., 0.18 for 18%) or None if data unavailable.
    """
    import yfinance as yf

    stock = yf.Ticker(ticker)
    income = stock.income_stmt
    balance = stock.balance_sheet

    try:
        # NOPAT = Operating Income * (1 - Tax Rate)
        operating_income = income.loc['Operating Income'].iloc[0]
        tax_provision = income.loc['Tax Provision'].iloc[0]
        pretax_income = income.loc['Pretax Income'].iloc[0]

        if pretax_income == 0:
            return None

        tax_rate = tax_provision / pretax_income
        nopat = operating_income * (1 - tax_rate)

        # Invested Capital = Total Assets - Current Liabilities - Cash
        total_assets = balance.loc['Total Assets'].iloc[0]
        current_liabilities = balance.loc['Current Liabilities'].iloc[0]
        cash = balance.loc['Cash And Cash Equivalents'].iloc[0]
        invested_capital = total_assets - current_liabilities - cash

        if invested_capital <= 0:
            return None

        return nopat / invested_capital

    except (KeyError, IndexError, ZeroDivisionError):
        return None


def calculate_fcf_conversion(ticker: str) -> float | None:
    """
    FCF Conversion = Free Cash Flow / Net Income

    Returns ratio (e.g., 1.2) or None if unavailable.
    """
    import yfinance as yf

    stock = yf.Ticker(ticker)
    cashflow = stock.cashflow
    income = stock.income_stmt

    try:
        fcf = cashflow.loc['Free Cash Flow'].iloc[0]
        net_income = income.loc['Net Income'].iloc[0]

        if net_income <= 0:
            return None

        return fcf / net_income

    except (KeyError, IndexError, ZeroDivisionError):
        return None
```

---

## 15. Success Criteria

### MVP Definition of Done
- [ ] Single stock analysis (AAPL) completes in < 2 minutes
- [ ] Output matches `CompanyAnalysis` schema with all 4 pillars populated
- [ ] Streamlit dashboard renders gauge charts and drill-downs
- [ ] Error handling tested for missing data and API failures

### Batch Run Success
- [ ] S&P 500 analysis completes in < 8 hours
- [ ] >= 95% of companies have complete analysis
- [ ] Total API cost < $50 for full run
- [ ] Results stored in SQLite with queryable structure

### Quality Gates
| Metric | Target |
|--------|--------|
| Schema validation pass rate | 100% |
| Partial analysis rate | < 5% |
| Average confidence score | > 0.7 |
| User can explain any score drill-down | Qualitative

---

## 16. Security Requirements

### Secrets Management

| Secret | Storage (MVP) | Storage (Production) | Notes |
|--------|--------------|---------------------|-------|
| `OPENAI_API_KEY` | `.env` file | AWS Secrets Manager | Never logged, never in git |
| `SEC_API_KEY` | `.env` file | AWS Secrets Manager | Rate limits enforced |
| SQLite database | Local file | PostgreSQL with auth | Contains no PII |

### .env.example
```bash
# Copy to .env and fill in values
OPENAI_API_KEY=sk-...
SEC_API_KEY=...
DATABASE_URL=sqlite:///./aequity.db
LOG_LEVEL=INFO
```

### Input Validation

```python
# tools/validator.py
import re

TICKER_PATTERN = re.compile(r'^[A-Z]{1,5}$')

def validate_ticker(ticker: str) -> str:
    """Sanitize and validate ticker input."""
    ticker = ticker.upper().strip()
    if not TICKER_PATTERN.match(ticker):
        raise ValueError(f"Invalid ticker format: {ticker}")
    return ticker

def validate_tickers_batch(tickers: list[str], max_batch: int = 100) -> list[str]:
    """Validate batch of tickers with size limit."""
    if len(tickers) > max_batch:
        raise ValueError(f"Batch size {len(tickers)} exceeds max {max_batch}")
    return [validate_ticker(t) for t in tickers]
```

### Rate Limiting (Streamlit)

```python
# app.py
from datetime import datetime, timedelta
from collections import defaultdict
import streamlit as st

class SessionRateLimiter:
    MAX_ANALYSES_PER_HOUR = 20

    @staticmethod
    def check_limit() -> bool:
        if 'analysis_timestamps' not in st.session_state:
            st.session_state.analysis_timestamps = []

        now = datetime.now()
        hour_ago = now - timedelta(hours=1)

        # Clean old timestamps
        st.session_state.analysis_timestamps = [
            ts for ts in st.session_state.analysis_timestamps
            if ts > hour_ago
        ]

        if len(st.session_state.analysis_timestamps) >= SessionRateLimiter.MAX_ANALYSES_PER_HOUR:
            return False

        st.session_state.analysis_timestamps.append(now)
        return True
```

### Data Access Controls

| Data Type | Access Level | Retention |
|-----------|--------------|-----------|
| Raw 10-K text | Internal only | 7 days (cache) |
| Analysis results | Read-only via dashboard | Indefinite |
| API logs | Admin only | 30 days |
| Error logs | Admin only | 90 days |

### Logging Policy

```python
# config/logging.py
import logging

# NEVER log these patterns
REDACT_PATTERNS = [
    r'sk-[a-zA-Z0-9]+',  # OpenAI keys
    r'Bearer [a-zA-Z0-9]+',  # Auth tokens
]

class RedactingFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        for pattern in REDACT_PATTERNS:
            msg = re.sub(pattern, '[REDACTED]', msg)
        return msg
```

### Security Checklist

- [ ] `.env` in `.gitignore`
- [ ] No API keys in logs or error messages
- [ ] Ticker input validated before API calls
- [ ] Rate limiting prevents abuse
- [ ] Database file not world-readable
- [ ] HTTPS enforced in production (Streamlit Cloud)