"""Tests for new db/init.py helpers: upsert_stock, get_stock_id, upsert_financial_snapshot."""

import sqlite3

import pytest

from db.init import (
    get_stock_id,
    init_db,
    upsert_financial_snapshot,
    upsert_stock,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    init_db(c)
    yield c
    c.close()


class TestUpsertStock:
    def test_insert_returns_id(self, conn: sqlite3.Connection) -> None:
        stock_id = upsert_stock(conn, "AAPL")
        assert isinstance(stock_id, int)
        assert stock_id > 0

    def test_ticker_stored_uppercase(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "aapl")
        row = conn.execute("SELECT ticker FROM stocks WHERE ticker = 'AAPL'").fetchone()
        assert row is not None

    def test_insert_with_name_and_price(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "MSFT", name="Microsoft Corp", current_price=420.0)
        row = conn.execute("SELECT * FROM stocks WHERE ticker = 'MSFT'").fetchone()
        assert row["name"] == "Microsoft Corp"
        assert row["current_price"] == pytest.approx(420.0)

    def test_update_returns_same_id(self, conn: sqlite3.Connection) -> None:
        id1 = upsert_stock(conn, "AAPL")
        id2 = upsert_stock(conn, "AAPL", name="Apple Inc")
        assert id1 == id2

    def test_update_name_on_existing(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "AAPL")
        upsert_stock(conn, "AAPL", name="Apple Inc")
        row = conn.execute("SELECT name FROM stocks WHERE ticker = 'AAPL'").fetchone()
        assert row["name"] == "Apple Inc"

    def test_update_price_on_existing(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "AAPL", current_price=100.0)
        upsert_stock(conn, "AAPL", current_price=200.0)
        row = conn.execute("SELECT current_price FROM stocks WHERE ticker = 'AAPL'").fetchone()
        assert row["current_price"] == pytest.approx(200.0)

    def test_price_updated_at_set_when_price_given(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "AAPL", current_price=150.0)
        row = conn.execute("SELECT price_updated_at FROM stocks WHERE ticker = 'AAPL'").fetchone()
        assert row["price_updated_at"] is not None

    def test_unique_constraint(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "AAPL")
        upsert_stock(conn, "AAPL")
        count = conn.execute("SELECT COUNT(*) FROM stocks WHERE ticker = 'AAPL'").fetchone()[0]
        assert count == 1

    def test_kwargs_sector_industry(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "AAPL", sector="Technology", industry="Consumer Electronics")
        row = conn.execute("SELECT sector, industry FROM stocks WHERE ticker = 'AAPL'").fetchone()
        assert row["sector"] == "Technology"
        assert row["industry"] == "Consumer Electronics"


class TestGetStockId:
    def test_returns_none_for_unknown(self, conn: sqlite3.Connection) -> None:
        assert get_stock_id(conn, "ZZZZ") is None

    def test_returns_correct_id(self, conn: sqlite3.Connection) -> None:
        inserted_id = upsert_stock(conn, "NVDA")
        fetched_id = get_stock_id(conn, "NVDA")
        assert fetched_id == inserted_id

    def test_case_insensitive(self, conn: sqlite3.Connection) -> None:
        upsert_stock(conn, "TSLA")
        assert get_stock_id(conn, "tsla") is not None


class TestUpsertFinancialSnapshot:
    def test_inserts_snapshot(self, conn: sqlite3.Connection) -> None:
        stock_id = upsert_stock(conn, "AAPL")
        upsert_financial_snapshot(conn, stock_id, {"roic": 0.25, "roe": 0.30})
        row = conn.execute(
            "SELECT roic, roe, period_type FROM financials WHERE stock_id = ?",
            (stock_id,),
        ).fetchone()
        assert row is not None
        assert row["roic"] == pytest.approx(0.25)
        assert row["roe"] == pytest.approx(0.30)
        assert row["period_type"] == "ttm"

    def test_replaces_existing_snapshot(self, conn: sqlite3.Connection) -> None:
        stock_id = upsert_stock(conn, "AAPL")
        upsert_financial_snapshot(conn, stock_id, {"roic": 0.20})
        upsert_financial_snapshot(conn, stock_id, {"roic": 0.28})
        count = conn.execute(
            "SELECT COUNT(*) FROM financials WHERE stock_id = ?", (stock_id,)
        ).fetchone()[0]
        assert count == 1
        row = conn.execute(
            "SELECT roic FROM financials WHERE stock_id = ?", (stock_id,)
        ).fetchone()
        assert row["roic"] == pytest.approx(0.28)

    def test_null_fields_stored(self, conn: sqlite3.Connection) -> None:
        stock_id = upsert_stock(conn, "AAPL")
        upsert_financial_snapshot(conn, stock_id, {})
        row = conn.execute(
            "SELECT roic FROM financials WHERE stock_id = ?", (stock_id,)
        ).fetchone()
        assert row["roic"] is None


class TestNewTablesCreated:
    def test_all_new_tables_exist(self, conn: sqlite3.Connection) -> None:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in ("stocks", "financials", "watchlist", "alerts", "positions", "transactions"):
            assert table in tables, f"Missing table: {table}"
