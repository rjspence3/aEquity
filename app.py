"""Streamlit dashboard for aEquity analysis."""

import json
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from config import settings
from db.init import get_all_latest, open_db
from models import CompanyAnalysis
from pipeline import analyze_ticker
from tools.validator import validate_ticker

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="aEquity — Autonomous Equity Analyst",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Rate limiter ──────────────────────────────────────────────────────────────

_MAX_ANALYSES_PER_HOUR = 20


def _check_rate_limit() -> bool:
    if "analysis_timestamps" not in st.session_state:
        st.session_state.analysis_timestamps = []

    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    st.session_state.analysis_timestamps = [
        ts for ts in st.session_state.analysis_timestamps if ts > hour_ago
    ]

    if len(st.session_state.analysis_timestamps) >= _MAX_ANALYSES_PER_HOUR:
        return False

    st.session_state.analysis_timestamps.append(now)
    return True


# ── Chart helpers ─────────────────────────────────────────────────────────────

_SCORE_COLORS = {
    "high": "#22c55e",
    "medium": "#f59e0b",
    "low": "#ef4444",
}


def _score_color(score: int) -> str:
    if score >= 65:
        return "#22c55e"
    if score >= 40:
        return "#f59e0b"
    return "#ef4444"


def _gauge_chart(score: int, title: str) -> go.Figure:
    color = _score_color(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": title, "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar": {"color": color, "thickness": 0.3},
            "bgcolor": "#1e293b",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 40], "color": "#1e293b"},
                {"range": [40, 65], "color": "#1e293b"},
                {"range": [65, 100], "color": "#1e293b"},
            ],
            "threshold": {
                "line": {"color": color, "width": 3},
                "thickness": 0.75,
                "value": score,
            },
        },
        number={"font": {"size": 32, "color": color}, "suffix": "/100"},
    ))
    fig.update_layout(
        height=180,
        margin={"t": 40, "b": 0, "l": 10, "r": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e8f0",
    )
    return fig


def _bar_chart(labels: list[str], scores: list[int], title: str) -> go.Figure:
    colors = [_score_color(s) for s in scores]
    fig = go.Figure(go.Bar(
        x=labels,
        y=scores,
        marker_color=colors,
        text=scores,
        textposition="outside",
    ))
    fig.update_layout(
        title=title,
        yaxis_range=[0, 110],
        height=280,
        margin={"t": 40, "b": 20, "l": 10, "r": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e8f0",
        yaxis={"gridcolor": "#334155", "showgrid": True},
        xaxis={"tickfont": {"size": 11}},
    )
    return fig


# ── Verdict badge ─────────────────────────────────────────────────────────────

_VERDICT_STYLES = {
    "Strong Buy":    ("🟢", "#14532d", "#bbf7d0"),
    "Buy":           ("🟩", "#166534", "#dcfce7"),
    "Hold":          ("🟡", "#713f12", "#fef9c3"),
    "Avoid":         ("🟠", "#7c2d12", "#ffedd5"),
    "Strong Avoid":  ("🔴", "#7f1d1d", "#fee2e2"),
}


def _verdict_html(verdict: str) -> str:
    icon, bg, text = _VERDICT_STYLES.get(verdict, ("⚪", "#1e293b", "#e2e8f0"))
    return (
        f'<span style="background:{bg};color:{text};padding:3px 10px;'
        f'border-radius:12px;font-weight:600;font-size:13px;">{icon} {verdict}</span>'
    )


# ── Render helpers ────────────────────────────────────────────────────────────

def _render_metric_table(metrics: list) -> None:
    if not metrics:
        st.caption("No quantitative metrics available.")
        return

    rows = []
    for m in metrics:
        confidence_icon = {"high": "✓", "medium": "~", "low": "?"}.get(m.confidence, "?")
        rows.append({
            "Metric": m.metric_name,
            "Raw Value": m.raw_value,
            "Score": f"{m.normalized_score}/100",
            "Confidence": f"{confidence_icon} {m.confidence}",
            "Evidence": m.evidence[:80] + "..." if len(m.evidence) > 80 else m.evidence,
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_analysis(result: CompanyAnalysis) -> None:
    # ── Header ─────────────────────────────────────────────────────────────────
    col_name, col_score, col_conf = st.columns([3, 1, 1])
    with col_name:
        st.title(f"{result.company_name}")
        st.caption(
            f"Ticker: **{result.ticker}** · Filing: {result.filing_type}"
            f" ({result.filing_date}) · Analyzed: {result.analysis_date}"
        )
    with col_score:
        st.metric("Overall Score", f"{result.overall_score}/100")
    with col_conf:
        conf_color = _SCORE_COLORS.get(result.confidence, "#94a3b8")
        st.markdown(
            f"**Confidence:** <span style='color:{conf_color}'>{result.confidence.upper()}</span>",
            unsafe_allow_html=True,
        )

    if result.errors:
        for err in result.errors:
            st.warning(f"⚠ {err}", icon="⚠️")

    st.divider()

    # ── Four Pillars ───────────────────────────────────────────────────────────
    st.subheader("📊 The Four Pillars")
    cols = st.columns(4)
    pillar_map: dict[str, Any] = {p.pillar_name: p for p in result.pillars}
    pillar_order = ["The Engine", "The Moat", "The Fortress", "Alignment"]

    for col, name in zip(cols, pillar_order, strict=False):
        pillar = pillar_map.get(name)
        if pillar:
            with col:
                st.plotly_chart(
                    _gauge_chart(pillar.score, name),
                    use_container_width=True,
                    config={"displayModeBar": False},
                )

    for name in pillar_order:
        pillar = pillar_map.get(name)
        if not pillar:
            continue
        with st.expander(f"{name} — {pillar.score}/100", expanded=False):
            st.markdown(pillar.summary)
            if pillar.red_flags:
                for flag in pillar.red_flags:
                    st.error(f"⚠ {flag}")
            _render_metric_table(pillar.metrics)

    st.divider()

    # ── Guru Scorecards ────────────────────────────────────────────────────────
    st.subheader("🏛️ Virtual Investment Committee")

    guru_names: list[str] = [str(g.guru_name) for g in result.gurus]
    guru_scores = [g.score for g in result.gurus]
    st.plotly_chart(
        _bar_chart(guru_names, guru_scores, "Guru Scores"),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    guru_cols = st.columns(2)
    for idx, guru in enumerate(result.gurus):
        with guru_cols[idx % 2]:
            with st.expander(
                f"{guru.guru_name} — {guru.score}/100",
                expanded=True,
            ):
                st.markdown(_verdict_html(guru.verdict), unsafe_allow_html=True)
                st.markdown(f"\n{guru.rationale}")
                if guru.key_metrics:
                    st.divider()
                    _render_metric_table(guru.key_metrics)

    st.divider()

    # ── Download ───────────────────────────────────────────────────────────────
    json_output = json.dumps(result.model_dump(mode="json"), indent=2, default=str)
    st.download_button(
        label="⬇ Download Full Analysis (JSON)",
        data=json_output,
        file_name=f"aequity_{result.ticker}_{result.analysis_date}.json",
        mime="application/json",
    )


# ── Screener ──────────────────────────────────────────────────────────────────

def _render_screener() -> None:
    st.subheader("🔍 Stock Screener")
    st.caption("Filter all analysed companies by score. Run `batch.py` to populate.")

    with open_db(settings.database_url) as conn:
        results = get_all_latest(conn)

    if not results:
        st.info("No analyses in the database yet. Run `python batch.py --limit 20` to get started.")
        return

    # Build flat rows for the table
    rows = []
    for r in results:
        guru_map = {g.guru_name: g.score for g in r.gurus}
        rows.append({
            "Ticker": r.ticker,
            "Company": r.company_name,
            "Overall": r.overall_score,
            "Buffett": guru_map.get("Warren Buffett", 0),
            "Lynch": guru_map.get("Peter Lynch", 0),
            "Graham": guru_map.get("Ben Graham", 0),
            "Damodaran": guru_map.get("Aswath Damodaran", 0),
            "Confidence": r.confidence,
            "Partial": "⚠" if r.partial else "",
            "Date": str(r.analysis_date),
        })

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        min_overall = st.slider("Min Overall Score", 0, 100, 0, key="screener_overall")
    with filter_col2:
        guru_filter = st.selectbox(
            "Filter by Guru Score ≥",
            ["(none)", "Buffett", "Lynch", "Graham", "Damodaran"],
            key="screener_guru",
        )
    with filter_col3:
        min_guru_score = st.slider("Guru Min Score", 0, 100, 0, key="screener_guru_score")

    filtered = [r for r in rows if r["Overall"] >= min_overall]
    if guru_filter != "(none)":
        filtered = [r for r in filtered if r[guru_filter] >= min_guru_score]

    st.caption(f"Showing {len(filtered)} of {len(rows)} companies")
    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Overall": st.column_config.ProgressColumn("Overall", min_value=0, max_value=100),
            "Buffett": st.column_config.ProgressColumn("Buffett", min_value=0, max_value=100),
            "Lynch": st.column_config.ProgressColumn("Lynch", min_value=0, max_value=100),
            "Graham": st.column_config.ProgressColumn("Graham", min_value=0, max_value=100),
            "Damodaran": st.column_config.ProgressColumn("Damodaran", min_value=0, max_value=100),
        },
    )


# ── Macro Radar ───────────────────────────────────────────────────────────────

def _render_macro_radar() -> None:
    st.subheader("🌐 Macro Radar")
    st.caption("Aggregate signals across all analysed companies.")

    with open_db(settings.database_url) as conn:
        results = get_all_latest(conn)

    if not results:
        st.info("No analyses in the database yet. Run `python batch.py --limit 20` to get started.")
        return

    # ── Summary metrics ────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    scores = [r.overall_score for r in results]
    avg_score = sum(scores) / len(scores)
    strong_buys = sum(1 for r in results if r.overall_score >= 80)
    avoids = sum(1 for r in results if r.overall_score < 30)
    partial_count = sum(1 for r in results if r.partial)

    m1.metric("Companies Analysed", len(results))
    m2.metric("Average Score", f"{avg_score:.1f}/100")
    m3.metric("Strong Buy (≥80)", strong_buys)
    m4.metric("Avoid (<30)", avoids)

    if partial_count:
        st.warning(f"{partial_count} companies have partial analyses (missing 10-K data).")

    st.divider()

    # ── Score distribution ─────────────────────────────────────────────────────
    st.markdown("#### Score Distribution")
    buckets = {"0–20": 0, "21–40": 0, "41–60": 0, "61–80": 0, "81–100": 0}
    for s in scores:
        if s <= 20:
            buckets["0–20"] += 1
        elif s <= 40:
            buckets["21–40"] += 1
        elif s <= 60:
            buckets["41–60"] += 1
        elif s <= 80:
            buckets["61–80"] += 1
        else:
            buckets["81–100"] += 1

    bucket_colors = [_score_color(10), _score_color(30), _score_color(50),
                     _score_color(70), _score_color(90)]
    dist_fig = go.Figure(go.Bar(
        x=list(buckets.keys()),
        y=list(buckets.values()),
        marker_color=bucket_colors,
        text=list(buckets.values()),
        textposition="outside",
    ))
    dist_fig.update_layout(
        height=260,
        margin={"t": 20, "b": 20, "l": 10, "r": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e2e8f0",
        yaxis={"gridcolor": "#334155"},
    )
    st.plotly_chart(dist_fig, use_container_width=True, config={"displayModeBar": False})

    st.divider()

    # ── Average guru scores ────────────────────────────────────────────────────
    st.markdown("#### Average Guru Scores Across Portfolio")
    guru_totals: dict[str, list[int]] = {
        "Warren Buffett": [], "Peter Lynch": [], "Ben Graham": [], "Aswath Damodaran": []
    }
    for r in results:
        for g in r.gurus:
            if g.guru_name in guru_totals:
                guru_totals[g.guru_name].append(g.score)

    guru_avgs = {
        name: int(sum(scores_list) / len(scores_list)) if scores_list else 0
        for name, scores_list in guru_totals.items()
    }
    st.plotly_chart(
        _bar_chart(list(guru_avgs.keys()), list(guru_avgs.values()), ""),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    st.divider()

    # ── Common risk flags ──────────────────────────────────────────────────────
    st.markdown("#### Most Common Risk Flags")
    all_flags: list[str] = []
    for r in results:
        for pillar in r.pillars:
            all_flags.extend(pillar.red_flags)

    if all_flags:
        flag_counts = Counter(all_flags).most_common(10)
        flag_labels = [f[:60] + "…" if len(f) > 60 else f for f, _ in flag_counts]
        flag_values = [count for _, count in flag_counts]
        flag_fig = go.Figure(go.Bar(
            x=flag_values,
            y=flag_labels,
            orientation="h",
            marker_color="#ef4444",
            text=flag_values,
            textposition="outside",
        ))
        flag_fig.update_layout(
            height=max(260, len(flag_counts) * 35),
            margin={"t": 10, "b": 10, "l": 10, "r": 60},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e8f0",
            xaxis={"gridcolor": "#334155"},
            yaxis={"autorange": "reversed"},
        )
        st.plotly_chart(flag_fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("No risk flags recorded yet.")

    st.divider()

    # ── Top and bottom companies ───────────────────────────────────────────────
    top_col, bot_col = st.columns(2)
    sorted_results = sorted(results, key=lambda r: r.overall_score, reverse=True)

    with top_col:
        st.markdown("#### Top 10 Companies")
        top_rows = [
            {"Ticker": r.ticker, "Company": r.company_name[:28], "Score": r.overall_score}
            for r in sorted_results[:10]
        ]
        st.dataframe(top_rows, hide_index=True, use_container_width=True)

    with bot_col:
        st.markdown("#### Bottom 10 Companies")
        bot_rows = [
            {"Ticker": r.ticker, "Company": r.company_name[:28], "Score": r.overall_score}
            for r in sorted_results[-10:]
        ]
        st.dataframe(bot_rows, hide_index=True, use_container_width=True)


# ── Main app ──────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown("""
    <style>
    .stApp { background-color: #0f172a; color: #e2e8f0; }
    .stMetric { background: #1e293b; border-radius: 8px; padding: 12px; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("## 📈 aEquity — Autonomous Equity Analyst")
    st.caption(
        "Decision-grade intelligence from 10-Ks, financial data,"
        " and the Virtual Investment Committee."
    )

    tab_analyze, tab_screener, tab_radar = st.tabs(["Analyze", "Screener", "Macro Radar"])

    with tab_analyze:
        col_input, col_btn = st.columns([3, 1])
        with col_input:
            ticker_input = st.text_input(
                "Ticker Symbol",
                value=st.session_state.get("last_ticker", "AAPL"),
                placeholder="e.g. AAPL",
                label_visibility="collapsed",
            ).upper().strip()
        with col_btn:
            run_clicked = st.button("▶ Run Analysis", type="primary", use_container_width=True)

        ticker_valid = True
        try:
            if ticker_input:
                validate_ticker(ticker_input)
        except ValueError:
            st.error(f"Invalid ticker: '{ticker_input}' — must be 1-5 uppercase letters.")
            ticker_valid = False

        if run_clicked and ticker_valid and ticker_input:
            if not _check_rate_limit():
                st.error("Rate limit reached: max 20 analyses per hour.")
            else:
                st.session_state["last_ticker"] = ticker_input
                with st.spinner(f"Analyzing {ticker_input}…"):
                    start = time.time()
                    try:
                        result = analyze_ticker(ticker_input)
                        st.session_state["analysis_result"] = result
                        elapsed = time.time() - start
                        st.success(f"Analysis complete in {elapsed:.1f}s")
                    except Exception as exc:
                        st.error(f"Analysis failed: {exc}")
                        st.session_state.pop("analysis_result", None)

        cached: CompanyAnalysis | None = st.session_state.get("analysis_result")
        if cached:
            _render_analysis(cached)
        else:
            st.info("Enter a ticker symbol and click **Run Analysis** to begin.")
            with st.expander("ℹ️ How it works", expanded=True):
                st.markdown("""
                **aEquity** analyzes stocks through four lenses:

                | Pillar | What it measures |
                |--------|-----------------|
                | 🔧 **The Engine** | Business quality (ROIC, margins) |
                | 🏰 **The Moat** | Competitive defensibility (text analysis) |
                | 🏦 **The Fortress** | Financial health (debt, FCF) |
                | 🤝 **Alignment** | Governance (insider ownership, capital returns) |

                The **Virtual Investment Committee** applies Buffett, Lynch, Graham, and Damodaran
                scoring formulas using your company's actual financial data.
                """)

    with tab_screener:
        _render_screener()

    with tab_radar:
        _render_macro_radar()


if __name__ == "__main__":
    main()
