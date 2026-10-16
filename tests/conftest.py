from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from etf_flow_observer.pipeline import ingest_points
from etf_flow_observer.storage import Store

SH = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def store(tmp_path):
    database = Store(tmp_path / "observer.sqlite", tmp_path / "raw")
    yield database
    database.close()


def shanghai(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SH)


def ingest(store, points, now, phase=None, closures=()):
    return ingest_points(
        store,
        points,
        now=now,
        phase_override=phase,
        closures=set(closures),
        abnormal_ratio=Decimal("0.20"),
        split_ratio=Decimal("0.50"),
        morning_start=time(8, 0),
        session_close=time(15, 0),
    )
