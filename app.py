"""Streamlit dashboard for aEquity analysis."""

import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import anthropic
import plotly.graph_objects as go
import streamlit as st

from config import settings
from db.init import get_all_latest, open_db
from models import CompanyAnalysis
from pipeline import analyze_ticker
from scoring_config import MAX_ANALYSES_PER_HOUR
from services.watchlist import (
    add_to_watchlist,
    get_watchlist_item,
    list_watchlist,
    transition_watchlist,
    update_price_targets,
)
from tools.validator import validate_ticker

logger = logging.getLogger(__name__)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="aEquity — Autonomous Equity Analyst",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Rate limiter ──────────────────────────────────────────────────────────────


def _check_rate_limit() -> bool:
    if "analysis_timestamps" not in st.session_state:
        st.session_state.analysis_timestamps = []

    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    st.session_state.analysis_timestamps = [
        ts for ts in st.session_state.analysis_timestamps if ts > hour_ago
    ]

    if len(st.session_state.analysis_timestamps) >= MAX_ANALYSES_PER_HOUR:
        return False

    st.session_state.analysis_timestamps.append(now)
    return True


# ── Chart helpers ─────────────────────────────────────────────────────────────

_SCORE_COLORS = {
    "high": "#DFFF00",
    "medium": "#FFE66D",
    "low": "#FF6B6B",
}


def _score_color(score: int) -> str:
    if score >= 65:
        return "#DFFF00"
    if score >= 40:
        return "#FFE66D"
    return "#FF6B6B"


def _gauge_chart(score: int, title: str) -> go.Figure:
    color = _score_color(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": title, "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar": {"color": color, "thickness": 0.3},
            "bgcolor": "#234D32",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 40], "color": "#234D32"},
                {"range": [40, 65], "color": "#234D32"},
                {"range": [65, 100], "color": "#234D32"},
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
        font_color="#F0FFF0",
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
        font_color="#F0FFF0",
        yaxis={"gridcolor": "#2D6A40", "showgrid": True},
        xaxis={"tickfont": {"size": 11}},
    )
    return fig


# ── Verdict badge ─────────────────────────────────────────────────────────────

_VERDICT_STYLES = {
    "Strong Buy":    ("🟢", "#DFFF00", "#1A4D2E"),
    "Buy":           ("🟩", "#b8e600", "#1A4D2E"),
    "Hold":          ("🟡", "#FFE66D", "#2D2D00"),
    "Avoid":         ("🟠", "#FF9A3C", "#2D1500"),
    "Strong Avoid":  ("🔴", "#FF6B6B", "#2D0000"),
}


def _grade_badge_html(grade: str) -> str:
    """Return a coloured HTML badge for a letter grade."""
    g = (grade or "").strip()
    if g.startswith(("A", "B")):
        bg, text = "#DFFF00", "#1A4D2E"
    elif g.startswith("C"):
        bg, text = "#FFE66D", "#2D2D00"
    else:
        bg, text = "#FF6B6B", "#2D0000"
    return (
        f'<span style="background:{bg};color:{text};padding:2px 8px;'
        f'border-radius:6px;font-weight:700;font-size:13px">{g}</span>'
    )


def _verdict_html(verdict: str) -> str:
    icon, bg, text = _VERDICT_STYLES.get(verdict, ("⚪", "#234D32", "#F0FFF0"))
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
    col_name, col_score, col_grade, col_conf = st.columns([3, 1, 1, 1])
    with col_name:
        st.title(f"{result.company_name}")
        st.caption(
            f"Ticker: **{result.ticker}** · Filing: {result.filing_type}"
            f" ({result.filing_date}) · Analyzed: {result.analysis_date}"
        )
    with col_score:
        st.metric("Overall Score", f"{result.overall_score}/100")
    with col_grade:
        grade_display = result.overall_grade or "—"
        st.caption("Grade")
        if result.overall_grade:
            st.markdown(_grade_badge_html(result.overall_grade), unsafe_allow_html=True)
        else:
            st.markdown("—")
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
            grade_label = f" [{guru.grade}]" if guru.grade else ""
            with st.expander(
                f"{guru.guru_name} — {guru.score}/100{grade_label}",
                expanded=True,
            ):
                badge_row = _verdict_html(guru.verdict)
                if guru.grade:
                    badge_row += "&nbsp;&nbsp;" + _grade_badge_html(guru.grade)
                st.markdown(badge_row, unsafe_allow_html=True)
                st.markdown(f"\n{guru.rationale}")
                if guru.key_metrics:
                    st.divider()
                    _render_metric_table(guru.key_metrics)

    # ── Price Targets ──────────────────────────────────────────────────────────
    if result.price_targets:
        st.divider()
        st.subheader("🎯 Intrinsic Value & Entry Zones")
        pt = result.price_targets

        # Support both old flat shape and new nested shape (backward compat with DB records)
        composite = pt.get("composite") or pt
        by_guru: dict = pt.get("by_guru", {})

        if composite and composite.get("fair_value"):
            fv = composite["fair_value"]
            zones = composite["zones"]
            methods = composite["methods"]

            zone_cols = st.columns(5)
            zone_defs = [
                ("Must Buy", "must_buy", "#DFFF00", "#1A4D2E"),
                ("Compelling", "compelling", "#b8e600", "#1A4D2E"),
                ("Accumulate", "accumulate", "#2D6A40", "#F0FFF0"),
                ("Fair Value", "fair_value", "#FFE66D", "#2D2D00"),
                ("Overvalued", "overvalued", "#FF6B6B", "#2D0000"),
            ]
            for col, (label, key, color, text_color) in zip(zone_cols, zone_defs):
                with col:
                    st.markdown(
                        f"<div style='background:{color};padding:8px;border-radius:6px;"
                        f"text-align:center'><b style='color:{text_color}'>{label}</b><br>"
                        f"<span style='color:{text_color};font-size:1.1em'>${zones[key]:.2f}</span></div>",
                        unsafe_allow_html=True,
                    )

            st.caption(
                f"Fair value: **${fv:.2f}** · Methods used: {composite['methods_used']}/4 · "
                f"Owner Earnings: ${methods.get('owner_earnings') or 0:.2f} · "
                f"Lynch: ${methods.get('lynch') or 0:.2f} · "
                f"Graham: ${methods.get('graham') or 0:.2f} · "
                f"Earnings Power: ${methods.get('earnings_power') or 0:.2f}"
            )

        # ── Guru Entry Prices ───────────────────────────────────────────────────
        if by_guru:
            st.divider()
            st.subheader("📐 Entry Prices by Guru")

            _GURU_LABELS = {
                "buffett": "Warren Buffett",
                "munger": "Charlie Munger",
                "lynch": "Peter Lynch",
                "greenblatt": "Joel Greenblatt",
                "marks": "Howard Marks",
                "graham": "Ben Graham",
                "fisher": "Philip Fisher",
                "smith": "Terry Smith",
            }

            current_price = result.price_targets.get("composite", {}) and None
            # Extract current price from composite methods or from the by_guru pct_away
            # (we reconstruct it from target + pct_away to avoid passing it separately)
            current_price_display: float | None = None
            for entry in by_guru.values():
                t = entry.get("target")
                p = entry.get("pct_away")
                if t and p is not None:
                    current_price_display = round(t * (1 + p / 100.0), 2)
                    break

            # Sort: in-zone first, then by pct_away ascending, None last
            rows = []
            for key, label in _GURU_LABELS.items():
                entry = by_guru.get(key, {})
                target = entry.get("target")
                pct_away = entry.get("pct_away")
                in_zone = entry.get("in_zone")
                rows.append((key, label, target, pct_away, in_zone))

            rows.sort(key=lambda r: (r[3] is None, r[3] if r[3] is not None else 0))

            table_rows_html = ""
            for _, label, target, pct_away, in_zone in rows:
                if target is None:
                    row_bg = "rgba(100,100,100,0.15)"
                    target_str = "N/A"
                    pct_str = "—"
                    status_str = "N/A"
                elif in_zone:
                    row_bg = "rgba(223,255,0,0.20)"
                    target_str = f"${target:.2f}"
                    pct_str = f"{pct_away:+.1f}%"
                    status_str = "✅ BUY"
                elif pct_away is not None and pct_away < 20:
                    row_bg = "rgba(255,160,0,0.15)"
                    target_str = f"${target:.2f}"
                    pct_str = f"{pct_away:+.1f}%"
                    status_str = "🔶 Close"
                else:
                    row_bg = "transparent"
                    target_str = f"${target:.2f}"
                    pct_str = f"+{pct_away:.1f}%" if pct_away is not None else "—"
                    status_str = "⏳ Wait"

                table_rows_html += (
                    f"<tr style='background:{row_bg}'>"
                    f"<td style='padding:6px 10px'>{label}</td>"
                    f"<td style='padding:6px 10px;text-align:right;font-family:monospace'>{target_str}</td>"
                    f"<td style='padding:6px 10px;text-align:right;font-family:monospace'>{pct_str}</td>"
                    f"<td style='padding:6px 10px;text-align:center'>{status_str}</td>"
                    f"</tr>"
                )

            st.markdown(
                "<table style='width:100%;border-collapse:collapse'>"
                "<thead><tr style='border-bottom:1px solid #444'>"
                "<th style='padding:6px 10px;text-align:left'>Guru</th>"
                "<th style='padding:6px 10px;text-align:right'>Buy At</th>"
                "<th style='padding:6px 10px;text-align:right'>vs Current</th>"
                "<th style='padding:6px 10px;text-align:center'>Status</th>"
                f"</tr></thead><tbody>{table_rows_html}</tbody></table>",
                unsafe_allow_html=True,
            )
            if current_price_display:
                st.caption(f"Current price used for % calculations: **${current_price_display:.2f}**")

        # Add to watchlist button
        st.divider()
        st.subheader("📋 Watchlist")
        with open_db(settings.database_url) as conn:
            wl_item = get_watchlist_item(conn, result.ticker)

        if wl_item is None:
            if st.button("+ Add to Watchlist", key="add_watchlist"):
                with open_db(settings.database_url) as conn:
                    wl = add_to_watchlist(conn, result.ticker, result.company_name)
                    update_price_targets(
                        conn, result.ticker,
                        must_buy=zones["must_buy"],
                        compelling=zones["compelling"],
                        accumulate=zones["accumulate"],
                        fair_value=zones["fair_value"],
                    )
                st.success(f"Added {result.ticker} to watchlist (screening)")
                st.rerun()
        else:
            status = wl_item.get("status", "screening")
            st.info(f"On watchlist — Status: **{status.upper()}**")
            status_cols = st.columns(4)
            state_buttons = {
                "Mark Analyzing": "analyzing",
                "Mark Watching": "watching",
                "Mark Buying": "buying",
            }
            for idx, (label, new_state) in enumerate(state_buttons.items()):
                with status_cols[idx]:
                    if st.button(label, key=f"wl_{new_state}"):
                        with open_db(settings.database_url) as conn:
                            transition_watchlist(conn, result.ticker, new_state)
                        st.rerun()

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

@st.cache_data(ttl=300)
def _load_all_analyses() -> list[CompanyAnalysis]:
    """Load and deserialize all analyses from the DB. Cached for 5 minutes."""
    with open_db(settings.database_url) as conn:
        return get_all_latest(conn)


@st.cache_data(ttl=300)
def _fetch_current_prices(tickers: tuple[str, ...]) -> dict[str, float]:
    """Batch-fetch latest close prices via a single yfinance download call.

    Uses a tuple parameter (not list) so Streamlit can hash it for caching.
    Returns a dict of {ticker: price}; missing tickers are omitted.
    """
    if not tickers:
        return {}
    import yfinance as yf
    data = yf.download(list(tickers), period="1d", progress=False, auto_adjust=True)
    if data.empty:
        return {}
    close = data["Close"]
    # Single-ticker download returns a Series; multi returns a DataFrame
    if hasattr(close, "iloc"):
        last_row = close.iloc[-1]
        if hasattr(last_row, "to_dict"):
            return {t: float(v) for t, v in last_row.to_dict().items() if v and not (isinstance(v, float) and v != v)}
        # Series (single ticker)
        return {tickers[0]: float(last_row)} if float(last_row) == float(last_row) else {}
    return {}


def _render_screener() -> None:
    st.subheader("🔍 Stock Screener")
    st.caption("Filter all analysed companies by score. Run `batch.py` to populate.")

    results = _load_all_analyses()

    if not results:
        st.info("No analyses in the database yet. Run `python batch.py --limit 20` to get started.")
        return

    all_tickers = tuple(r.ticker for r in results)
    with st.spinner("Fetching current prices…"):
        current_prices = _fetch_current_prices(all_tickers)

    # Build flat rows for the table
    rows = []
    _guru_col_map = {
        "Buffett": "Warren Buffett",
        "Lynch": "Peter Lynch",
        "Graham": "Ben Graham",
        "Damodaran": "Aswath Damodaran",
        "Munger": "Charlie Munger",
        "Greenblatt": "Joel Greenblatt",
        "Marks": "Howard Marks",
        "Smith": "Terry Smith",
    }
    for r in results:
        guru_map = {g.guru_name: g.score for g in r.gurus}

        # Extract composite fair value — handles both old flat and new nested shapes
        pt = r.price_targets or {}
        composite = pt.get("composite") or pt
        fair_value = composite.get("fair_value") if composite else None
        must_buy = composite.get("zones", {}).get("must_buy") if composite else None

        row: dict = {
            "Ticker": r.ticker,
            "Company": r.company_name,
            "Overall": r.overall_score,
            "Grade": r.overall_grade or "—",
        }
        for short, full in _guru_col_map.items():
            row[short] = guru_map.get(full, 0)
        price_now = current_prices.get(r.ticker)
        vs_fv = (
            round((price_now - fair_value) / fair_value * 100, 1)
            if price_now and fair_value and fair_value > 0
            else None
        )
        if vs_fv is None:
            zone = "—"
        elif vs_fv < 0:
            zone = "🟢"   # price below fair value
        elif vs_fv <= 20:
            zone = "🟡"   # within 20% above fair value
        else:
            zone = "🔴"   # significantly overvalued
        row.update({
            "Price": price_now,
            "Fair Value": fair_value,
            "vs FV %": vs_fv,
            "Zone": zone,
            "Must Buy": must_buy,
            "Confidence": r.confidence,
            "Partial": "⚠" if r.partial else "",
            "Date": str(r.analysis_date),
        })
        rows.append(row)

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        min_overall = st.slider("Min Overall Score", 0, 100, 0, key="screener_overall")
    with filter_col2:
        guru_filter = st.selectbox(
            "Filter by Guru Score ≥",
            ["(none)", *list(_guru_col_map.keys())],
            key="screener_guru",
        )
    with filter_col3:
        min_guru_score = st.slider("Guru Min Score", 0, 100, 0, key="screener_guru_score")

    filtered = [r for r in rows if r["Overall"] >= min_overall]
    if guru_filter != "(none)":
        filtered = [r for r in filtered if r[guru_filter] >= min_guru_score]

    st.caption(f"Showing {len(filtered)} of {len(rows)} companies")
    progress_cols = {
        short: st.column_config.ProgressColumn(short, min_value=0, max_value=100)
        for short in _guru_col_map
    }
    progress_cols["Overall"] = st.column_config.ProgressColumn("Overall", min_value=0, max_value=100)
    progress_cols["Price"] = st.column_config.NumberColumn("Price", format="$%.2f")
    progress_cols["Fair Value"] = st.column_config.NumberColumn("Fair Value", format="$%.2f")
    progress_cols["vs FV %"] = st.column_config.NumberColumn("vs FV %", format="%.1f%%")
    progress_cols["Zone"] = st.column_config.TextColumn("Zone", help="🟢 below FV · 🟡 ≤20% above · 🔴 >20% above")
    progress_cols["Must Buy"] = st.column_config.NumberColumn("Must Buy", format="$%.2f")
    st.dataframe(filtered, use_container_width=True, hide_index=True, column_config=progress_cols)

    # ── Add top N results to watchlist ────────────────────────────────────────
    if filtered:
        st.divider()
        add_col1, add_col2, add_col3 = st.columns([2, 1, 3])
        with add_col1:
            top_n = st.number_input(
                "Top N to add to Watchlist",
                min_value=1, max_value=len(filtered), value=min(20, len(filtered)),
                step=1, key="screener_top_n",
            )
        with add_col2:
            st.write("")  # vertical alignment spacer
            st.write("")
            if st.button("➕ Add to Watchlist", key="screener_add_watchlist"):
                candidates = sorted(filtered, key=lambda r: r["Overall"], reverse=True)[:int(top_n)]
                added, skipped = 0, 0
                # Map ticker → company name from results for the upsert call
                name_map = {r.ticker: r.company_name for r in results}
                with open_db(settings.database_url) as conn:
                    for row in candidates:
                        ticker = row["Ticker"]
                        existing = get_watchlist_item(conn, ticker)
                        if existing:
                            skipped += 1
                        else:
                            add_to_watchlist(conn, ticker, name_map.get(ticker, ""))
                            added += 1
                if added:
                    st.success(f"Added {added} stocks to watchlist (screening). {skipped} already present.")
                else:
                    st.info(f"All {skipped} selected stocks are already on the watchlist.")


# ── Watchlist ─────────────────────────────────────────────────────────────────

_STATUS_COLORS = {
    "screening":  "#2D6A40",
    "analyzing":  "#1A5C35",
    "watching":   "#DFFF00",
    "buying":     "#b8e600",
    "owned":      "#234D32",
    "sold":       "#3D5C40",
    "rejected":   "#FF6B6B",
    "removed":    "#2D3D30",
}


def _render_watchlist() -> None:
    st.subheader("📋 Watchlist")
    st.caption("Track investment candidates through the research pipeline.")

    with open_db(settings.database_url) as conn:
        items = list_watchlist(conn)

    if not items:
        st.info("No stocks on the watchlist yet. Analyze a stock and add it via the Analyze tab.")
        return

    status_filter = st.selectbox(
        "Filter by status",
        ["All", "screening", "analyzing", "watching", "buying", "owned", "sold", "rejected"],
        key="wl_status_filter",
    )
    if status_filter != "All":
        items = [i for i in items if i["status"] == status_filter]

    st.caption(f"Showing {len(items)} items")

    for item in items:
        ticker = item["ticker"]
        status = item["status"]
        color = _STATUS_COLORS.get(status, "#334155")
        fv = item.get("fair_value_price")
        must_buy = item.get("must_buy_price")

        header = (
            f"**{ticker}** — {item.get('name') or ticker} · "
            f"<span style='background:{color};padding:2px 8px;border-radius:10px;"
            f"color:#1A4D2E;font-size:0.85em'>{status.upper()}</span>"
        )
        if fv:
            header += f" · Fair Value: **${fv:.2f}**"
        if must_buy:
            header += f" · Must Buy: **${must_buy:.2f}**"

        with st.expander(f"{ticker} — {status.upper()}", expanded=False):
            st.markdown(header, unsafe_allow_html=True)
            if item.get("notes"):
                st.markdown(f"*{item['notes']}*")

            tran_cols = st.columns(5)
            from services.watchlist import VALID_TRANSITIONS
            valid_next = VALID_TRANSITIONS.get(status, [])
            for idx, next_state in enumerate(valid_next):
                with tran_cols[idx]:
                    if st.button(f"→ {next_state}", key=f"wl_tran_{ticker}_{next_state}"):
                        with open_db(settings.database_url) as conn:
                            transition_watchlist(conn, ticker, next_state)
                        st.rerun()


# ── Macro Radar ───────────────────────────────────────────────────────────────

def _render_macro_radar() -> None:
    st.subheader("🌐 Macro Radar")
    st.caption("Aggregate signals across all analysed companies.")

    results = _load_all_analyses()

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
        font_color="#F0FFF0",
        yaxis={"gridcolor": "#2D6A40"},
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
            marker_color="#FF6B6B",
            text=flag_values,
            textposition="outside",
        ))
        flag_fig.update_layout(
            height=max(260, len(flag_counts) * 35),
            margin={"t": 10, "b": 10, "l": 10, "r": 60},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#F0FFF0",
            xaxis={"gridcolor": "#2D6A40"},
            yaxis={"autorange": "reversed"},
        )
        st.plotly_chart(flag_fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("No risk flags recorded yet.")

    st.divider()

    # ── Top and bottom companies ───────────────────────────────────────────────
    top_col, bot_col = st.columns(2)
    sorted_results = sorted(results, key=lambda r: r.overall_score, reverse=True)

    def _truncate_name(name: str) -> str:
        return name[:25] + "..." if len(name) > 28 else name

    with top_col:
        st.markdown("#### Top 10 Companies")
        top_rows = [
            {"Ticker": r.ticker, "Company": _truncate_name(r.company_name),
             "Score": r.overall_score}
            for r in sorted_results[:10]
        ]
        st.dataframe(top_rows, hide_index=True, use_container_width=True)

    with bot_col:
        st.markdown("#### Bottom 10 Companies")
        bot_rows = [
            {"Ticker": r.ticker, "Company": _truncate_name(r.company_name),
             "Score": r.overall_score}
            for r in sorted_results[-10:]
        ]
        st.dataframe(bot_rows, hide_index=True, use_container_width=True)


# ── Main app ──────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown("""
    <style>
    /* ── Acid Forest Design Tokens ─────────────────────────────────────── */
    :root {
        --bg-base:       #1A4D2E;
        --surface:       #234D32;
        --surface-dark:  #153D24;
        --primary:       #DFFF00;
        --primary-dim:   #b8e600;
        --text-primary:  #F0FFF0;
        --text-muted:    #8FBC8F;
        --danger:        #FF6B6B;
        --warning:       #FFE66D;
        --grid-line:     #2D6A40;
        --outer-radius:  12px;
        --padding:       8px;
        --inner-radius:  calc(var(--outer-radius) - var(--padding));
    }

    /* ── Base ───────────────────────────────────────────────────────────── */
    .stApp {
        background: radial-gradient(ellipse 80% 50% at 50% 0%,
            rgba(223,255,0,0.05) 0%,
            var(--bg-base) 60%);
        color: var(--text-primary);
    }

    /* ── Typography ─────────────────────────────────────────────────────── */
    .stApp .stMarkdown p,
    .stApp .stText,
    .stApp label,
    .stApp .stCaption {
        font-size: calc(14px + 0.5vw);
        color: var(--text-primary);
    }
    .stApp h1, .stApp h2, .stApp h3,
    .stApp .stMarkdown h1, .stApp .stMarkdown h2, .stApp .stMarkdown h3 {
        font-size: calc(18px + 1vw);
        font-weight: 600;
        color: var(--primary);
    }
    .stApp .stCaption p { color: var(--text-muted); font-size: 0.85em; }

    /* ── Metrics ────────────────────────────────────────────────────────── */
    [data-testid="stMetric"] {
        background: var(--surface);
        border-radius: var(--outer-radius);
        border: 1px solid rgba(223,255,0,0.2);
        padding: var(--padding);
    }
    [data-testid="stMetricValue"] { color: var(--primary); }
    [data-testid="stMetricLabel"] { color: var(--text-muted); }

    /* ── Buttons ────────────────────────────────────────────────────────── */
    .stButton > button {
        background: var(--primary) !important;
        color: var(--bg-base) !important;
        border: none !important;
        border-radius: 6px !important;
        min-height: 44px !important;
        font-weight: 600 !important;
    }
    .stButton > button:hover {
        background: var(--primary-dim) !important;
    }

    /* ── Dataframes / Tables ────────────────────────────────────────────── */
    [data-testid="stDataFrame"],
    [data-testid="stDataFrameResizable"] {
        background: var(--surface) !important;
        border-radius: var(--inner-radius);
        border: 1px solid rgba(223,255,0,0.15);
    }
    [data-testid="stDataFrame"] th {
        background: var(--surface-dark) !important;
        color: rgba(223,255,0,0.8) !important;
        font-weight: 600;
    }
    [data-testid="stDataFrame"] td {
        color: var(--text-primary) !important;
    }

    /* ── Tabs ───────────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        background: var(--surface-dark);
        border-radius: var(--outer-radius);
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--text-primary);
        border-radius: var(--inner-radius);
    }
    .stTabs [data-baseweb="tab"]:not([aria-selected="true"]) {
        color: var(--text-primary) !important;
        opacity: 0.7;
    }
    .stTabs [aria-selected="true"] {
        background: var(--primary) !important;
        color: var(--bg-base) !important;
        font-weight: 600;
        opacity: 1;
    }

    /* ── Expanders ──────────────────────────────────────────────────────── */
    [data-testid="stExpander"] {
        background: var(--surface);
        border: 1px solid rgba(223,255,0,0.15);
        border-radius: var(--outer-radius);
    }

    /* ── Sidebar ────────────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: var(--surface-dark);
    }
    [data-testid="stSidebar"] .stMarkdown p { color: var(--text-muted); }

    /* ── Inputs ─────────────────────────────────────────────────────────── */
    .stTextInput > div > div > input,
    .stSelectbox > div > div {
        background: var(--surface) !important;
        color: var(--text-primary) !important;
        border-color: rgba(223,255,0,0.3) !important;
        border-radius: var(--inner-radius) !important;
    }

    /* ── Progress bars (Screener ProgressColumn) ────────────────────────── */
    [role="progressbar"] > div {
        background: var(--primary) !important;
    }

    /* ── Alerts ─────────────────────────────────────────────────────────── */
    [data-testid="stAlert"] { border-radius: var(--inner-radius); }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("## 📈 aEquity — Autonomous Equity Analyst")
    st.caption(
        "Decision-grade intelligence from 10-Ks, financial data,"
        " and the Virtual Investment Committee."
    )
    st.info("⚠️ This is a personal project built for fun. Nothing here is investing advice.", icon=None)

    tab_analyze, tab_screener, tab_watchlist, tab_radar = st.tabs(
        ["Analyze", "Screener", "Watchlist", "Macro Radar"]
    )

    with tab_analyze:
        # ── Access token gate ────────────────────────────────────────────────
        # If ANALYZE_ACCESS_TOKEN is set in the environment, require the user
        # to enter it once per session before analyses can run. This prevents
        # unbounded API spend when the app is deployed publicly on Railway.
        _token_required = bool(settings.analyze_access_token)
        _token_granted = st.session_state.get("access_granted", False)

        if _token_required and not _token_granted:
            st.info("This demo requires an access token to run analyses.")
            entered_token = st.text_input("Access token", type="password", key="token_input")
            if st.button("Unlock", key="token_submit"):
                if entered_token == settings.analyze_access_token:
                    st.session_state["access_granted"] = True
                    st.rerun()
                else:
                    st.error("Invalid access token.")
        else:
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
                st.error(f"Invalid ticker: '{ticker_input}' — use 1–6 uppercase letters, optionally with a dot suffix (e.g. BRK.A).")
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
                        except ValueError:
                            st.error("Invalid ticker or data unavailable for this symbol.")
                            st.session_state.pop("analysis_result", None)
                        except anthropic.AuthenticationError:
                            st.error("API key error — check that ANTHROPIC_API_KEY is set correctly.")
                            st.session_state.pop("analysis_result", None)
                        except anthropic.RateLimitError:
                            st.error("Rate limit reached. Wait a moment and try again.")
                            st.session_state.pop("analysis_result", None)
                        except Exception as exc:
                            logger.error(
                                "Unexpected error analyzing %s: %s", ticker_input, exc, exc_info=True
                            )
                            st.error("Unexpected error. Check logs for details.")
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

    with tab_watchlist:
        _render_watchlist()

    with tab_radar:
        _render_macro_radar()


if __name__ == "__main__":
    main()
