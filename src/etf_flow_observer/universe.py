"""固定观察宇宙。名单不按表现更换，配置也不能改。"""

from __future__ import annotations

from dataclasses import dataclass

from etf_flow_observer.errors import ObserverError


@dataclass(frozen=True)
class Fund:
    code: str
    name: str
    exchange: str
    share_source: str
    nav_source: str


FUNDS: tuple[Fund, ...] = (
    Fund("510300", "华泰柏瑞沪深300ETF", "SSE", "sse_shares", "huatai_nav_table"),
    Fund("510310", "易方达沪深300ETF", "SSE", "sse_shares", "efunds_nav"),
    Fund("510330", "华夏沪深300ETF", "SSE", "sse_shares", "chinaamc_nav"),
    Fund("159919", "嘉实沪深300ETF", "SZSE", "szse_shares", "jsfund_nav"),
)

FUND_BY_CODE: dict[str, Fund] = {fund.code: fund for fund in FUNDS}
FUND_CODES: tuple[str, ...] = tuple(fund.code for fund in FUNDS)
SSE_SHARE_CODES: tuple[str, ...] = tuple(fund.code for fund in FUNDS if fund.exchange == "SSE")


def ensure_known(code: str) -> Fund:
    fund = FUND_BY_CODE.get(code)
    if fund is None:
        raise ObserverError(f"{code} 不在固定宇宙内，不能拿别的基金来替换")
    return fund


def ensure_fixed_list(codes: list[str]) -> None:
    if list(codes) != list(FUND_CODES):
        raise ObserverError(
            "观察宇宙已固定为 510300、510310、510330、159919，配置不能增删或换序"
        )


def is_full_universe(codes: set[str]) -> bool:
    return codes == set(FUND_CODES)
