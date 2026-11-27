"""固定龙虎榜只读来源；每次调用有总截止时间，不隐式展开全页详情。"""

import re
import time
from datetime import UTC, date, datetime
from urllib.parse import urlencode

from ._dragon_codec import (
    decode_dragon_calendar,
    decode_dragon_detail,
    decode_dragon_events,
    decode_dragon_list,
)
from ._dragon_models import (
    DragonTigerCursor,
    DragonTigerDetail,
    DragonTigerEntryRef,
    DragonTigerEvent,
    DragonTigerEventRef,
    DragonTigerPage,
)
from ._http import request
from .errors import ThsNetworkError

_BASE = "https://data.10jqka.com.cn/dataapi/transaction"


def _get(
    path: str,
    *,
    params: dict[str, str | int],
    deadline: float,
    connect_timeout: float,
    retries: int,
) -> tuple[bytes, datetime]:
    url = _BASE + path + ("?" + urlencode(params) if params else "")
    for attempt in range(retries + 1):
        try:
            if time.monotonic() >= deadline:
                raise ThsNetworkError("dragon tiger: deadline exceeded")
            response = request(url, deadline=deadline, connect_timeout=connect_timeout)
            return response.body, datetime.now(UTC)
        except ThsNetworkError:
            if attempt == retries:
                raise
    raise ThsNetworkError("dragon tiger: retry budget exhausted")


def validate_list(
    owner: object, trade_date: date, page: DragonTigerCursor | None
) -> tuple[int, int]:
    """日期必须显式传入，续页只能用于同客户端及同日期。"""
    if type(trade_date) is not date:
        raise ValueError("explicit trade_date must be a date")
    if page is None:
        return 1, 50
    if (
        not isinstance(page, DragonTigerCursor)
        or page._owner is not owner
        or page.request_date != trade_date
        or type(page._page) is not int
        or not 2 <= page._page <= 100
        or page._size != 50
    ):
        raise ValueError("cursor does not belong to this query")
    return page._page, page._size


def validate_ref(owner: object, ref: DragonTigerEntryRef | DragonTigerEventRef) -> None:
    """来源引用不能跨客户端使用，也不能接受任意证券参数。"""
    if (
        not isinstance(ref, (DragonTigerEntryRef, DragonTigerEventRef))
        or ref._owner is not owner
    ):
        raise ValueError("reference does not belong to this client")
    if (
        not isinstance(ref.stock_code, str)
        or re.fullmatch(r"[0-9]{6}", ref.stock_code) is None
        or not isinstance(ref.market, str)
        or re.fullmatch(r"[0-9]{1,16}", ref.market) is None
        or type(ref.request_date) is not date
        or type(ref.range_days) is not int
        or ref.range_days not in (1, 3, 10, 30)
    ):
        raise ValueError("invalid source reference")
    if isinstance(ref, DragonTigerEventRef) and (
        type(ref.start_date) is not date
        or type(ref.end_date) is not date
        or ref.start_date > ref.end_date
        or ref.end_date != ref.request_date
        or not isinstance(ref.range_type, str)
        or re.fullmatch(r"[0-9]{1,16}", ref.range_type) is None
        or not ref.reasons
    ):
        raise ValueError("invalid complete event reference")


def query_list(
    *,
    owner: object,
    trade_date: date,
    page: DragonTigerCursor | None,
    deadline: float,
    connect_timeout: float,
    retries: int,
) -> DragonTigerPage:
    number, size = validate_list(owner, trade_date, page)
    body, received = _get(
        "/market/v1/trade_day",
        params={},
        deadline=deadline,
        connect_timeout=connect_timeout,
        retries=retries,
    )
    calendar = decode_dragon_calendar(body, received_at=received)
    if trade_date not in calendar.trade_days:
        raise ValueError(
            "date outside observed source calendar; trading status unknown"
        )
    body, received = _get(
        "/stock/v1/list",
        params={
            "order_field": "hot_rank",
            "order_type": "asc",
            "date": trade_date.isoformat(),
            "filter": "",
            "page": number,
            "size": size,
            "module": "all",
            "order_null_greater": 1,
        },
        deadline=deadline,
        connect_timeout=connect_timeout,
        retries=retries,
    )
    return decode_dragon_list(
        body,
        owner=owner,
        request_date=trade_date,
        page=number,
        size=size,
        received_at=received,
        calendar=calendar,
    )


def query_events(
    *,
    owner: object,
    entry: DragonTigerEntryRef,
    deadline: float,
    connect_timeout: float,
    retries: int,
) -> tuple[DragonTigerEvent, ...]:
    if not isinstance(entry, DragonTigerEntryRef):
        raise ValueError("unsupported entry reference")  # noqa: TRY004
    validate_ref(owner, entry)
    body, received = _get(
        "/stock/v1/info",
        params={"code": entry.stock_code, "date": entry.request_date.isoformat()},
        deadline=deadline,
        connect_timeout=connect_timeout,
        retries=retries,
    )
    return decode_dragon_events(body, owner=owner, entry=entry, received_at=received)


def query_detail(
    *,
    owner: object,
    event: DragonTigerEventRef,
    deadline: float,
    connect_timeout: float,
    retries: int,
) -> DragonTigerDetail:
    if not isinstance(event, DragonTigerEventRef):
        raise ValueError("unsupported event reference")  # noqa: TRY004
    validate_ref(owner, event)
    body, received = _get(
        "/stock/v1/info",
        params={"code": event.stock_code, "date": event.request_date.isoformat()},
        deadline=deadline,
        connect_timeout=connect_timeout,
        retries=retries,
    )
    return decode_dragon_detail(body, owner=owner, event=event, received_at=received)
