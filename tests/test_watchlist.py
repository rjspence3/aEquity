"""Tests for services/watchlist.py state machine."""

import sqlite3

import pytest

from db.init import init_db, upsert_stock
from services.watchlist import (
    VALID_TRANSITIONS,
    add_to_watchlist,
    check_auto_transitions,
    get_watchlist_item,
    list_watchlist,
    transition_watchlist,
    update_price_targets,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    init_db(c)
    yield c
    c.close()


class TestAddToWatchlist:
    def test_add_returns_dict(self, conn: sqlite3.Connection) -> None:
        result = add_to_watchlist(conn, "AAPL")
        assert isinstance(result, dict)
        assert result["status"] == "screening"

    def test_stock_created(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "MSFT", name="Microsoft Corp")
        row = conn.execute("SELECT name FROM stocks WHERE ticker = 'MSFT'").fetchone()
        assert row["name"] == "Microsoft Corp"

    def test_noop_if_already_present(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL")
        add_to_watchlist(conn, "AAPL")  # second call
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        assert count == 1

    def test_custom_initial_status(self, conn: sqlite3.Connection) -> None:
        result = add_to_watchlist(conn, "AAPL", status="analyzing")
        assert result["status"] == "analyzing"

    def test_invalid_status_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            add_to_watchlist(conn, "AAPL", status="nonsense")


class TestGetWatchlistItem:
    def test_returns_none_for_unknown(self, conn: sqlite3.Connection) -> None:
        assert get_watchlist_item(conn, "ZZZZ") is None

    def test_returns_dict_for_known(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL")
        item = get_watchlist_item(conn, "AAPL")
        assert item is not None
        assert item["status"] == "screening"


class TestListWatchlist:
    def test_empty_list(self, conn: sqlite3.Connection) -> None:
        assert list_watchlist(conn) == []

    def test_lists_all(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL")
        add_to_watchlist(conn, "MSFT")
        items = list_watchlist(conn)
        assert len(items) == 2

    def test_filters_by_status(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL", status="screening")
        add_to_watchlist(conn, "MSFT", status="analyzing")
        screening = list_watchlist(conn, status="screening")
        assert len(screening) == 1
        assert screening[0]["ticker"] == "AAPL"

    def test_list_includes_ticker(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "NVDA")
        items = list_watchlist(conn)
        assert items[0]["ticker"] == "NVDA"


class TestTransitionWatchlist:
    def test_valid_transition_returns_true(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL", status="screening")
        result = transition_watchlist(conn, "AAPL", "analyzing")
        assert result is True

    def test_status_updated_after_transition(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL", status="screening")
        transition_watchlist(conn, "AAPL", "analyzing")
        item = get_watchlist_item(conn, "AAPL")
        assert item["status"] == "analyzing"

    def test_invalid_transition_returns_false(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL", status="screening")
        result = transition_watchlist(conn, "AAPL", "owned")
        assert result is False

    def test_unknown_ticker_returns_false(self, conn: sqlite3.Connection) -> None:
        result = transition_watchlist(conn, "ZZZZ", "analyzing")
        assert result is False

    def test_sold_has_no_valid_transitions(self, conn: sqlite3.Connection) -> None:
        assert VALID_TRANSITIONS["sold"] == []


class TestCheckAutoTransitions:
    def _setup_watching(
        self,
        conn: sqlite3.Connection,
        ticker: str,
        price: float,
        must_buy: float | None = None,
        compelling: float | None = None,
        accumulate: float | None = None,
    ) -> None:
        add_to_watchlist(conn, ticker, status="watching")
        update_price_targets(conn, ticker, must_buy, compelling, accumulate, None)
        stock_id = conn.execute(
            "SELECT id FROM stocks WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()["id"]
        conn.execute(
            "UPDATE stocks SET current_price = ? WHERE id = ?", (price, stock_id)
        )
        conn.commit()

    def test_no_transitions_when_no_targets(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL", status="watching")
        results = check_auto_transitions(conn)
        assert results == []

    def test_watching_to_buying_on_must_buy(self, conn: sqlite3.Connection) -> None:
        self._setup_watching(conn, "AAPL", price=100.0, must_buy=110.0)
        transitions = check_auto_transitions(conn)
        assert len(transitions) == 1
        assert transitions[0]["to_status"] == "buying"
        assert transitions[0]["ticker"] == "AAPL"

    def test_watching_to_buying_on_compelling(self, conn: sqlite3.Connection) -> None:
        self._setup_watching(conn, "MSFT", price=200.0, compelling=210.0)
        transitions = check_auto_transitions(conn)
        assert len(transitions) == 1
        assert transitions[0]["to_status"] == "buying"

    def test_no_transition_when_price_above_targets(self, conn: sqlite3.Connection) -> None:
        self._setup_watching(conn, "AAPL", price=300.0, must_buy=200.0, compelling=250.0)
        transitions = check_auto_transitions(conn)
        assert transitions == []

    def test_buying_to_watching_when_price_above_accumulate(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "TSLA", status="buying")
        update_price_targets(conn, "TSLA", None, None, 150.0, None)
        stock_id = conn.execute(
            "SELECT id FROM stocks WHERE ticker = 'TSLA'"
        ).fetchone()["id"]
        conn.execute("UPDATE stocks SET current_price = 200.0 WHERE id = ?", (stock_id,))
        conn.commit()
        transitions = check_auto_transitions(conn)
        assert len(transitions) == 1
        assert transitions[0]["from_status"] == "buying"
        assert transitions[0]["to_status"] == "watching"

    def test_no_transition_without_current_price(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL", status="watching")
        update_price_targets(conn, "AAPL", 100.0, None, None, None)
        transitions = check_auto_transitions(conn)
        assert transitions == []


class TestUpdatePriceTargets:
    def test_updates_all_targets(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL")
        update_price_targets(conn, "AAPL", 120.0, 135.0, 150.0, 180.0)
        item = get_watchlist_item(conn, "AAPL")
        assert item["must_buy_price"] == pytest.approx(120.0)
        assert item["compelling_buy_price"] == pytest.approx(135.0)
        assert item["accumulate_price"] == pytest.approx(150.0)
        assert item["fair_value_price"] == pytest.approx(180.0)

    def test_partial_update_with_none(self, conn: sqlite3.Connection) -> None:
        add_to_watchlist(conn, "AAPL")
        update_price_targets(conn, "AAPL", 100.0, None, None, None)
        item = get_watchlist_item(conn, "AAPL")
        assert item["must_buy_price"] == pytest.approx(100.0)
        assert item["compelling_buy_price"] is None

    def test_raises_for_unknown_ticker(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            update_price_targets(conn, "ZZZZ", 100.0, None, None, None)
