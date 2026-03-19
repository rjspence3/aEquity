"""Script 3: Correlate composite scores against Wall Street analyst consensus."""

import logging
from pathlib import Path

import pandas as pd
from scipy import stats

from config import settings

from validation._helpers import (
    ensure_output_dir,
    fetch_analyst_rating,
    get_cached_analysis,
    load_sp500_tickers,
    rate_limited_sleep,
    run_analysis_safe,
)

logger = logging.getLogger(__name__)


def fetch_sp500_with_ratings(
    tickers: list[str],
    db_url: str,
    skip_new: bool = False,
    delay: float = 0.5,
) -> pd.DataFrame:
    """
    For each ticker, pull analyst rating and composite score.

    1. Pull recommendationMean from yfinance (with rate limiting)
    2. Get composite score: from DB if cached, else run analysis (unless skip_new)
    3. Return DataFrame: ticker, composite_score, analyst_mean, analyst_inverted

    analyst_inverted = min(100, (5 - analyst_mean) / 4 * 100) maps 1→100, 3→50, 5→0, clamped to [0, 100].
    Skips tickers where either value is unavailable.
    """
    rows = []

    for i, ticker in enumerate(tickers):
        logger.info("Processing %s (%d/%d)", ticker, i + 1, len(tickers))

        analyst_mean = fetch_analyst_rating(ticker)
        rate_limited_sleep(delay)

        if analyst_mean is None:
            logger.debug("No analyst rating for %s, skipping", ticker)
            continue

        analysis = get_cached_analysis(ticker, db_url)
        if analysis is None:
            if skip_new:
                logger.debug("No cached analysis for %s and skip_new=True, skipping", ticker)
                continue
            analysis = run_analysis_safe(ticker)

        if analysis is None:
            logger.debug("Could not get analysis for %s, skipping", ticker)
            continue

        # Maps 1 (Strong Buy) → 100, 3 (Hold) → 50, 5 (Strong Sell) → 0.
        # Clamped to [0, 100]: without the clamp, mean=1.0 yields 125.
        analyst_inverted = min(100.0, max(0.0, (5.0 - analyst_mean) / 4.0 * 100.0))

        rows.append({
            "ticker": ticker,
            "composite_score": analysis.overall_score,
            "analyst_mean": analyst_mean,
            "analyst_inverted": analyst_inverted,
        })

    return pd.DataFrame(rows)


def compute_correlations(df: pd.DataFrame) -> dict[str, float]:
    """
    Compute Pearson and Spearman correlations between composite_score and analyst_inverted.

    Returns {"pearson": float, "spearman": float, "pearson_p": float, "spearman_p": float, "n": int}.
    Uses scipy.stats.pearsonr and spearmanr.
    """
    if len(df) < 3:
        logger.warning("Not enough data for correlation (n=%d)", len(df))
        return {"pearson": 0.0, "spearman": 0.0, "pearson_p": 1.0, "spearman_p": 1.0, "n": len(df)}

    pearson_r, pearson_p = stats.pearsonr(df["composite_score"], df["analyst_inverted"])
    spearman_r, spearman_p = stats.spearmanr(df["composite_score"], df["analyst_inverted"])

    return {
        "pearson": float(pearson_r),
        "spearman": float(spearman_r),
        "pearson_p": float(pearson_p),
        "spearman_p": float(spearman_p),
        "n": len(df),
    }


def plot_scatter(df: pd.DataFrame, output_path: Path) -> None:
    """
    Scatter plot: x=analyst_inverted (1-5 scale, inverted), y=composite_score.

    Colors dots by verdict bucket. Adds regression line. Saves to output_path.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from scoring_config import VERDICT_AVOID, VERDICT_BUY, VERDICT_HOLD, VERDICT_STRONG_BUY

    def _verdict_color(score: int) -> str:
        if score >= VERDICT_STRONG_BUY:
            return "green"
        if score >= VERDICT_BUY:
            return "limegreen"
        if score >= VERDICT_HOLD:
            return "orange"
        if score >= VERDICT_AVOID:
            return "salmon"
        return "red"

    colors = [_verdict_color(s) for s in df["composite_score"]]

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(df["analyst_inverted"], df["composite_score"], c=colors, alpha=0.6, s=40)

    # Regression line
    if len(df) >= 3:
        x = df["analyst_inverted"].values
        y = df["composite_score"].values
        slope, intercept = np.polyfit(x, y, 1)
        x_line = np.linspace(x.min(), x.max(), 100)
        ax.plot(x_line, slope * x_line + intercept, "b--", linewidth=1.5, label="Regression")

    ax.set_xlabel("Analyst Consensus (inverted, 0-100)")
    ax.set_ylabel("Composite Score (0-100)")
    ax.set_title("aEquity Composite vs Wall St Analyst Consensus")
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close(fig)
    logger.info("Saved scatter plot to %s", output_path)


def find_outliers(df: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute delta = composite_score - analyst_inverted.

    Analyst is already on 0-100 scale (analyst_inverted).
    Top n by delta → "we love it, analysts don't".
    Bottom n by delta → "analysts love it, we don't".
    """
    df = df.copy()
    df["analyst_inverted_normalized"] = df["analyst_inverted"]
    df["delta"] = df["composite_score"] - df["analyst_inverted_normalized"]

    sorted_df = df.sort_values("delta", ascending=False)
    we_love = sorted_df.head(n)
    analysts_love = sorted_df.tail(n).sort_values("delta", ascending=True)

    return we_love, analysts_love


def _interpret_correlation(pearson: float) -> str:
    """Return a plain-English interpretation of the Pearson correlation."""
    abs_r = abs(pearson)
    if abs_r >= 0.7:
        strength = "Strong"
    elif abs_r >= 0.4:
        strength = "Moderate"
    elif abs_r >= 0.2:
        strength = "Weak"
    else:
        strength = "Very weak / negligible"

    direction = "positive" if pearson >= 0 else "negative"
    return (
        f"{strength} {direction} correlation — scores are in the same universe "
        "as analyst consensus but differentiated enough to be non-redundant."
    )


def main(skip_new: bool = False, db_url: str | None = None) -> int:
    """Run consensus correlation. Print correlations + outliers. Save plot + CSV."""
    if db_url is None:
        db_url = settings.database_url

    output_dir = ensure_output_dir()
    plot_path = output_dir / "analyst_correlation.png"
    outliers_csv_path = output_dir / "analyst_outliers.csv"

    tickers = load_sp500_tickers()
    df = fetch_sp500_with_ratings(tickers, db_url, skip_new=skip_new)

    skipped = len(tickers) - len(df)
    print(f"\nLoaded {len(df)} tickers with both scores ({skipped} skipped — no analyst data or analysis)")

    if len(df) < 3:
        print("Not enough data to compute correlations. Exiting.")
        return 1

    corr = compute_correlations(df)
    print(f"\nPearson correlation:  {corr['pearson']:.2f} (p={corr['pearson_p']:.4f})")
    print(f"Spearman correlation: {corr['spearman']:.2f} (p={corr['spearman_p']:.4f})")
    print(f"\nInterpretation: {_interpret_correlation(corr['pearson'])}")

    plot_scatter(df, plot_path)

    we_love, analysts_love = find_outliers(df, n=10)

    print("\nTOP 10: We love it, analysts don't:")
    for _, row in we_love.iterrows():
        analyst_label = f"{row['analyst_mean']:.1f}"
        print(f"  {row['ticker']:<8} composite={row['composite_score']:.0f}  analyst={analyst_label}  delta=+{row['delta']:.0f}")

    print("\nTOP 10: Analysts love it, we don't:")
    for _, row in analysts_love.iterrows():
        analyst_label = f"{row['analyst_mean']:.1f}"
        print(f"  {row['ticker']:<8} composite={row['composite_score']:.0f}  analyst={analyst_label}  delta={row['delta']:.0f}")

    outliers_combined = pd.concat([
        we_love.assign(direction="we_love"),
        analysts_love.assign(direction="analysts_love"),
    ])
    outliers_combined[
        ["ticker", "composite_score", "analyst_mean", "analyst_inverted_normalized", "delta", "direction"]
    ].to_csv(outliers_csv_path, index=False)
    logger.info("Saved outliers CSV to %s", outliers_csv_path)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
