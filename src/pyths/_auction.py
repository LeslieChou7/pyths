"""集合竞价当日首屏查询。"""

import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal

from . import _http
from ._auction_codec import (
    AuctionSector,
    AuctionWirePage,
    decode_auction_ranking,
    decode_auction_sectors,
)

type AuctionRankingKind = Literal["one_price", "yesterday_limit_up", "weak_to_strong"]
_ROUTES = {
    "one_price": ("limit_board", "imbalance"),
    "yesterday_limit_up": ("yesterday_limit_up", ""),
    "weak_to_strong": ("weak_to_strong", "warnTimestamp"),
}


@dataclass(frozen=True)
class AuctionRankingPage(AuctionWirePage):
    """原序首屏，附请求日期和 UTC 接收时间；来源日期保留在原始行。"""

    kind: AuctionRankingKind
    request_date: date
    received_at: datetime


def query_auction_ranking(
    kind: AuctionRankingKind,
    trade_date: date,
    *,
    timeout: float,
    connect_timeout: float,
) -> AuctionRankingPage:
    if not isinstance(kind, str) or kind not in _ROUTES:
        raise ValueError("unsupported auction ranking kind")
    if type(trade_date) is not date:
        raise ValueError("explicit auction date required")
    if trade_date != datetime.now(timezone(timedelta(hours=8))).date():
        raise ValueError("only the current Shanghai date supports this ranking route")
    route, sort_field = _ROUTES[kind]
    params = {
        "date": trade_date.isoformat(),
        "page_num": 1,
        "page_size": 20,
        "sort": 0,
        "sort_field": sort_field,
        "filter": None,
    }
    response = _http.request(
        f"https://eq.10jqka.com.cn/call_auction_v2/stock_chance/v1/real_time_list/{route}",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=json.dumps(params).encode("utf-8"),
        deadline=time.monotonic() + timeout,
        connect_timeout=connect_timeout,
        expected_json=True,
    )
    received_at = datetime.now(UTC)
    page = decode_auction_ranking(response.body)
    return AuctionRankingPage(
        page.columns,
        page.rows,
        page.total,
        page.current_page,
        kind,
        trade_date,
        received_at,
    )


type AuctionSectorSide = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class AuctionSectorSnapshot:
    """单侧来源快照，接收时间为 UTC，来源未回显交易日。"""

    side: AuctionSectorSide
    request_date: date
    received_at: datetime
    sectors: tuple[AuctionSector, ...]


def query_auction_sectors(
    side: AuctionSectorSide,
    trade_date: date,
    *,
    deadline: float,
    connect_timeout: float,
) -> AuctionSectorSnapshot:
    if side not in ("bullish", "bearish") or type(trade_date) is not date:
        raise ValueError("explicit auction side and date required")
    route = 1 if side == "bullish" else 2
    response = _http.request(
        f"https://eq.10jqka.com.cn/call_auction_v2/variation/v1/get_block_list/{route}?date={trade_date.isoformat()}",
        deadline=deadline,
        connect_timeout=connect_timeout,
        expected_json=True,
    )
    received_at = datetime.now(UTC)
    return AuctionSectorSnapshot(
        side, trade_date, received_at, decode_auction_sectors(response.body)
    )
