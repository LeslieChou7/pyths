"""M10龙虎榜纯离线解码；来源与范围见研究仓库dragon-tiger规格。"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, NoReturn, cast

from ._dragon_models import (
    DragonTigerCalendar,
    DragonTigerCursor,
    DragonTigerDetail,
    DragonTigerEntry,
    DragonTigerEntryRef,
    DragonTigerEvent,
    DragonTigerEventRef,
    DragonTigerPage,
    DragonTigerReason,
    DragonTigerSeat,
    DragonTigerStatus,
)
from .errors import ThsBusinessError, ThsProtocolError

MAX_BODY = 4 * 1024 * 1024
MAX_ROWS = 10_000
_GROUPS = {1: "one", 3: "three", 10: "ten", 30: "thirty"}


def _invalid() -> NoReturn:
    raise ThsProtocolError("dragon tiger: invalid or mismatched response")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    if len(pairs) > 128:
        _invalid()
    for key, value in pairs:
        if key in result or len(key) > 128:
            _invalid()
        result[key] = value
    return result


def _check(value: object, depth: int = 0) -> None:
    if depth > 32:
        _invalid()
    if isinstance(value, dict):
        for item in value.values():
            _check(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            _invalid()
        for item in value:
            _check(item, depth + 1)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        _invalid()
    return cast(dict[str, object], value)


def _list(value: object, maximum: int = MAX_ROWS) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        _invalid()
    return cast(list[object], value)


def _load(body: bytes) -> dict[str, object]:
    if not isinstance(body, bytes) or not body or len(body) > MAX_BODY:
        _invalid()
    try:
        root = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=Decimal,
            parse_constant=lambda _: _invalid(),
        )
        _check(root)
    except (ValueError, UnicodeError, RecursionError):
        _invalid()
    obj = _object(root)
    status = obj.get("status_code")
    if type(status) is not int:
        _invalid()
    if status != 0:
        raise ThsBusinessError("dragon tiger: business rejection")
    if "succeed" in obj and obj["succeed"] is not True:
        _invalid()
    return _object(obj.get("data"))


def _text(value: object, maximum: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        _invalid()
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _int(value: object, minimum: int = 0, maximum: int = 10_000_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid()
    return value


def _date(value: object) -> date:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None
    ):
        _invalid()
    try:
        return date.fromisoformat(value)
    except ValueError:
        _invalid()


def _request_date(value: date) -> None:
    if type(value) is not date:
        raise ValueError("explicit date required")


def _identity(market: object, code: object) -> tuple[str, str]:
    market_text, code_text = _text(market, 16), _text(code, 6)
    if (
        re.fullmatch(r"[0-9]{1,16}", market_text) is None
        or re.fullmatch(r"[0-9]{6}", code_text) is None
    ):
        _invalid()
    return market_text, code_text


def _amount(row: dict[str, object], key: str) -> Decimal | None:
    if key not in row:
        _invalid()
    raw = row[key]
    if raw is None:
        return None
    if type(raw) is int:
        result = Decimal(raw)
    elif isinstance(raw, Decimal):
        result = raw
    else:
        _invalid()
    if not result.is_finite() or result.copy_abs() > Decimal("1e30"):
        _invalid()
    return result


def decode_dragon_calendar(
    body: bytes, *, received_at: datetime
) -> DragonTigerCalendar:
    """解析来源日期覆盖；不以请求端本机日期判定交易状态。"""
    data = _load(body)
    days = tuple(_date(item) for item in _list(data.get("trade_day_list")))
    last = _date(data.get("last_date"))
    if not days or tuple(sorted(set(days))) != days or last != days[-1]:
        _invalid()
    updated = data.get("last_update_status")
    if type(updated) is not bool:
        _invalid()
    stamp = data.get("time")
    if stamp is not None:
        stamp = _int(stamp, maximum=10**16)
    return DragonTigerCalendar(days, last, updated, stamp, received_at)


def _status(
    calendar: DragonTigerCalendar | None, day: date, rows: int
) -> DragonTigerStatus:
    if calendar is None:
        return "unknown"
    if day == calendar.last_date and not calendar.last_update_status:
        if rows:
            _invalid()
        return "pending"
    # Previous dates are not labelled published by inference from last update.
    return "unknown"


def decode_dragon_list(
    body: bytes,
    *,
    owner: object,
    request_date: date,
    received_at: datetime,
    page: int = 1,
    size: int = 50,
    calendar: DragonTigerCalendar | None = None,
) -> DragonTigerPage:
    """解析固定all列表，保留重复证券和请求日期上下文。"""
    _request_date(request_date)
    if (
        type(page) is not int
        or not 1 <= page <= 200_000
        or size != 50
        or type(size) is not int
    ):
        raise ValueError("unsupported dragon tiger page")
    data = _load(body)
    if (
        data.get("module") != "all"
        or _int(data.get("page"), 1) != page
        or _int(data.get("size"), 1) != size
    ):
        _invalid()
    total = _int(data.get("count"))
    if "stock_count" not in data:
        _invalid()
    count = None if data["stock_count"] is None else _int(data["stock_count"])
    rows = _list(data.get("items"), size)
    start = (page - 1) * size
    if (
        (count is not None and count > total)
        or start > total
        or len(rows) != min(size, total - start)
    ):
        _invalid()
    items = []
    for item in rows:
        row = _object(item)
        market, code = _identity(row.get("market_id"), row.get("stock_code"))
        span = _int(row.get("range_days"), 1, 30)
        if span not in _GROUPS:
            _invalid()
        rank = row.get("hot_rank")
        if rank is not None:
            rank = _int(rank, 1)
        items.append(
            DragonTigerEntry(
                DragonTigerEntryRef(owner, market, code, request_date, span),
                _text(row.get("stock_name")),
                _amount(row, "buy_value"),
                _amount(row, "sell_value"),
                _amount(row, "net_value"),
                _amount(row, "change"),
                _amount(row, "net_rate"),
                rank,
                _optional_text(row.get("limit_reason")),
            )
        )
    has_more = start + len(rows) < total
    cursor = (
        DragonTigerCursor(owner, request_date, page + 1, size) if has_more else None
    )
    return DragonTigerPage(
        tuple(items),
        total,
        count,
        page,
        size,
        cursor,
        has_more,
        _status(calendar, request_date, len(rows)),
        request_date,
        received_at,
    )


def _reasons(value: object) -> tuple[DragonTigerReason, ...]:
    result = tuple(
        DragonTigerReason(
            _text((obj := _object(item)).get("id"), 128), _text(obj.get("content"))
        )
        for item in _list(value, 64)
    )
    if not result or len(set(result)) != len(result):
        _invalid()
    return result


def _seats(
    value: object, direction: Literal["buy", "sell"]
) -> tuple[DragonTigerSeat, ...]:
    seats = []
    for item in _list(value, 100):
        row = _object(item)
        seats.append(
            DragonTigerSeat(
                _text(row.get("id"), 128),
                _optional_text(row.get("org_id")),
                _text(row.get("name")),
                _optional_text(row.get("short_name")),
                direction,
                _int(row.get("rank_value"), 1, 100),
                _amount(row, "buy_value"),
                _amount(row, "sell_value"),
                _amount(row, "net_value"),
            )
        )
    if len({seat.rank for seat in seats}) != len(seats):
        _invalid()
    return tuple(seats)


def _key(ref: DragonTigerEventRef) -> tuple[object, ...]:
    return (
        ref.market,
        ref.stock_code,
        ref.request_date,
        ref.range_days,
        ref.range_type,
        ref.start_date,
        ref.end_date,
        tuple(sorted((reason.id, reason.content) for reason in ref.reasons)),
    )


def _collection(
    body: bytes,
    *,
    owner: object,
    market: str,
    code: str,
    request_date: date,
    range_days: int,
    received_at: datetime,
) -> tuple[DragonTigerDetail, ...]:
    _identity(market, code)
    _request_date(request_date)
    if type(range_days) is not int or range_days not in _GROUPS:
        raise ValueError("unsupported dragon tiger event range")
    data = _load(body)
    if _identity(data.get("market_id"), data.get("stock_code")) != (market, code):
        _invalid()
    name = _text(data.get("stock_name"))
    groups = _object(data.get("details"))
    for group in _GROUPS.values():
        _list(groups.get(group), 100)
    result = []
    for item in _list(groups[_GROUPS[range_days]], 100):
        row = _object(item)
        start, end = _date(row.get("start_date")), _date(row.get("end_date"))
        if start > end or end != request_date:
            _invalid()
        range_type = _text(row.get("range_type"), 16)
        if re.fullmatch(r"[0-9]{1,16}", range_type) is None:
            _invalid()
        reasons = _reasons(row.get("reason"))
        ref = DragonTigerEventRef(
            owner,
            market,
            code,
            request_date,
            range_days,
            range_type,
            start,
            end,
            reasons,
        )
        result.append(
            DragonTigerDetail(
                ref,
                name,
                reasons,
                _amount(row, "buy_value"),
                _amount(row, "sell_value"),
                _amount(row, "net_value"),
                _seats(row.get("buy_items"), "buy"),
                _seats(row.get("sell_items"), "sell"),
                received_at,
            )
        )
    if not result or len({_key(item.ref) for item in result}) != len(result):
        _invalid()
    return tuple(result)


def decode_dragon_events(
    body: bytes, *, owner: object, entry: DragonTigerEntryRef, received_at: datetime
) -> tuple[DragonTigerEvent, ...]:
    """显式展开候选行所属区间的全部真实事件，不复制多原因金额。"""
    if not isinstance(entry, DragonTigerEntryRef) or entry._owner is not owner:
        raise ValueError("entry does not belong to this client")
    details = _collection(
        body,
        owner=owner,
        market=entry.market,
        code=entry.stock_code,
        request_date=entry.request_date,
        range_days=entry.range_days,
        received_at=received_at,
    )
    return tuple(
        DragonTigerEvent(
            item.ref,
            item.stock_name,
            item.reasons,
            item.buy_value,
            item.sell_value,
            item.net_value,
        )
        for item in details
    )


def decode_dragon_detail(
    body: bytes, *, owner: object, event: DragonTigerEventRef, received_at: datetime
) -> DragonTigerDetail:
    """重新查询结果中恰好匹配完整事件；不存在或歧义时拒绝。"""
    if not isinstance(event, DragonTigerEventRef) or event._owner is not owner:
        raise ValueError("event does not belong to this client")
    details = _collection(
        body,
        owner=owner,
        market=event.market,
        code=event.stock_code,
        request_date=event.request_date,
        range_days=event.range_days,
        received_at=received_at,
    )
    matches = [item for item in details if _key(item.ref) == _key(event)]
    if len(matches) != 1:
        _invalid()
    return matches[0]
