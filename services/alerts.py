"""Price alert creation and triggering."""

import sqlite3

from db.init import get_stock_id, upsert_stock


def create_alert(
    conn: sqlite3.Connection,
    stock_id: int,
    alert_type: str,
    target_price: float,
    condition: str = "below",
) -> int:
    """Create an alert. Returns alert id."""
    if condition not in ("below", "above"):
        raise ValueError(f"condition must be 'below' or 'above', got {condition!r}")

    cursor = conn.execute(
        """
        INSERT INTO alerts (stock_id, alert_type, target_price, condition)
        VALUES (?, ?, ?, ?)
        """,
        (stock_id, alert_type, target_price, condition),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def create_default_alerts(
    conn: sqlite3.Connection,
    ticker: str,
    must_buy: float | None,
    compelling: float | None,
    accumulate: float | None,
) -> list[int]:
    """Create must_buy, compelling, and accumulate alerts for a ticker.

    Returns list of created alert ids.
    """
    stock_id = get_stock_id(conn, ticker)
    if stock_id is None:
        stock_id = upsert_stock(conn, ticker=ticker)

    created_ids: list[int] = []
    targets = [
        ("must_buy", must_buy, "below"),
        ("compelling", compelling, "below"),
        ("accumulate", accumulate, "below"),
    ]
    for alert_type, price, condition in targets:
        if price is not None:
            alert_id = create_alert(
                conn,
                stock_id=stock_id,
                alert_type=alert_type,
                target_price=price,
                condition=condition,
            )
            created_ids.append(alert_id)

    return created_ids


def check_alerts(conn: sqlite3.Connection) -> list[dict]:
    """
    Check all active alerts against current stock prices (from stocks.current_price).

    Marks triggered alerts as 'triggered'. Returns list of triggered alert dicts.
    """
    rows = conn.execute(
        """
        SELECT a.*, s.ticker, s.current_price
        FROM alerts a
        JOIN stocks s ON s.id = a.stock_id
        WHERE a.status = 'active'
          AND s.current_price IS NOT NULL
        """
    ).fetchall()

    triggered: list[dict] = []
    for row in rows:
        alert = dict(row)
        price = alert["current_price"]
        target = alert["target_price"]
        condition = alert["condition"]

        fired = (condition == "below" and price <= target) or (
            condition == "above" and price >= target
        )
        if fired:
            conn.execute(
                """
                UPDATE alerts
                SET status = 'triggered',
                    triggered_at = datetime('now'),
                    triggered_price = ?
                WHERE id = ?
                """,
                (price, alert["id"]),
            )
            conn.commit()
            alert["triggered_price"] = price
            alert["status"] = "triggered"
            triggered.append(alert)

    return triggered


def format_alert_output(alert: dict) -> str:
    """Format a triggered alert as a console-printable string."""
    ticker = alert.get("ticker", "?")
    alert_type = alert.get("alert_type", "?")
    target = alert.get("target_price", 0.0)
    triggered_price = alert.get("triggered_price", alert.get("current_price", 0.0))
    condition = alert.get("condition", "below")
    return (
        f"ALERT [{ticker}] {alert_type}: price {triggered_price:.2f} "
        f"is {condition} target {target:.2f}"
    )
