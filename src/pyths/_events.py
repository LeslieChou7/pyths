"""固定M14只读来源；每次显式单页，不自动展开。"""

import time
from datetime import UTC, datetime

from ._event_codec import decode_anomalies, decode_trading_status
from ._event_models import (
    StockAnomalyCursor,
    StockAnomalyKind,
    StockAnomalyPage,
    TradingStatusCursor,
    TradingStatusKind,
    TradingStatusPage,
)
from ._http import request

ANOMALY_SOURCE = (
    "https://dq.10jqka.com.cn//fuyao/stock_halt_monitor/monitor_stock/v1/list"
)
STATUS_SOURCE = "https://data.hexin.cn/Tfp/"


def _page(
    owner: object,
    kind: str,
    cursor: StockAnomalyCursor | TradingStatusCursor | None,
    cls: type[StockAnomalyCursor] | type[TradingStatusCursor],
) -> int:
    if cursor is None:
        return 1
    if (
        not isinstance(cursor, cls)
        or cursor._owner is not owner
        or cursor._kind != kind
        or type(cursor._page) is not int
        or cursor._page != 2
    ):
        raise ValueError("cursor does not belong to this query or supported page range")
    return cursor._page


def query_anomalies(
    *,
    owner: object,
    kind: StockAnomalyKind,
    page: StockAnomalyCursor | None,
    timeout: float,
    connect_timeout: float,
) -> StockAnomalyPage:
    """当前/历史默认来源；页范围另经真实验证，不猜测历史日期。"""
    if kind not in ("current", "history"):
        raise ValueError("unsupported anomaly kind")
    if kind == "current" and page is not None:
        raise ValueError("current anomalies only support the first page")
    number = _page(owner, kind, page, StockAnomalyCursor)
    wire = "monitor" if kind == "current" else "history"
    response = request(
        f"{ANOMALY_SOURCE}?date_type={wire}&page_num={number}",
        deadline=time.monotonic() + timeout,
        connect_timeout=connect_timeout,
        headers={"Accept": "application/json"},
    )
    items, total = decode_anomalies(response.body)
    offset = (number - 1) * 20
    more = (
        None
        if offset + len(items) > total
        or (len(items) < 20 and offset + len(items) < total)
        else offset + len(items) < total
    )
    continuation = (
        StockAnomalyCursor(owner, kind, 2)
        if kind == "history" and number == 1 and more is True
        else None
    )
    return StockAnomalyPage(
        kind, items, total, datetime.now(UTC), ANOMALY_SOURCE, more, continuation
    )


def query_status(
    *,
    owner: object,
    kind: TradingStatusKind,
    page: TradingStatusCursor | None,
    timeout: float,
    connect_timeout: float,
) -> TradingStatusPage:
    """两种原生列表分别返回，满页只表示可尝试已验证续页。"""
    if kind not in ("suspension", "resumption"):
        raise ValueError("unsupported trading status kind")
    number = _page(owner, kind, page, TradingStatusCursor)
    path = "tpLatest" if kind == "suspension" else "fpLatest"
    response = request(
        f"{STATUS_SOURCE}{path}/page/{number}/",
        deadline=time.monotonic() + timeout,
        connect_timeout=connect_timeout,
        headers={"Accept": "application/json"},
    )
    items = decode_trading_status(response.body)
    more = False if not items else None
    continuation = (
        TradingStatusCursor(owner, kind, 2)
        if number == 1 and len(items) == 10
        else None
    )
    return TradingStatusPage(
        kind,
        items,
        datetime.now(UTC),
        STATUS_SOURCE + path,
        has_more=more,
        next_page=continuation,
    )
