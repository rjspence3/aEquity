"""Tests for services/portfolio.py."""

import sqlite3

import pytest

from db.init import init_db, upsert_stock
from services.portfolio import (
    get_portfolio_summary,
    get_position_detail,
    record_buy,
    record_sell,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    init_db(c)
    yield c
    c.close()


class TestRecordBuy:
    def test_creates_position(self, conn: sqlite3.Connection) -> None:
        position = record_buy(conn, "AAPL", shares=10.0, price=150.0)
        assert position["shares"] == pytest.approx(10.0)
        assert position["avg_cost_basis"] == pytest.approx(150.0)
        assert position["total_cost"] == pytest.approx(1500.0)

    def test_creates_stock_record(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "MSFT", shares=5.0, price=400.0)
        row = conn.execute("SELECT ticker FROM stocks WHERE ticker = 'MSFT'").fetchone()
        assert row is not None

    def test_creates_transaction_record(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=150.0)
        row = conn.execute(
            "SELECT * FROM transactions WHERE transaction_type = 'buy'"
        ).fetchone()
        assert row is not None
        assert row["shares"] == pytest.approx(10.0)
        assert row["price"] == pytest.approx(150.0)
        assert row["total_amount"] == pytest.approx(1500.0)

    def test_adds_to_existing_position(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        position = record_buy(conn, "AAPL", shares=10.0, price=120.0)
        assert position["shares"] == pytest.approx(20.0)
        assert position["avg_cost_basis"] == pytest.approx(110.0)
        assert position["total_cost"] == pytest.approx(2200.0)

    def test_weighted_average_cost_basis(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=5.0, price=100.0)
        position = record_buy(conn, "AAPL", shares=15.0, price=140.0)
        # (5*100 + 15*140) / 20 = (500 + 2100) / 20 = 130
        assert position["avg_cost_basis"] == pytest.approx(130.0)

    def test_entry_zone_stored(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=150.0, entry_zone="must_buy")
        row = conn.execute(
            "SELECT entry_zone FROM transactions WHERE transaction_type = 'buy'"
        ).fetchone()
        assert row["entry_zone"] == "must_buy"

    def test_invalid_shares_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="shares"):
            record_buy(conn, "AAPL", shares=-5.0, price=150.0)

    def test_invalid_price_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="price"):
            record_buy(conn, "AAPL", shares=5.0, price=0.0)


class TestRecordSell:
    def test_records_sell_transaction(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        txn = record_sell(conn, "AAPL", shares=5.0, price=150.0)
        assert txn["transaction_type"] == "sell"
        assert txn["shares"] == pytest.approx(5.0)
        assert txn["price"] == pytest.approx(150.0)

    def test_reduces_position_shares(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        record_sell(conn, "AAPL", shares=4.0, price=150.0)
        row = conn.execute(
            "SELECT shares FROM positions p JOIN stocks s ON s.id = p.stock_id WHERE s.ticker = 'AAPL'"
        ).fetchone()
        assert row["shares"] == pytest.approx(6.0)

    def test_removes_position_when_fully_sold(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        record_sell(conn, "AAPL", shares=10.0, price=150.0)
        count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        assert count == 0

    def test_calculates_realized_gain(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        txn = record_sell(conn, "AAPL", shares=10.0, price=150.0)
        assert txn["realized_gain"] == pytest.approx(500.0)

    def test_calculates_realized_loss(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=200.0)
        txn = record_sell(conn, "AAPL", shares=10.0, price=150.0)
        assert txn["realized_gain"] == pytest.approx(-500.0)

    def test_raises_when_no_position(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "AAPL")
        with pytest.raises(ValueError, match="No position"):
            record_sell(conn, "AAPL", shares=5.0, price=150.0)

    def test_raises_when_overselling(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=5.0, price=100.0)
        with pytest.raises(ValueError, match="Cannot sell"):
            record_sell(conn, "AAPL", shares=10.0, price=150.0)

    def test_raises_when_no_stock(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="No stock"):
            record_sell(conn, "ZZZZ", shares=1.0, price=100.0)


class TestGetPortfolioSummary:
    def test_empty_portfolio(self, conn: sqlite3.Connection) -> None:
        summary = get_portfolio_summary(conn)
        assert summary["position_count"] == 0
        assert summary["total_invested"] == 0.0
        assert summary["total_current_value"] == 0.0

    def test_basic_summary(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        upsert_stock(conn, "AAPL", current_price=150.0)
        summary = get_portfolio_summary(conn)
        assert summary["position_count"] == 1
        assert summary["total_invested"] == pytest.approx(1000.0)
        assert summary["total_current_value"] == pytest.approx(1500.0)
        assert summary["total_unrealized_gain"] == pytest.approx(500.0)
        assert summary["total_unrealized_gain_pct"] == pytest.approx(50.0)

    def test_fallback_to_cost_basis_when_no_price(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        # No current_price set → effective_price == avg_cost_basis
        summary = get_portfolio_summary(conn)
        assert summary["total_current_value"] == pytest.approx(1000.0)
        assert summary["total_unrealized_gain"] == pytest.approx(0.0)

    def test_multiple_positions(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        record_buy(conn, "MSFT", shares=5.0, price=200.0)
        summary = get_portfolio_summary(conn)
        assert summary["position_count"] == 2
        assert summary["total_invested"] == pytest.approx(2000.0)

    def test_realized_gains_ytd(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        record_sell(conn, "AAPL", shares=10.0, price=150.0)
        summary = get_portfolio_summary(conn)
        assert summary["realized_gains_ytd"] == pytest.approx(500.0)


class TestGetPositionDetail:
    def test_returns_none_for_unknown(self, conn: sqlite3.Connection) -> None:
        assert get_position_detail(conn, "ZZZZ") is None

    def test_returns_none_when_no_position(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "AAPL")
        assert get_position_detail(conn, "AAPL") is None

    def test_returns_position_with_transactions(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        record_buy(conn, "AAPL", shares=5.0, price=120.0)
        detail = get_position_detail(conn, "AAPL")
        assert detail is not None
        assert detail["shares"] == pytest.approx(15.0)
        assert len(detail["transactions"]) == 2

    def test_includes_unrealized_gain(self, conn: sqlite3.Connection) -> None:
        record_buy(conn, "AAPL", shares=10.0, price=100.0)
        upsert_stock(conn, "AAPL", current_price=120.0)
        detail = get_position_detail(conn, "AAPL")
        assert detail["unrealized_gain"] == pytest.approx(200.0)
        assert detail["unrealized_gain_pct"] == pytest.approx(20.0)
