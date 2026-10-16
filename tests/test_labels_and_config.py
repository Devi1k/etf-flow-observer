from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from etf_flow_observer.cli import main
from etf_flow_observer.config import load_config
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.labels import ETF_SHARE_CHANGE, OFFICIAL_INCREASE

ROOT = Path(__file__).resolve().parents[1]


def test_example_config_keeps_the_fixed_universe():
    cfg = load_config(ROOT / "config" / "example.toml")
    assert cfg.fund_codes == ["510300", "510310", "510330", "159919"]


def test_config_cannot_swap_the_universe(tmp_path):
    text = (ROOT / "config" / "example.toml").read_text(encoding="utf-8")
    broken = text.replace(
        'fund_codes = ["510300", "510310", "510330", "159919"]',
        'fund_codes = ["510500", "510310", "510330", "159919"]',
        1,
    )
    path = tmp_path / "broken.toml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(ObserverError, match="观察宇宙"):
        load_config(path)


def test_share_change_is_not_an_official_increase_or_state_team(store):
    created = store.add_disclosure(
        fund_code="510300",
        as_of_date="2026-10-15",
        kind=ETF_SHARE_CHANGE,
        note="ETF份额变化，不是现金流入",
        created_at=datetime(2026, 10, 16, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert created > 0
    row = store.conn.execute("SELECT kind, note FROM disclosure_records").fetchone()
    assert row["kind"] == ETF_SHARE_CHANGE
    assert "国家队" not in row["note"]
    with pytest.raises(ObserverError, match="增持"):
        store.add_disclosure(
            fund_code="510300",
            as_of_date="2026-10-15",
            kind=OFFICIAL_INCREASE,
            note="由份额增加推断",
            created_at=datetime(2026, 10, 16, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    with pytest.raises(ObserverError, match="国家队"):
        store.add_disclosure(
            fund_code="510300",
            as_of_date="2026-10-15",
            kind=ETF_SHARE_CHANGE,
            note="这是国家队资金",
            created_at=datetime(2026, 10, 16, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )


def test_sim_check_command_is_blocked():
    code = main(
        [
            "--config",
            str(ROOT / "config" / "example.toml"),
            "sim-check",
            "--sim-config",
            str(ROOT / "config" / "simulation.example.toml"),
        ]
    )
    assert code == 2
