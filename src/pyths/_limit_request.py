"""M15纯离线查询编码；可编码不代表独立网络访问已验证。"""

from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import urlencode

type LimitPoolKind = Literal[
    "limit_up",
    "approaching_limit_up",
    "consecutive_limit_up",
    "broken_limit_up",
    "limit_down",
]

# Source defaults observed in M15 windows 10--12. No inferred field IDs.
POOL_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "limit_up": (
        "limit_up_pool",
        "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
        "330324",
    ),
    "approaching_limit_up": (
        "limit_up",
        "199112,10,48,1968584,19,3475914,9003,9004",
        "199112",
    ),
    "consecutive_limit_up": (
        "continuous_limit_pool",
        "199112,10,330329,330325,133971,133970,1968584,3475914,3541450,9004",
        "330329",
    ),
    "broken_limit_up": (
        "open_limit_pool",
        "199112,9002,48,1968584,19,3475914,9003,10,9004",
        "199112",
    ),
    "limit_down": (
        "lower_limit_pool",
        "199112,10,330333,330334,1968584,3475914,9004",
        "330334",
    ),
}


@dataclass(frozen=True)
class LimitFilters:
    """来源市场组合与两个显示选项；不读取账户设置。"""

    markets: tuple[Literal["HS", "GEM2STAR"], ...] = ("HS", "GEM2STAR")
    include_st: bool = False
    include_unopened: bool = False

    def to_wire(self) -> str:
        if (
            not isinstance(self.markets, tuple)
            or not self.markets
            or len(set(self.markets)) != len(self.markets)
            or any(m not in ("HS", "GEM2STAR") for m in self.markets)
        ):
            raise ValueError("invalid limit market selection")
        if type(self.include_st) is not bool or type(self.include_unopened) is not bool:
            raise ValueError("invalid limit filter flag")
        selected: list[str] = [m for m in ("HS", "GEM2STAR") if m in self.markets]
        if self.include_st:
            selected.append("ST")
        if self.include_unopened:
            selected.append("NEW")
        return ",".join(selected)


@dataclass(frozen=True)
class LimitPoolQuery:
    """完整查询上下文；日期必须显式给出，不猜最新来源日。"""

    pool: LimitPoolKind
    trade_date: date
    filters: LimitFilters = LimitFilters()
    sort_field: str | None = None
    order_type: Literal["0", "1"] = "0"


def encode_limit_query(query: LimitPoolQuery, *, page: int = 1) -> str:
    """构造一页固定来源URL；不发送、重试或自动展开下一页。"""
    if not isinstance(query, LimitPoolQuery) or query.pool not in POOL_DEFAULTS:
        raise ValueError("unsupported limit pool")
    if type(query.trade_date) is not date or not isinstance(
        query.filters, LimitFilters
    ):
        raise ValueError("explicit date and typed filters required")
    if type(page) is not int or not 1 <= page <= 10000:
        raise ValueError("invalid limit page")
    path, fields, default_sort = POOL_DEFAULTS[query.pool]
    sort = default_sort if query.sort_field is None else query.sort_field
    if sort not in fields.split(",") or query.order_type not in ("0", "1"):
        raise ValueError("unsupported limit sort")
    params = {
        "page": str(page),
        "limit": "15",
        "field": fields,
        "filter": query.filters.to_wire(),
        "date": query.trade_date.strftime("%Y%m%d"),
        "order_field": sort,
        "order_type": query.order_type,
    }
    return (
        "https://data.10jqka.com.cn/dataapi/limit_up/" + path + "?" + urlencode(params)
    )
