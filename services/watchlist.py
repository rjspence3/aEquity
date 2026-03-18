"""Watchlist state machine for tracking investment candidates."""

import sqlite3

from db.init import upsert_stock

VALID_STATES = [
    "screening",
    "analyzing",
    "watching",
    "buying",
    "owned",
    "sold",
    "rejected",
    "removed",
]

VALID_TRANSITIONS: dict[str, list[str]] = {
    "screening": ["analyzing"],
    "analyzing": ["watching", "rejected"],
    "watching": ["buying", "removed"],
    "buying": ["owned", "watching"],
    "owned": ["sold", "watching"],
    "sold": [],
    "rejected": ["screening"],
    "removed": ["screening"],
}


def add_to_watchlist(
    conn: sqlite3.Connection,
    ticker: str,
    name: str | None = None,
    status: str = "screening",
) -> dict:
    """Add stock to watchlist. Returns watchlist row as dict. No-op if already present."""
    if status not in VALID_STATES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {VALID_STATES}")

    stock_id = upsert_stock(conn, ticker=ticker, name=name)

    existing = conn.execute(
        "SELECT * FROM watchlist WHERE stock_id = ?", (stock_id,)
    ).fetchone()
    if existing:
        return dict(existing)

    conn.execute(
        """
        INSERT INTO watchlist (stock_id, status)
        VALUES (?, ?)
        """,
        (stock_id, status),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM watchlist WHERE stock_id = ?", (stock_id,)
    ).fetchone()
    return dict(row)


def get_watchlist_item(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """Return watchlist row as dict, or None."""
    row = conn.execute(
        """
        SELECT w.* FROM watchlist w
        JOIN stocks s ON s.id = w.stock_id
        WHERE s.ticker = ?
        """,
        (ticker.upper(),),
    ).fetchone()
    return dict(row) if row else None


def list_watchlist(
    conn: sqlite3.Connection, status: str | None = None
) -> list[dict]:
    """Return all watchlist items, optionally filtered by status."""
    if status is not None:
        rows = conn.execute(
            """
            SELECT w.*, s.ticker, s.name, s.current_price
            FROM watchlist w
            JOIN stocks s ON s.id = w.stock_id
            WHERE w.status = ?
            ORDER BY w.updated_at DESC
            """,
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT w.*, s.ticker, s.name, s.current_price
            FROM watchlist w
            JOIN stocks s ON s.id = w.stock_id
            ORDER BY w.updated_at DESC
            """,
        ).fetchall()
    return [dict(row) for row in rows]


def transition_watchlist(
    conn: sqlite3.Connection,
    ticker: str,
    new_status: str,
    trigger: str = "manual",
) -> bool:
    """Attempt a state transition. Validates against VALID_TRANSITIONS. Returns True on success."""
    item = get_watchlist_item(conn, ticker)
    if item is None:
        return False

    current_status = item["status"]
    allowed = VALID_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        return False

    conn.execute(
        """
        UPDATE watchlist
        SET status = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (new_status, item["id"]),
    )
    conn.commit()
    return True


def check_auto_transitions(conn: sqlite3.Connection) -> list[dict]:
    """
    Check all active watchlist items for price-driven state transitions.

    Rules:
    - watching -> buying: current_price <= must_buy_price OR current_price <= compelling_buy_price
    - buying -> watching: current_price > accumulate_price (when accumulate_price is set)

    Returns list of dicts describing each transition that occurred.
    """
    active_statuses = ("watching", "buying")
    placeholders = ", ".join("?" * len(active_statuses))
    rows = conn.execute(
        f"""
        SELECT w.*, s.ticker, s.current_price
        FROM watchlist w
        JOIN stocks s ON s.id = w.stock_id
        WHERE w.status IN ({placeholders})
        """,
        active_statuses,
    ).fetchall()

    transitions: list[dict] = []
    for row in rows:
        item = dict(row)
        price = item.get("current_price")
        if price is None:
            continue

        status = item["status"]
        if status == "watching":
            must_buy = item.get("must_buy_price")
            compelling = item.get("compelling_buy_price")
            triggered = (must_buy is not None and price <= must_buy) or (
                compelling is not None and price <= compelling
            )
            if triggered:
                conn.execute(
                    """
                    UPDATE watchlist
                    SET status = 'buying', updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (item["id"],),
                )
                conn.commit()
                transitions.append(
                    {
                        "ticker": item["ticker"],
                        "from_status": "watching",
                        "to_status": "buying",
                        "trigger": "price_target",
                        "current_price": price,
                    }
                )

        elif status == "buying":
            accumulate = item.get("accumulate_price")
            if accumulate is not None and price > accumulate:
                conn.execute(
                    """
                    UPDATE watchlist
                    SET status = 'watching', updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (item["id"],),
                )
                conn.commit()
                transitions.append(
                    {
                        "ticker": item["ticker"],
                        "from_status": "buying",
                        "to_status": "watching",
                        "trigger": "price_above_accumulate",
                        "current_price": price,
                    }
                )

    return transitions


def update_price_targets(
    conn: sqlite3.Connection,
    ticker: str,
    must_buy: float | None,
    compelling: float | None,
    accumulate: float | None,
    fair_value: float | None,
) -> None:
    """Update price target columns on a watchlist row."""
    item = get_watchlist_item(conn, ticker)
    if item is None:
        raise ValueError(f"Ticker {ticker!r} not found in watchlist")

    conn.execute(
        """
        UPDATE watchlist
        SET must_buy_price = ?,
            compelling_buy_price = ?,
            accumulate_price = ?,
            fair_value_price = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (must_buy, compelling, accumulate, fair_value, item["id"]),
    )
    conn.commit()
