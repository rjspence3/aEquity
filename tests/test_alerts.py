"""Tests for services/alerts.py."""

import sqlite3

import pytest

from db.init import init_db, upsert_stock
from services.alerts import (
    check_alerts,
    create_alert,
    create_default_alerts,
    format_alert_output,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    init_db(c)
    yield c
    c.close()


@pytest.fixture()
def stock_id(conn: sqlite3.Connection) -> int:
    return upsert_stock(conn, "AAPL", current_price=150.0)


class TestCreateAlert:
    def test_returns_id(self, conn: sqlite3.Connection, stock_id: int) -> None:
        alert_id = create_alert(conn, stock_id, "must_buy", 120.0)
        assert isinstance(alert_id, int)
        assert alert_id > 0

    def test_stored_correctly(self, conn: sqlite3.Connection, stock_id: int) -> None:
        alert_id = create_alert(conn, stock_id, "compelling", 130.0, condition="below")
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["alert_type"] == "compelling"
        assert row["target_price"] == pytest.approx(130.0)
        assert row["condition"] == "below"
        assert row["status"] == "active"

    def test_default_condition_is_below(self, conn: sqlite3.Connection, stock_id: int) -> None:
        alert_id = create_alert(conn, stock_id, "custom", 200.0)
        row = conn.execute("SELECT condition FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["condition"] == "below"

    def test_above_condition(self, conn: sqlite3.Connection, stock_id: int) -> None:
        alert_id = create_alert(conn, stock_id, "custom", 200.0, condition="above")
        row = conn.execute("SELECT condition FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["condition"] == "above"

    def test_invalid_condition_raises(self, conn: sqlite3.Connection, stock_id: int) -> None:
        with pytest.raises(ValueError, match="condition"):
            create_alert(conn, stock_id, "must_buy", 100.0, condition="sideways")


class TestCreateDefaultAlerts:
    def test_creates_three_alerts(self, conn: sqlite3.Connection) -> None:
        ids = create_default_alerts(conn, "AAPL", must_buy=100.0, compelling=120.0, accumulate=140.0)
        assert len(ids) == 3

    def test_creates_only_non_none(self, conn: sqlite3.Connection) -> None:
        ids = create_default_alerts(conn, "AAPL", must_buy=100.0, compelling=None, accumulate=None)
        assert len(ids) == 1

    def test_creates_stock_if_missing(self, conn: sqlite3.Connection) -> None:
        create_default_alerts(conn, "NVDA", must_buy=500.0, compelling=None, accumulate=None)
        row = conn.execute("SELECT ticker FROM stocks WHERE ticker = 'NVDA'").fetchone()
        assert row is not None

    def test_all_none_returns_empty(self, conn: sqlite3.Connection) -> None:
        ids = create_default_alerts(conn, "AAPL", must_buy=None, compelling=None, accumulate=None)
        assert ids == []


class TestCheckAlerts:
    def test_no_alerts_when_empty(self, conn: sqlite3.Connection) -> None:
        assert check_alerts(conn) == []

    def test_triggers_below_alert(self, conn: sqlite3.Connection) -> None:
        # price=100, target=120 below → should trigger
        stock_id = upsert_stock(conn, "AAPL", current_price=100.0)
        create_alert(conn, stock_id, "must_buy", 120.0, condition="below")
        triggered = check_alerts(conn)
        assert len(triggered) == 1
        assert triggered[0]["ticker"] == "AAPL"

    def test_does_not_trigger_when_above_target(self, conn: sqlite3.Connection) -> None:
        # price=200, target=120 below → should NOT trigger
        stock_id = upsert_stock(conn, "AAPL", current_price=200.0)
        create_alert(conn, stock_id, "must_buy", 120.0, condition="below")
        triggered = check_alerts(conn)
        assert triggered == []

    def test_triggers_above_alert(self, conn: sqlite3.Connection) -> None:
        # price=250, target=200 above → should trigger
        stock_id = upsert_stock(conn, "AAPL", current_price=250.0)
        create_alert(conn, stock_id, "custom", 200.0, condition="above")
        triggered = check_alerts(conn)
        assert len(triggered) == 1

    def test_alert_marked_triggered(self, conn: sqlite3.Connection) -> None:
        stock_id = upsert_stock(conn, "AAPL", current_price=100.0)
        alert_id = create_alert(conn, stock_id, "must_buy", 120.0)
        check_alerts(conn)
        row = conn.execute("SELECT status FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["status"] == "triggered"

    def test_already_triggered_not_re_triggered(self, conn: sqlite3.Connection) -> None:
        stock_id = upsert_stock(conn, "AAPL", current_price=100.0)
        create_alert(conn, stock_id, "must_buy", 120.0)
        check_alerts(conn)  # trigger once
        triggered_again = check_alerts(conn)  # should be empty now
        assert triggered_again == []

    def test_no_price_skipped(self, conn: sqlite3.Connection) -> None:
        # stock with no current_price should be skipped gracefully
        stock_id = upsert_stock(conn, "AAPL")  # no price
        create_alert(conn, stock_id, "must_buy", 120.0)
        triggered = check_alerts(conn)
        assert triggered == []


class TestFormatAlertOutput:
    def test_formats_below_alert(self) -> None:
        alert = {
            "ticker": "AAPL",
            "alert_type": "must_buy",
            "target_price": 120.0,
            "triggered_price": 115.0,
            "condition": "below",
        }
        output = format_alert_output(alert)
        assert "AAPL" in output
        assert "must_buy" in output
        assert "120.00" in output
        assert "115.00" in output

    def test_handles_missing_keys_gracefully(self) -> None:
        output = format_alert_output({})
        assert isinstance(output, str)
