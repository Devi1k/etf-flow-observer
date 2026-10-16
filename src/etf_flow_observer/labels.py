"""把官方增持和 ETF 份额变化分开。份额变化不是国家队资金。"""

from __future__ import annotations

from etf_flow_observer.errors import ObserverError

OFFICIAL_INCREASE = "official_increase_holding"
ETF_SHARE_CHANGE = "etf_share_change"
FORBIDDEN_LABEL = "国家队"


def refuse_state_team_wording(text: str) -> None:
    if FORBIDDEN_LABEL in text:
        raise ObserverError("禁止把成交、放量或份额变化写成国家队资金")


def prepare_disclosure(*, kind: str, note: str) -> tuple[str, str]:
    refuse_state_team_wording(note)
    refuse_state_team_wording(kind)
    if kind == OFFICIAL_INCREASE:
        raise ObserverError(
            "本阶段没有接入官方增持披露。禁止用份额变化、大额成交或放量填进增持，也禁止写成国家队资金。"
        )
    if kind != ETF_SHARE_CHANGE:
        raise ObserverError(f"未知披露类型 {kind}")
    return kind, note
