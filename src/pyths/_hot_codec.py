"""纯离线热榜JSON解码，仅支持M9实际观察到的源字段。"""

import json
import math
import re
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from typing import NoReturn

from ._hot_models import HotMetric, HotRankItem
from .errors import ThsBusinessError, ThsProtocolError

MAX_BODY = 4 * 1024 * 1024
MAX_ROWS = 10_000
_NUMBER = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")


def _invalid() -> NoReturn:
    raise ThsProtocolError("hot ranking: invalid response")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) > 128:
        _invalid()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result or len(key) > 128:
            _invalid()
        result[key] = value
    return result


def _check_depth(value: object, depth: int = 0) -> None:
    if depth > 32:
        _invalid()
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            _invalid()
        for child in value:
            _check_depth(child, depth + 1)


def _integer(value: object, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,10}", value):
        number = int(value)
    else:
        _invalid()
    if not minimum <= number <= maximum:
        _invalid()
    return number


def _text(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum:
        _invalid()
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        _invalid()
    return value


def _heat(value: object) -> HotMetric | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        _invalid()
    raw = str(value)
    if len(raw) > 128 or _NUMBER.fullmatch(raw) is None:
        _invalid()
    try:
        number = Decimal(raw)
        if not number.is_finite() or number.copy_abs() > Decimal("1e18"):
            _invalid()
        # App uses binary64 Number then toFixed(1), not decimal rounding of rate.
        binary = float(number)
        if binary > 10_000:
            rounded = Decimal.from_float(binary / 10_000).quantize(
                Decimal("0.1"), context=Context(prec=64, rounding=ROUND_HALF_UP)
            )
            display = f"{rounded:.1f}万热度"
        else:
            display = f"{math.floor(binary)}热度"
    except (InvalidOperation, OverflowError, ValueError):
        _invalid()
    return HotMetric(raw, number, display, derivation="app_number_floor_or_wan_fixed1")


def decode_hot_response(body: bytes) -> tuple[HotRankItem, ...]:
    """有界解析成功列表；不联网、不猜测行情或缺失状态。"""
    if not isinstance(body, bytes) or not body or len(body) > MAX_BODY:
        _invalid()
    try:
        root = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=Decimal,
            parse_constant=lambda _: _invalid(),
        )
        _check_depth(root)
    except (ValueError, UnicodeError, RecursionError):
        _invalid()
    if not isinstance(root, dict):
        _invalid()
    status = root.get("status_code")
    if type(status) is not int:
        _invalid()
    if status != 0:
        raise ThsBusinessError("hot ranking: business rejection")
    data = root.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("stock_list"), list):
        _invalid()
    rows = data["stock_list"]
    result = []
    for row in rows:
        if not isinstance(row, dict):
            _invalid()
        code = _text(row.get("code"), maximum=32)
        if code is None or re.fullmatch(r"[0-9]{6}", code) is None:
            _invalid()
        market = row.get("market")
        if type(market) is int:
            market = str(market)
        market_text = _text(market, maximum=32)
        result.append(
            HotRankItem(
                stock_code=code,
                market=market_text,
                name=_text(row.get("name"), maximum=512),
                rank=_integer(row.get("order"), minimum=1, maximum=10_000_000),
                heat=_heat(row.get("rate")),
                rank_change=_integer(
                    row.get("hot_rank_chg"),
                    minimum=-1_000_000_000,
                    maximum=1_000_000_000,
                ),
            )
        )
    return tuple(result)
