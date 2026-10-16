from datetime import date, time
from decimal import Decimal

import pytest

from etf_flow_observer.errors import ObserverError, SimNotReady
from etf_flow_observer.signals import (
    SchedulePiece,
    assess_window,
    percentile_80,
    schedule_entry,
    trigger_long,
)
from etf_flow_observer.sim import book_entry
from etf_flow_observer.timing import assert_entry_after_data, next_entry_timestamp
from etf_flow_observer.universe import FUND_CODES
from tests.conftest import shanghai


def _closed(day: date) -> bool:
    return day.weekday() >= 5


def _pieces(status="ok", authoritative=True, when=None):
    moment = when or shanghai(2026, 10, 16, 16, 30)
    return [
        SchedulePiece(
            fund_code=code,
            shares_status=status,
            nav_status="ok",
            shares_fetched_at=moment,
            nav_fetched_at=moment,
            authoritative_shares=authoritative,
        )
        for code in FUND_CODES
    ]


def test_signal_time_cannot_precede_data_or_use_the_same_close():
    available = shanghai(2026, 10, 16, 16, 30)
    as_of = date(2026, 10, 15)
    with pytest.raises(ObserverError, match="早于或等于"):
        assert_entry_after_data(shanghai(2026, 10, 16, 9, 35), available, as_of)
    with pytest.raises(ObserverError, match="当天"):
        assert_entry_after_data(
            shanghai(2026, 10, 15, 15, 0),
            shanghai(2026, 10, 15, 14, 0),
            as_of,
        )
    same_afternoon = next_entry_timestamp(
        shanghai(2026, 10, 15, 14, 0), time(15, 0), as_of, _closed
    )
    assert same_afternoon == shanghai(2026, 10, 16, 15, 0)
    executable = next_entry_timestamp(available, time(9, 35), as_of, _closed)
    assert executable == shanghai(2026, 10, 19, 9, 35)
    assert executable > available
    assert executable.date() != as_of


def test_evening_or_incomplete_data_is_not_scheduled():
    evening = schedule_entry(
        _pieces(status="provisional_evening", authoritative=False, when=shanghai(2026, 10, 15, 21, 0)),
        as_of=date(2026, 10, 15),
        entry_clock=time(15, 0),
        is_closed_day=_closed,
    )
    assert evening.schedulable is False
    assert evening.executable_at is None

    missing = _pieces()
    missing = [piece for piece in missing if piece.fund_code != "159919"]
    incomplete = schedule_entry(
        missing,
        as_of=date(2026, 10, 15),
        entry_clock=time(9, 35),
        is_closed_day=_closed,
    )
    assert incomplete.schedulable is False

    undecided = schedule_entry(
        _pieces(),
        as_of=date(2026, 10, 15),
        entry_clock=None,
        is_closed_day=_closed,
    )
    assert undecided.schedulable is False
    assert undecided.available_at == shanghai(2026, 10, 16, 16, 30)
    assert undecided.executable_at is None


def test_ready_authoritative_data_schedules_the_next_session_after_it_arrived():
    result = schedule_entry(
        _pieces(),
        as_of=date(2026, 10, 15),
        entry_clock=time(9, 35),
        is_closed_day=_closed,
    )
    assert result.schedulable is True
    assert result.executable_at == shanghai(2026, 10, 19, 9, 35)
    assert result.executable_at > result.available_at


def test_121_raw_rows_do_not_make_the_quantile_window_ready():
    readiness = assess_window(raw_observation_rows=121, complete_prior_indicators=0)
    assert readiness.ready is False
    assert "121" in readiness.reason
    prior = [Decimal(i) for i in range(120)]
    assert assess_window(raw_observation_rows=121, complete_prior_indicators=120).ready is True
    assert percentile_80(prior) > 0
    with pytest.raises(ObserverError, match="120"):
        percentile_80(prior[:-1])
    assert trigger_long(Decimal("-1"), prior) is False
    assert trigger_long(Decimal("1000"), prior) is True


def test_example_simulation_cannot_book(store):
    with pytest.raises(SimNotReady):
        book_entry(
            store,
            {
                "version_id": "",
                "stacking": False,
                "extension": False,
                "hold_trading_days": 5,
                "allow_trial": False,
            },
        )
