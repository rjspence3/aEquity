"""Core analysis pipeline: fetch → calculate → analyze → score."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import date
from typing import Any, cast

import anthropic
import yfinance as yf

from config import settings
from models import (
    CompanyAnalysis,
    GuruScorecard,
    MetricDrillDown,
    PillarAnalysis,
)
from scoring_config import (
    ALIGNMENT_WEIGHTS,
    ENGINE_WEIGHTS,
    FORTRESS_WEIGHTS,
    HAIKU_MODEL,
    SONNET_MODEL,
    VERDICT_AVOID,
    VERDICT_BUY,
    VERDICT_HOLD,
    VERDICT_STRONG_BUY,
)
from tools.calculator_tools import (
    build_alignment_metrics,
    build_engine_metrics,
    build_fortress_metrics,
    compute_all_metrics,
    normalize_current_ratio,
    normalize_debt_ratio,
    normalize_fcf_conversion,
    normalize_peg,
    normalize_price_to_book,
    normalize_roic,
)
from tools.sec_tools import fetch_10k_sections
from tools.validator import validate_ticker

logger = logging.getLogger(__name__)


def _parse_llm_json(raw: str) -> dict:  # type: ignore[type-arg]
    """Strip optional markdown fences and parse a JSON object from an LLM response."""
    text = raw.strip()
    if "```" in text:
        text = text.split("```")[1].removeprefix("json").strip()
    return cast(dict, json.loads(text))  # type: ignore[type-arg]


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _call_claude(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
    retries: int = 3,
) -> str:
    """Call Claude with retry logic; returns the text response."""
    for attempt in range(1, retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text  # type: ignore[union-attr]
        except anthropic.RateLimitError:
            wait = 2 ** attempt
            logger.warning(
                "Rate limit hit, retrying in %ds (attempt %d/%d)", wait, attempt, retries
            )
            time.sleep(wait)
        except anthropic.APITimeoutError:
            if attempt == retries:
                raise
            time.sleep(2)
    raise RuntimeError(f"Claude call failed after {retries} retries")


def _assess_moat_and_understandability(
    client: anthropic.Anthropic,
    ticker: str,
    company_name: str,
    risk_factors: str | None,
    mdna: str | None,
) -> dict[str, object]:
    """
    Use Claude Haiku to assess qualitative dimensions from filing text.

    Returns dict with keys: moat_score, understandability_score, moat_evidence,
    understandability_evidence, red_flags.
    """
    if not risk_factors and not mdna:
        return {
            "moat_score": 50,
            "understandability_score": 50,
            "moat_evidence": "No filing text available — defaulting to neutral score.",
            "understandability_evidence": "No filing text available.",
            "red_flags": [],
        }

    filing_excerpt = ""
    if risk_factors:
        filing_excerpt += f"=== RISK FACTORS ===\n{risk_factors[:50000]}\n\n"
    if mdna:
        filing_excerpt += f"=== MD&A ===\n{mdna[:50000]}\n\n"

    system_prompt = (
        "You are a senior equity analyst. Analyze the provided 10-K filing excerpts "
        "and return ONLY a valid JSON object with no markdown or explanation. "
        "Score each dimension 0–100 where 100 is best."
    )

    user_prompt = f"""Analyze {company_name} ({ticker}) based on this 10-K excerpt.

{filing_excerpt}

Return exactly this JSON structure (no other text):
{{
  "moat_score": <integer 0-100>,
  "moat_evidence": "<one sentence citing specific evidence from the filing>",
  "understandability_score": <integer 0-100>,
  "understandability_evidence": "<one sentence: can a 12-year-old understand this business?>",
  "red_flags": ["<flag 1>", "<flag 2>"]
}}

Scoring criteria:
- moat_score: 80-100 = clear durable advantages (brands, switching costs, network
  effects); 40-60 = moderate; 0-20 = commodity/no moat
- understandability_score: 80-100 = simple, clear business model; 40-60 = moderate
  complexity; 0-20 = opaque or complex
"""

    raw = _call_claude(client, HAIKU_MODEL, system_prompt, user_prompt, max_tokens=1024)

    try:
        return cast(dict[str, object], _parse_llm_json(raw))
    except (json.JSONDecodeError, IndexError) as exc:
        logger.warning("Failed to parse moat assessment JSON: %s — raw: %s", exc, raw[:200])
        return {
            "moat_score": 50,
            "understandability_score": 50,
            "moat_evidence": "Assessment parsing failed.",
            "understandability_evidence": "Assessment parsing failed.",
            "red_flags": [],
        }


def _generate_guru_rationales(
    client: anthropic.Anthropic,
    ticker: str,
    company_name: str,
    guru_scores: dict[str, int],
    metrics_summary: str,
) -> dict[str, str]:
    """
    Use Claude Sonnet to generate 3-5 sentence rationales for each guru verdict.

    Returns dict mapping guru_name → rationale string.
    """
    system_prompt = (
        "You are an investment analyst writing from the perspectives of legendary investors. "
        "Be specific about the company's actual metrics. Keep each rationale to 3-5 sentences. "
        "Return ONLY a valid JSON object."
    )

    user_prompt = f"""Company: {company_name} ({ticker})

Key Metrics:
{metrics_summary}

Guru Scores:
- Warren Buffett: {guru_scores.get("Warren Buffett", 50)}/100
- Peter Lynch: {guru_scores.get("Peter Lynch", 50)}/100
- Ben Graham: {guru_scores.get("Ben Graham", 50)}/100
- Aswath Damodaran: {guru_scores.get("Aswath Damodaran", 50)}/100

For each investor, write a 3-5 sentence rationale explaining WHY they would score this
company that way. Reference specific metrics. Return exactly this JSON (no markdown):
{{
  "Warren Buffett": "<3-5 sentence rationale>",
  "Peter Lynch": "<3-5 sentence rationale>",
  "Ben Graham": "<3-5 sentence rationale>",
  "Aswath Damodaran": "<3-5 sentence rationale>"
}}
"""

    raw = _call_claude(client, SONNET_MODEL, system_prompt, user_prompt, max_tokens=2048)

    try:
        return cast(dict[str, str], _parse_llm_json(raw))
    except (json.JSONDecodeError, IndexError) as exc:
        logger.warning("Failed to parse guru rationales JSON: %s", exc)
        return {
            guru: f"Score: {score}/100. Rationale generation failed."
            for guru, score in guru_scores.items()
        }


def _generate_pillar_summaries(
    client: anthropic.Anthropic,
    ticker: str,
    company_name: str,
    pillar_scores: dict[str, int],
    metrics_summary: str,
) -> dict[str, str]:
    """Generate 2-3 sentence summaries for each pillar using Claude Sonnet."""
    system_prompt = (
        "You are a senior equity analyst. Write concise, evidence-based summaries. "
        "Return ONLY a valid JSON object."
    )

    user_prompt = f"""Company: {company_name} ({ticker})

Metrics:
{metrics_summary}

Pillar Scores:
- The Engine (business quality): {pillar_scores.get("The Engine", 50)}/100
- The Moat (defensibility): {pillar_scores.get("The Moat", 50)}/100
- The Fortress (financial health): {pillar_scores.get("The Fortress", 50)}/100
- Alignment (governance): {pillar_scores.get("Alignment", 50)}/100

Write a 2-3 sentence summary for each pillar. Be specific about the company.
Return exactly this JSON (no markdown):
{{
  "The Engine": "<2-3 sentence summary>",
  "The Moat": "<2-3 sentence summary>",
  "The Fortress": "<2-3 sentence summary>",
  "Alignment": "<2-3 sentence summary>"
}}
"""

    raw = _call_claude(client, SONNET_MODEL, system_prompt, user_prompt, max_tokens=1024)

    try:
        return cast(dict[str, str], _parse_llm_json(raw))
    except (json.JSONDecodeError, IndexError) as exc:
        logger.warning("Failed to parse pillar summaries JSON: %s", exc)
        return {pillar: f"Score: {score}/100." for pillar, score in pillar_scores.items()}


# ── Guru scoring formulas ──────────────────────────────────────────────────────

def _score_buffett(
    roic: float | None,
    fcf_conv: float | None,
    moat_score: int,
    nd_ebitda: float | None,
) -> int:
    components = []
    if roic is not None:
        components.append((0.30, normalize_roic(roic)))
    if fcf_conv is not None:
        components.append((0.25, normalize_fcf_conversion(fcf_conv)))
    components.append((0.25, moat_score))
    if nd_ebitda is not None:
        components.append((0.20, normalize_debt_ratio(nd_ebitda)))

    if not components:
        return 50

    total_weight = sum(w for w, _ in components)
    return int(sum(w * s for w, s in components) / total_weight)


def _score_lynch(
    peg: float | None,
    earnings_growth: float | None,
    understandability: int,
) -> int:
    components = []
    if peg is not None:
        components.append((0.40, normalize_peg(peg)))
    if earnings_growth is not None:
        growth_score = max(0, min(100, int(earnings_growth / 0.15 * 100)))
        components.append((0.30, growth_score))
    components.append((0.30, understandability))

    if not components:
        return 50

    total_weight = sum(w for w, _ in components)
    return int(sum(w * s for w, s in components) / total_weight)


def _score_graham(
    pb: float | None,
    current_ratio: float | None,
    earnings_growth: float | None,
) -> int:
    components = []
    if pb is not None:
        components.append((0.35, normalize_price_to_book(pb)))
    if current_ratio is not None:
        components.append((0.35, normalize_current_ratio(current_ratio)))
    if earnings_growth is not None:
        stability = 100 if earnings_growth > 0 else 0
        components.append((0.30, stability))

    if not components:
        return 50

    total_weight = sum(w for w, _ in components)
    return int(sum(w * s for w, s in components) / total_weight)


def _score_damodaran(
    roic: float | None,
    peg: float | None,
    nd_ebitda: float | None,
) -> int:
    """
    Proxy Damodaran score using ROIC, PEG, and leverage as valuation inputs.
    A full reverse-DCF requires a price target; this approximation is intentional
    for the MVP and flagged as Phase 3 work in docs/Plan.md.
    """
    components = []
    if roic is not None:
        components.append((0.50, normalize_roic(roic)))
    if peg is not None:
        components.append((0.30, normalize_peg(peg)))
    if nd_ebitda is not None:
        components.append((0.20, normalize_debt_ratio(nd_ebitda)))

    if not components:
        return 50

    total_weight = sum(w for w, _ in components)
    return int(sum(w * s for w, s in components) / total_weight)


def _score_to_verdict(score: int) -> str:
    if score >= VERDICT_STRONG_BUY:
        return "Strong Buy"
    if score >= VERDICT_BUY:
        return "Buy"
    if score >= VERDICT_HOLD:
        return "Hold"
    if score >= VERDICT_AVOID:
        return "Avoid"
    return "Strong Avoid"


# ── Pillar score aggregation ──────────────────────────────────────────────────

def _weighted_score(metrics: list[MetricDrillDown], weights: dict[str, float]) -> int:
    """
    Weighted average of metric scores.

    Unknown metric names fall back to equal weighting (1 / len(metrics)) so that
    test fixtures and future metrics degrade gracefully rather than being silently
    excluded.
    """
    if not metrics:
        return 50

    equal_fallback = 1.0 / len(metrics)
    total_weight = 0.0
    weighted_sum = 0.0

    for m in metrics:
        w = weights.get(m.metric_name, equal_fallback)
        weighted_sum += w * m.normalized_score
        total_weight += w

    if total_weight == 0:
        return 50

    return int(weighted_sum / total_weight)


def _score_engine(metrics: list[MetricDrillDown]) -> int:
    return _weighted_score(metrics, ENGINE_WEIGHTS)


def _score_fortress(metrics: list[MetricDrillDown]) -> int:
    return _weighted_score(metrics, FORTRESS_WEIGHTS)


def _score_alignment(metrics: list[MetricDrillDown]) -> int:
    return _weighted_score(metrics, ALIGNMENT_WEIGHTS)


# ── Main pipeline ──────────────────────────────────────────────────────────────

def analyze_ticker(ticker: str) -> CompanyAnalysis:
    """Run the full analysis pipeline for a single ticker. Returns CompanyAnalysis."""
    ticker = validate_ticker(ticker)
    errors: list[str] = []
    partial = False

    logger.info("Starting analysis for %s", ticker)

    # ── Step 1: Fetch company info ─────────────────────────────────────────────
    try:
        def _fetch_info() -> tuple[yf.Ticker, dict]:
            s = yf.Ticker(ticker)
            return s, s.info

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch_info)
            try:
                stock, info = future.result(timeout=60)
            except FuturesTimeoutError as exc:
                raise ValueError(f"yfinance timed out fetching data for {ticker}") from exc

        company_name = info.get("longName") or info.get("shortName") or ticker
    except ValueError:
        raise
    except Exception as exc:
        logger.error("Failed to fetch info for %s: %s", ticker, exc)
        raise ValueError(f"Ticker {ticker} not found or yfinance unavailable") from exc

    # ── Step 2: Fetch 10-K ─────────────────────────────────────────────────────
    logger.info("Fetching 10-K for %s", ticker)
    filing_data = fetch_10k_sections(ticker)
    risk_factors = filing_data.get("risk_factors")
    mdna = filing_data.get("mdna")
    filing_date_str = filing_data.get("filing_date")

    if not risk_factors and not mdna:
        errors.append("10-K sections unavailable — qualitative scores defaulted to neutral")
        partial = True

    try:
        filing_date = date.fromisoformat(filing_date_str) if filing_date_str else date.today()
    except (ValueError, TypeError):
        filing_date = date.today()

    # ── Step 3: Calculate quantitative metrics ─────────────────────────────────
    logger.info("Calculating quantitative metrics for %s", ticker)
    precomputed = compute_all_metrics(stock)
    roic = precomputed["roic"]
    fcf_conv = precomputed["fcf_conversion"]
    nd_ebitda = precomputed["net_debt_ebitda"]
    peg = precomputed["peg_ratio"]
    pb = precomputed["price_to_book"]
    current_ratio = precomputed["current_ratio"]
    earnings_growth = precomputed["earnings_growth"]

    fortress_metrics = build_fortress_metrics(stock, precomputed)
    engine_metrics = build_engine_metrics(stock, precomputed)
    alignment_metrics = build_alignment_metrics(stock)

    # ── Step 4: LLM qualitative assessment ────────────────────────────────────
    logger.info("Running LLM qualitative assessment for %s", ticker)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    qualitative = _assess_moat_and_understandability(
        client, ticker, company_name, risk_factors, mdna
    )
    moat_score = int(cast(Any, qualitative.get("moat_score", 50)))
    understandability = int(cast(Any, qualitative.get("understandability_score", 50)))
    moat_evidence = str(qualitative.get("moat_evidence", ""))
    raw_flags = cast(Any, qualitative.get("red_flags", []))
    filing_red_flags: list[str] = [str(f) for f in raw_flags] if raw_flags else []

    moat_metric = MetricDrillDown(
        metric_name="Moat Score",
        raw_value=float(moat_score),
        normalized_score=moat_score,
        source="10-K",
        evidence=moat_evidence,
        confidence="medium",
    )
    understandability_metric = MetricDrillDown(
        metric_name="Understandability",
        raw_value=float(understandability),
        normalized_score=understandability,
        source="10-K",
        evidence=str(qualitative.get("understandability_evidence", "")),
        confidence="medium",
    )

    # ── Step 5: Apply guru scoring formulas ───────────────────────────────────
    buffett_score = _score_buffett(roic, fcf_conv, moat_score, nd_ebitda)
    lynch_score = _score_lynch(peg, earnings_growth, understandability)
    graham_score = _score_graham(pb, current_ratio, earnings_growth)
    damodaran_score = _score_damodaran(roic, peg, nd_ebitda)
    overall_score = int((buffett_score + lynch_score + graham_score + damodaran_score) / 4)

    guru_scores = {
        "Warren Buffett": buffett_score,
        "Peter Lynch": lynch_score,
        "Ben Graham": graham_score,
        "Aswath Damodaran": damodaran_score,
    }

    # ── Step 6: Generate narrative with Claude Sonnet ─────────────────────────
    logger.info("Generating narratives for %s", ticker)
    metrics_lines = []
    if roic is not None:
        metrics_lines.append(f"- ROIC: {roic * 100:.1f}%")
    if fcf_conv is not None:
        metrics_lines.append(f"- FCF Conversion: {fcf_conv:.2f}x")
    if nd_ebitda is not None:
        metrics_lines.append(f"- Net Debt/EBITDA: {nd_ebitda:.2f}x")
    if peg is not None:
        metrics_lines.append(f"- PEG Ratio: {peg:.2f}")
    if pb is not None:
        metrics_lines.append(f"- Price/Book: {pb:.2f}")
    if current_ratio is not None:
        metrics_lines.append(f"- Current Ratio: {current_ratio:.2f}")
    if earnings_growth is not None:
        metrics_lines.append(f"- Earnings Growth: {earnings_growth * 100:.1f}%")
    metrics_lines.append(f"- Moat Score: {moat_score}/100")
    metrics_lines.append(f"- Understandability: {understandability}/100")
    metrics_summary = "\n".join(metrics_lines)

    guru_rationales = _generate_guru_rationales(
        client, ticker, company_name, guru_scores, metrics_summary
    )

    pillar_scores = {
        "The Engine": _score_engine(engine_metrics),
        "The Moat": moat_score,
        "The Fortress": _score_fortress(fortress_metrics),
        "Alignment": _score_alignment(alignment_metrics),
    }
    pillar_summaries = _generate_pillar_summaries(
        client, ticker, company_name, pillar_scores, metrics_summary
    )

    # ── Step 7: Assemble CompanyAnalysis ──────────────────────────────────────

    # Build guru key metrics directly from raw calculated values.
    # Constructing them here (rather than filtering the pillar metric lists by name)
    # keeps guru metrics independent of pillar structure.
    buffett_key_metrics: list[MetricDrillDown] = []
    if roic is not None:
        buffett_key_metrics.append(MetricDrillDown(
            metric_name="ROIC",
            raw_value=round(roic * 100, 2),
            normalized_score=normalize_roic(roic),
            source="calculated",
            evidence=f"ROIC = {roic * 100:.1f}%",
            confidence="high",
        ))
    if fcf_conv is not None:
        buffett_key_metrics.append(MetricDrillDown(
            metric_name="FCF Conversion",
            raw_value=round(fcf_conv, 3),
            normalized_score=normalize_fcf_conversion(fcf_conv),
            source="calculated",
            evidence=f"FCF / Net Income = {fcf_conv:.2f}x",
            confidence="high",
        ))
    buffett_key_metrics.append(moat_metric)

    lynch_key_metrics: list[MetricDrillDown] = []
    if peg is not None:
        lynch_key_metrics.append(MetricDrillDown(
            metric_name="PEG Ratio",
            raw_value=peg,
            normalized_score=normalize_peg(peg),
            source="yfinance",
            evidence=f"PEG = {peg:.2f}",
            confidence="medium",
        ))
    lynch_key_metrics.append(understandability_metric)

    graham_key_metrics: list[MetricDrillDown] = []
    if pb is not None:
        graham_key_metrics.append(MetricDrillDown(
            metric_name="Price/Book",
            raw_value=pb,
            normalized_score=normalize_price_to_book(pb),
            source="yfinance",
            evidence=f"P/B = {pb:.2f}",
            confidence="high",
        ))
    if current_ratio is not None:
        graham_key_metrics.append(MetricDrillDown(
            metric_name="Current Ratio",
            raw_value=current_ratio,
            normalized_score=normalize_current_ratio(current_ratio),
            source="calculated",
            evidence=f"Current Ratio = {current_ratio:.2f}",
            confidence="high",
        ))

    damodaran_key_metrics: list[MetricDrillDown] = []
    if roic is not None:
        damodaran_key_metrics.append(MetricDrillDown(
            metric_name="ROIC",
            raw_value=round(roic * 100, 2),
            normalized_score=normalize_roic(roic),
            source="calculated",
            evidence=f"ROIC = {roic * 100:.1f}%",
            confidence="high",
        ))
    if peg is not None:
        damodaran_key_metrics.append(MetricDrillDown(
            metric_name="PEG Ratio",
            raw_value=peg,
            normalized_score=normalize_peg(peg),
            source="yfinance",
            evidence=f"PEG = {peg:.2f}",
            confidence="medium",
        ))

    def _build_guru_scorecard(
        name: str, score: int, key_metrics: list[MetricDrillDown]
    ) -> GuruScorecard:
        return GuruScorecard(
            guru_name=name,  # type: ignore[arg-type]
            score=score,
            verdict=_score_to_verdict(score),  # type: ignore[arg-type]
            rationale=guru_rationales.get(name, f"Score: {score}/100"),
            key_metrics=key_metrics,
        )

    gurus = [
        _build_guru_scorecard("Warren Buffett", buffett_score, buffett_key_metrics),
        _build_guru_scorecard("Peter Lynch", lynch_score, lynch_key_metrics),
        _build_guru_scorecard("Ben Graham", graham_score, graham_key_metrics),
        _build_guru_scorecard("Aswath Damodaran", damodaran_score, damodaran_key_metrics),
    ]

    pillars = [
        PillarAnalysis(
            pillar_name="The Engine",
            score=pillar_scores["The Engine"],
            metrics=engine_metrics,
            summary=pillar_summaries.get("The Engine", ""),
            red_flags=[],
        ),
        PillarAnalysis(
            pillar_name="The Moat",
            score=pillar_scores["The Moat"],
            metrics=[moat_metric, understandability_metric],
            summary=pillar_summaries.get("The Moat", ""),
            red_flags=filing_red_flags[:3],
        ),
        PillarAnalysis(
            pillar_name="The Fortress",
            score=pillar_scores["The Fortress"],
            metrics=fortress_metrics,
            summary=pillar_summaries.get("The Fortress", ""),
            red_flags=[],
        ),
        PillarAnalysis(
            pillar_name="Alignment",
            score=pillar_scores["Alignment"],
            metrics=alignment_metrics,
            summary=pillar_summaries.get("Alignment", ""),
            red_flags=[],
        ),
    ]

    confidence: str = "high" if not partial else "medium"
    if roic is None and peg is None:
        confidence = "low"

    return CompanyAnalysis(
        ticker=ticker,
        company_name=company_name,
        analysis_date=date.today(),
        filing_date=filing_date,
        filing_type="10-K",
        pillars=pillars,
        gurus=gurus,
        overall_score=overall_score,
        confidence=confidence,  # type: ignore[arg-type]
        errors=errors,
        partial=partial,
    )
