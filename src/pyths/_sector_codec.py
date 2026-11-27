"""M13 板块JSON的内部离线解码；不声明网络访问或未验证查询能力。"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, NoReturn

from .errors import ThsBusinessError, ThsProtocolError


@dataclass(frozen=True)
class SectorWireRow:
    """仅源字段；比例不改成百分数，金额币种与换手率单位待确认。"""

    code: str
    market: str
    name: str | None
    change_rate: Decimal | None
    main_net_inflow: Decimal | None
    turnover: Decimal | None
    turnover_rate: Decimal | None


@dataclass(frozen=True)
class SectorWirePage:
    """源总数与本响应条目分别保存；无完整性或末页推断。"""

    rows: tuple[SectorWireRow, ...]
    total: int


def _invalid() -> NoReturn:
    raise ThsProtocolError("sector statistics: invalid response")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    if len(pairs) > 256:
        _invalid()
    for key, value in pairs:
        if key in result or len(key) > 128:
            _invalid()
        result[key] = value
    return result


def _depth(value: object, level: int = 0) -> None:
    if level > 32:
        _invalid()
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        if len(value) > 10000:
            _invalid()
        for item in value:
            _depth(item, level + 1)


def _text(value: object, *, identity: bool = False) -> str | None:
    if value is None and not identity:
        return None
    if not isinstance(value, str) or not value or len(value) > 128:
        _invalid()
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        _invalid()
    if identity and re.fullmatch(r"[0-9]{1,32}", value) is None:
        _invalid()
    return value


def _number(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        _invalid()
    text = str(value)
    if (
        len(text) > 128
        or re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text) is None
    ):
        _invalid()
    try:
        result = Decimal(text)
    except InvalidOperation:
        _invalid()
    if not result.is_finite() or abs(result.adjusted()) > 100:
        _invalid()
    return result


def decode_sector_response(
    body: bytes, *, kind: Literal["block", "stock"]
) -> SectorWirePage:
    """解码原始HTTP JSON，拒绝无身份行；未知附加字段不改变已知值。"""
    if kind not in ("block", "stock"):
        raise ValueError("unsupported sector row kind")
    if not isinstance(body, bytes) or not 0 < len(body) <= 4 * 1024 * 1024:
        _invalid()
    try:
        root = json.loads(
            body.decode("utf-8"),
            parse_float=Decimal,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: _invalid(),
        )
        _depth(root)
    except (ValueError, UnicodeError, RecursionError):
        _invalid()
    if not isinstance(root, dict) or type(root.get("status_code")) is not int:
        _invalid()
    if root["status_code"] != 0:
        raise ThsBusinessError("sector statistics: business rejection")
    data = root.get("data")
    if not isinstance(data, dict):
        _invalid()
    total, rows = data.get("total"), data.get("list")
    if type(total) is not int or total < 0 or not isinstance(rows, list):
        _invalid()
    result = []
    for row in rows:
        if not isinstance(row, dict):
            _invalid()
        code = _text(row.get(f"{kind}_code"), identity=True)
        market = _text(row.get(f"{kind}_market"), identity=True)
        if code is None or market is None:
            _invalid()
        result.append(
            SectorWireRow(
                code,
                market,
                _text(row.get(f"{kind}_name")),
                _number(row.get("margin_of_increase")),
                _number(row.get("net_inflow_of_main_force")),
                _number(row.get("turnover")),
                _number(row.get("turnover_rate")) if kind == "stock" else None,
            )
        )
    return SectorWirePage(tuple(result), total)
