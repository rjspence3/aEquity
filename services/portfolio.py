"""Portfolio position tracking and P&L calculation."""

import sqlite3

from db.init import get_stock_id, upsert_stock


def record_buy(
    conn: sqlite3.Connection,
    ticker: str,
    shares: float,
    price: float,
    entry_zone: str | None = None,
    reason: str | None = None,
) -> dict:
    """Record a purchase.

    - Upserts stock
    - Creates or updates position (avg cost basis via weighted average)
    - Creates transaction record
    Returns updated position as dict.
    """
    if shares <= 0:
        raise ValueError(f"shares must be positive, got {shares}")
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")

    stock_id = upsert_stock(conn, ticker=ticker)
    total_amount = shares * price

    existing_position = conn.execute(
        "SELECT * FROM positions WHERE stock_id = ?", (stock_id,)
    ).fetchone()

    if existing_position:
        old_shares = existing_position["shares"]
        old_cost = existing_position["avg_cost_basis"]
        new_shares = old_shares + shares
        new_avg_cost = (old_shares * old_cost + shares * price) / new_shares
        new_total_cost = existing_position["total_cost"] + total_amount
        conn.execute(
            """
            UPDATE positions
            SET shares = ?,
                avg_cost_basis = ?,
                total_cost = ?,
                updated_at = datetime('now')
            WHERE stock_id = ?
            """,
            (new_shares, new_avg_cost, new_total_cost, stock_id),
        )
        position_id = existing_position["id"]
    else:
        cursor = conn.execute(
            """
            INSERT INTO positions
                (stock_id, shares, avg_cost_basis, total_cost, entry_zone, first_purchase_date)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (stock_id, shares, price, total_amount, entry_zone),
        )
        position_id = cursor.lastrowid

    conn.execute(
        """
        INSERT INTO transactions
            (stock_id, position_id, transaction_type, shares, price, total_amount, entry_zone, reason)
        VALUES (?, ?, 'buy', ?, ?, ?, ?, ?)
        """,
        (stock_id, position_id, shares, price, total_amount, entry_zone, reason),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM positions WHERE stock_id = ?", (stock_id,)
    ).fetchone()
    return dict(row)


def record_sell(
    conn: sqlite3.Connection,
    ticker: str,
    shares: float,
    price: float,
    reason: str | None = None,
) -> dict:
    """Record a sale.

    - Looks up position
    - Calculates realized gain (FIFO approximation: price - avg_cost_basis) * shares
    - Updates position shares (removes if fully sold)
    - Creates transaction record
    Returns transaction as dict.
    Raises ValueError if position not found or selling more than held.
    """
    if shares <= 0:
        raise ValueError(f"shares must be positive, got {shares}")
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")

    stock_id = get_stock_id(conn, ticker)
    if stock_id is None:
        raise ValueError(f"No stock found for ticker {ticker!r}")

    position = conn.execute(
        "SELECT * FROM positions WHERE stock_id = ?", (stock_id,)
    ).fetchone()
    if position is None:
        raise ValueError(f"No position found for {ticker!r}")

    if shares > position["shares"]:
        raise ValueError(
            f"Cannot sell {shares} shares of {ticker!r}; only {position['shares']} held"
        )

    total_amount = shares * price
    realized_gain = (price - position["avg_cost_basis"]) * shares

    position_id = position["id"]
    remaining_shares = position["shares"] - shares

    # Insert the sell transaction before any position delete to avoid FK violations.
    # Use NULL for position_id when position will be removed (fully sold out).
    tx_position_id = position_id if remaining_shares > 0 else None
    cursor = conn.execute(
        """
        INSERT INTO transactions
            (stock_id, position_id, transaction_type, shares, price, total_amount, reason, realized_gain)
        VALUES (?, ?, 'sell', ?, ?, ?, ?, ?)
        """,
        (stock_id, tx_position_id, shares, price, total_amount, reason, realized_gain),
    )

    if remaining_shares <= 0:
        # Null out the position_id FK on all remaining historical buy transactions
        # before deleting the position row, since the schema has no ON DELETE SET NULL.
        conn.execute(
            "UPDATE transactions SET position_id = NULL WHERE position_id = ?",
            (position_id,),
        )
        conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
    else:
        new_total_cost = remaining_shares * position["avg_cost_basis"]
        conn.execute(
            """
            UPDATE positions
            SET shares = ?,
                total_cost = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (remaining_shares, new_total_cost, position_id),
        )

    conn.commit()

    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return dict(row)


def get_portfolio_summary(conn: sqlite3.Connection) -> dict:
    """Return a portfolio-level summary with P&L calculations.

    Uses stocks.current_price for current value; falls back to avg_cost_basis
    when current_price is NULL.
    """
    positions = conn.execute(
        """
        SELECT p.*, s.ticker, s.name,
               COALESCE(s.current_price, p.avg_cost_basis) AS effective_price
        FROM positions p
        JOIN stocks s ON s.id = p.stock_id
        ORDER BY p.total_cost DESC
        """
    ).fetchall()

    position_list = []
    total_invested = 0.0
    total_current_value = 0.0

    for row in positions:
        pos = dict(row)
        current_value = pos["shares"] * pos["effective_price"]
        unrealized_gain = current_value - pos["total_cost"]
        unrealized_gain_pct = (
            (unrealized_gain / pos["total_cost"] * 100) if pos["total_cost"] else 0.0
        )
        pos["current_value"] = current_value
        pos["unrealized_gain"] = unrealized_gain
        pos["unrealized_gain_pct"] = unrealized_gain_pct
        position_list.append(pos)
        total_invested += pos["total_cost"]
        total_current_value += current_value

    total_unrealized_gain = total_current_value - total_invested
    total_unrealized_gain_pct = (
        (total_unrealized_gain / total_invested * 100) if total_invested else 0.0
    )

    # Realized gains year-to-date: sum realized_gain from sell transactions this year
    ytd_row = conn.execute(
        """
        SELECT COALESCE(SUM(realized_gain), 0.0) AS ytd
        FROM transactions
        WHERE transaction_type = 'sell'
          AND strftime('%Y', transaction_date) = strftime('%Y', 'now')
          AND realized_gain IS NOT NULL
        """
    ).fetchone()
    realized_gains_ytd = float(ytd_row["ytd"]) if ytd_row else 0.0

    return {
        "positions": position_list,
        "total_invested": total_invested,
        "total_current_value": total_current_value,
        "total_unrealized_gain": total_unrealized_gain,
        "total_unrealized_gain_pct": total_unrealized_gain_pct,
        "realized_gains_ytd": realized_gains_ytd,
        "position_count": len(position_list),
    }


def get_position_detail(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """Return position with full transaction history. None if no position."""
    stock_id = get_stock_id(conn, ticker)
    if stock_id is None:
        return None

    position_row = conn.execute(
        """
        SELECT p.*, s.ticker, s.name,
               COALESCE(s.current_price, p.avg_cost_basis) AS effective_price
        FROM positions p
        JOIN stocks s ON s.id = p.stock_id
        WHERE p.stock_id = ?
        """,
        (stock_id,),
    ).fetchone()
    if position_row is None:
        return None

    position = dict(position_row)
    current_value = position["shares"] * position["effective_price"]
    position["current_value"] = current_value
    position["unrealized_gain"] = current_value - position["total_cost"]
    position["unrealized_gain_pct"] = (
        (position["unrealized_gain"] / position["total_cost"] * 100)
        if position["total_cost"]
        else 0.0
    )

    transaction_rows = conn.execute(
        """
        SELECT * FROM transactions
        WHERE stock_id = ?
        ORDER BY transaction_date DESC
        """,
        (stock_id,),
    ).fetchall()
    position["transactions"] = [dict(r) for r in transaction_rows]

    return position
