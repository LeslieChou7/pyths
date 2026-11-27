"""按实际来源组合M8快照，各来源保留独立时间与失败。"""

import time
from collections.abc import Sequence
from datetime import datetime
from typing import cast

from ._market_breadth import query_breadth
from ._market_models import (
    ComponentResult,
    MarketBreadth,
    MarketComponentError,
    MarketComponentMeta,
    MarketFundFlow,
    MarketLimitCounts,
    MarketOverview,
    MarketSizeComparison,
    MarketTurnover,
)
from ._market_size import query_size
from .errors import (
    ThsAuthenticationError,
    ThsError,
    ThsNetworkError,
    ThsProtocolError,
    ThsRateLimitError,
)

COMPONENTS = ("breadth", "limit_counts", "turnover", "fund_flow", "size_comparison")


def validate_selection(
    scope: str, components: Sequence[str], allow_partial: bool
) -> tuple[str, ...]:
    """仅开放冻结范围；拒绝重复、空选择及误传单字符串。"""
    if (
        scope != "m8_baseline"
        or type(allow_partial) is not bool
        or isinstance(components, (str, bytes))
        or not isinstance(components, (tuple, list))
        or not components
        or any(not isinstance(c, str) or c not in COMPONENTS for c in components)
        or len(set(components)) != len(components)
    ):
        raise ValueError("unsupported market overview selection")
    return tuple(components)


def _error(error: ThsError, *, deadline: float) -> MarketComponentError:
    if isinstance(error, ThsNetworkError):
        return MarketComponentError(
            "timeout" if time.monotonic() >= deadline else "network"
        )
    if isinstance(error, ThsAuthenticationError):
        return MarketComponentError("authentication")
    if isinstance(error, ThsRateLimitError):
        return MarketComponentError("rate_limit")
    if isinstance(error, ThsProtocolError):
        return MarketComponentError("protocol")
    return MarketComponentError("business")


def query_overview(
    *,
    scope: str,
    components: Sequence[str],
    allow_partial: bool,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int,
) -> MarketOverview:
    """同次调用对统计来源去重；所有来源及重试共用同一截止时间。"""
    selected = validate_selection(scope, components, allow_partial)
    result: dict[str, ComponentResult[object]] = {}
    for group in (
        ("breadth", "limit_counts"),
        ("turnover",),
        ("fund_flow",),
        ("size_comparison",),
    ):
        wanted = tuple(c for c in group if c in selected)
        if not wanted:
            continue
        try:
            if time.monotonic() >= deadline:
                raise ThsNetworkError("market overview: deadline exceeded")
            received: datetime
            if group[0] == "breadth":
                breadth, limits, received, label = query_breadth(
                    endpoint=endpoint,
                    app_config=app_config,
                    app_info=app_info,
                    connect_timeout=connect_timeout,
                    deadline=deadline,
                    retries=retries,
                )
                meta = MarketComponentMeta(
                    "hs_datacenter_ztdt",
                    received,
                    source_time_label=label,
                    scope_description="来源1A0001/16；统计成分未确认",
                    unknowns=("统计集合及tp含义未知", "时分标签缺少来源日期"),
                )
                values: dict[str, object] = {"breadth": breadth, "limit_counts": limits}
                for name in wanted:
                    result[name] = ComponentResult("ok", values[name], meta)
            elif group[0] == "size_comparison":
                sizes, received = query_size(
                    endpoint=endpoint,
                    app_config=app_config,
                    app_info=app_info,
                    connect_timeout=connect_timeout,
                    deadline=deadline,
                    retries=retries,
                )
                result["size_comparison"] = ComponentResult(
                    "ok",
                    sizes,
                    MarketComponentMeta(
                        "1264:1B0300|1B0852",
                        received,
                        scope_description="App以沪深300/中证1000当前涨跌幅作大小盘对比",
                        unknowns=("来源时间未知", "指数样本和加权算法未研究"),
                    ),
                )
            elif group[0] == "fund_flow":
                from ._market_fund import query_fund

                flow, received = query_fund(
                    endpoint=endpoint,
                    app_config=app_config,
                    app_info=app_info,
                    connect_timeout=connect_timeout,
                    deadline=deadline,
                    retries=retries,
                )
                result["fund_flow"] = ComponentResult(
                    "ok",
                    flow,
                    MarketComponentMeta(
                        "1229:DDE:1A0001/16+399001/32",
                        received,
                        scope_description="App两路DDE末值按float32汇总",
                        unknowns=(
                            "币种及资金分类算法未知",
                            "两来源时间分别保留，非原子快照",
                        ),
                    ),
                )
            else:
                from ._market_turnover import query_turnover

                turnover, received = query_turnover(
                    endpoint=endpoint,
                    app_config=app_config,
                    app_info=app_info,
                    connect_timeout=connect_timeout,
                    deadline=deadline,
                    retries=retries,
                )
                result["turnover"] = ComponentResult(
                    "ok",
                    turnover,
                    MarketComponentMeta(
                        "1229+1271:883957/48",
                        received,
                        source_time=turnover.source_time,
                        source_time_label=turnover.source_time_label,
                        scope_description="App来源883957/48的成交额及上一交易日比较",
                        unknowns=("统计集合及币种未知", "交易日仅覆盖冻结2026年度日历"),
                    ),
                )
        except ThsError as error:
            if not allow_partial:
                raise
            for name in wanted:
                result[name] = ComponentResult(
                    "error", error=_error(error, deadline=deadline)
                )
    return MarketOverview(
        breadth=cast(
            ComponentResult[MarketBreadth], result.get("breadth", ComponentResult())
        ),
        limit_counts=cast(
            ComponentResult[MarketLimitCounts],
            result.get("limit_counts", ComponentResult()),
        ),
        turnover=cast(
            ComponentResult[MarketTurnover], result.get("turnover", ComponentResult())
        ),
        fund_flow=cast(
            ComponentResult[MarketFundFlow], result.get("fund_flow", ComponentResult())
        ),
        size_comparison=cast(
            ComponentResult[MarketSizeComparison],
            result.get("size_comparison", ComponentResult()),
        ),
    )
