"""M14纯离线JSON解码；仅映射来源字段，不猜测业务状态。"""

import json
import re
from decimal import Decimal
from typing import NoReturn

from ._event_models import StockAnomaly, TradingStatusEvent
from .errors import ThsBusinessError, ThsProtocolError


def _invalid() -> NoReturn:
    raise ThsProtocolError("event list: invalid response")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    if len(pairs) > 128:
        _invalid()
    for key, value in pairs:
        if key in result or len(key) > 128:
            _invalid()
        result[key] = value
    return result


def _depth(value: object, level: int = 0) -> None:
    if level > 24:
        _invalid()
    if isinstance(value, dict):
        for child in value.values():
            _depth(child, level + 1)
    elif isinstance(value, list):
        if len(value) > 10000:
            _invalid()
        for child in value:
            _depth(child, level + 1)


def _load(body: bytes) -> object:
    if not isinstance(body, bytes) or not 0 < len(body) <= 4 * 1024 * 1024:
        _invalid()
    try:
        value: object = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: _invalid(),
        )
        _depth(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        _invalid()


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        _invalid()
    return value


def _int(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 10**16:
        _invalid()
    return value


def _code(value: object) -> str:
    text = _text(value)
    if re.fullmatch(r"[0-9]{6}", text) is None:
        _invalid()
    return text


def _number(raw: str) -> Decimal | None:
    if re.fullmatch(r"[+-]?[0-9]{1,24}(?:\.[0-9]{1,24})?", raw):
        return Decimal(raw)
    return None


def decode_anomalies(body: bytes) -> tuple[tuple[StockAnomaly, ...], int]:
    """保留源日期整数、市场码及重复行；合成数据不证明真实兼容。"""
    root = _load(body)
    if not isinstance(root, dict) or type(root.get("status_code")) is not int:
        _invalid()
    if root["status_code"] != 0:
        raise ThsBusinessError("stock anomalies: source rejected query")
    data = root.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        _invalid()
    total = _int(data.get("total_num"))
    result = []
    for row in data["list"]:
        if not isinstance(row, dict):
            _invalid()
        name = row.get("stock_name")
        result.append(
            StockAnomaly(
                _code(row.get("stock_code")),
                _text(row.get("stock_market")),
                None if name is None else _text(name),
                _text(row.get("ths_code")),
                _int(row.get("monitor_type")),
                _int(row.get("start_date")),
                _int(row.get("end_date")),
            )
        )
    return tuple(result), total


def decode_trading_status(body: bytes) -> tuple[TradingStatusEvent, ...]:
    """不解释isFp为布尔值，不从日期或价格推断实际状态。"""
    root = _load(body)
    if not isinstance(root, list):
        _invalid()
    result = []
    for row in root:
        if not isinstance(row, dict):
            _invalid()
        price, change, index = (
            _text(row.get(k)) for k in ("Price", "Change", "indexChange")
        )
        label = row.get("isFp")
        days = row.get("Days")
        result.append(
            TradingStatusEvent(
                _code(row.get("Code")),
                _text(row.get("Name")),
                _text(row.get("Reason")),
                _text(row.get("tpDate")),
                _text(row.get("fpDate")),
                None if label is None else _text(label),
                price,
                _number(price),
                change,
                _number(change),
                index,
                _number(index),
                None if days is None else _int(days),
            )
        )
    return tuple(result)
