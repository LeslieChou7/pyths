"""M15内部离线解码；不证明独立网络访问或业务口径。"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import NoReturn

from .errors import ThsBusinessError, ThsProtocolError

type LimitValue = (
    None
    | bool
    | int
    | Decimal
    | str
    | tuple[LimitValue, ...]
    | Mapping[str, LimitValue]
)


@dataclass(frozen=True)
class LimitPoolRow:
    """证券代码保留前导零；所有原始字段不换单位或解释状态。"""

    code: str
    market: str | None
    name: str | None
    fields: Mapping[str, LimitValue] = field(repr=False)


@dataclass(frozen=True)
class LimitWirePage:
    """源分页值与实际解码行数分开；不由列表推导统计。"""

    date_raw: str | None
    page: int
    page_size: int
    total: int
    page_count: int
    rows: tuple[LimitPoolRow, ...]
    summary: Mapping[str, LimitValue] = field(repr=False)


def _invalid() -> NoReturn:
    raise ThsProtocolError("limit focus: invalid response")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    if len(pairs) > 256:
        _invalid()
    for key, value in pairs:
        if key in result or len(key) > 128:
            _invalid()
        result[key] = value
    return result


def _freeze(value: object, depth: int = 0) -> LimitValue:
    if depth > 24:
        _invalid()
    if value is None or type(value) in (bool, int):
        return value  # type: ignore[return-value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            _invalid()
        return value
    if isinstance(value, str):
        if len(value) > 16384 or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            _invalid()
        return value
    if isinstance(value, list):
        if len(value) > 10000:
            _invalid()
        return tuple(_freeze(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v, depth + 1) for k, v in value.items()})
    _invalid()


def _integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 10**12:
        _invalid()
    return value


def decode_limit_pool(body: bytes) -> LimitWirePage:
    """只解码JSON，保留缺失、零、重复行及未知字段；无网络依赖。"""
    if not isinstance(body, bytes) or not 0 < len(body) <= 4 * 1024 * 1024:
        _invalid()
    try:
        root = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=Decimal,
            parse_constant=lambda _: _invalid(),
        )
        _freeze(root)
    except (ValueError, UnicodeError, RecursionError):
        _invalid()
    if not isinstance(root, dict) or type(root.get("status_code")) is not int:
        _invalid()
    if root["status_code"] != 0:
        raise ThsBusinessError("limit focus: source rejected query")
    data = root.get("data")
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("page"), dict)
        or not isinstance(data.get("info"), list)
    ):
        _invalid()
    meta = data["page"]
    number = _integer(meta.get("page"))
    size = _integer(meta.get("limit"), 1)
    total = _integer(meta.get("total"))
    pages = _integer(meta.get("count"))
    if number == 0 and (data["info"] or total != 0 or pages != 0):
        _invalid()
    if len(data["info"]) > size:
        _invalid()
    date_raw = data.get("date")
    if date_raw is not None and (
        not isinstance(date_raw, str) or not re.fullmatch(r"[0-9]{8}", date_raw)
    ):
        _invalid()
    rows = []
    for item in data["info"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("code"), str)
            or not re.fullmatch(r"[0-9]{6}", item["code"])
        ):
            _invalid()
        market = item.get("market_id")
        if (
            market is not None
            and type(market) is not int
            and not isinstance(market, str)
        ):
            _invalid()
        name = item.get("name")
        if name is not None and not isinstance(name, str):
            _invalid()
        frozen = _freeze(item)
        if not isinstance(frozen, Mapping):
            _invalid()
        rows.append(
            LimitPoolRow(
                item["code"], None if market is None else str(market), name, frozen
            )
        )
    summary = data.get("limit_up_count")
    if not isinstance(summary, dict):
        _invalid()
    for side in ("today", "yesterday"):
        part = summary.get(side)
        if not isinstance(part, dict):
            _invalid()
        for key in ("num", "open_num"):
            if part.get(key) is not None:
                _integer(part[key])
        rate = part.get("rate")
        if rate is not None and (
            type(rate) is not int and not isinstance(rate, Decimal)
        ):
            _invalid()
    frozen_summary = _freeze(summary)
    if not isinstance(frozen_summary, Mapping):
        _invalid()
    return LimitWirePage(
        date_raw, number, size, total, pages, tuple(rows), frozen_summary
    )
