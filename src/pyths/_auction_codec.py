"""集合竞价榜单首屏的离线解码。"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import NoReturn

from .errors import ThsBusinessError, ThsProtocolError

type AuctionValue = str | int | Decimal | bool | None


@dataclass(frozen=True)
class AuctionColumn:
    code: str
    name: str
    type_raw: str


@dataclass(frozen=True)
class AuctionWirePage:
    columns: tuple[AuctionColumn, ...]
    rows: tuple[Mapping[str, AuctionValue], ...] = field(repr=False)
    total: int | None
    current_page: int | None

    @property
    def source_data_null(self) -> bool:
        return self.total is None


def _invalid() -> NoReturn:
    raise ThsProtocolError("auction: invalid response")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        _invalid()
    return result


def _auction_data(body: bytes) -> dict[str, object] | None:
    if not isinstance(body, bytes) or not 0 < len(body) <= 4 * 1024 * 1024:
        _invalid()
    try:
        root = json.loads(
            body.decode("utf-8"),
            parse_float=Decimal,
            object_pairs_hook=_object,
            parse_constant=lambda _: _invalid(),
        )
    except (ValueError, RecursionError, ArithmeticError):
        _invalid()
    if not isinstance(root, dict) or type(root.get("status_code")) is not int:
        _invalid()
    if root["status_code"] != 0:
        raise ThsBusinessError("auction: source rejected request")
    if "data" not in root:
        _invalid()
    data = root["data"]
    if data is None:
        return None
    if not isinstance(data, dict):
        _invalid()
    return data


def decode_auction_ranking(body: bytes) -> AuctionWirePage:
    """按来源列顺序映射数据，保留未知标量字段、负值及空值。"""
    data = _auction_data(body)
    if data is None:
        return AuctionWirePage((), (), None, None)
    total, page = data.get("total"), data.get("current_page")
    if type(total) is not int or type(page) is not int or min(total, page) < 0:
        _invalid()
    headers, records = data.get("header_list"), data.get("data_list")
    if not isinstance(headers, list) or not isinstance(records, list):
        _invalid()
    columns = []
    for header in headers:
        if not isinstance(header, dict) or not all(
            isinstance(header.get(key), str) for key in ("code", "name", "type")
        ):
            _invalid()
        columns.append(AuctionColumn(header["code"], header["name"], header["type"]))
    keys = [column.code for column in columns]
    if len(set(keys)) != len(keys) or "" in keys:
        _invalid()
    rows = []
    for record in records:
        if not isinstance(record, list) or len(record) != len(keys):
            _invalid()
        if any(
            v is not None and not isinstance(v, (str, Decimal, int)) for v in record
        ):
            _invalid()
        row = dict(zip(keys, record, strict=True))
        code, market = row.get("code"), row.get("market")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            _invalid()
        if not isinstance(market, str) or not market:
            _invalid()
        rows.append(MappingProxyType(row))
    return AuctionWirePage(tuple(columns), tuple(rows), total, page)


@dataclass(frozen=True)
class AuctionSector:
    """板块原始身份、指标和关联证券，顺序与来源一致。"""

    market: str
    code: str
    name: str
    fields: Mapping[str, AuctionValue]
    leader_stocks: tuple[Mapping[str, AuctionValue], ...] | None


def _scalar_fields(values: dict[str, object]) -> Mapping[str, AuctionValue]:
    result: dict[str, AuctionValue] = {}
    for key, value in values.items():
        if value is not None and not isinstance(value, (str, int, Decimal)):
            _invalid()
        result[key] = value
    return MappingProxyType(result)


def decode_auction_sectors(body: bytes) -> tuple[AuctionSector, ...]:
    """解码单侧已返回的板块集合，不推断全量覆盖或事件身份。"""
    data = _auction_data(body)
    if data is None:
        _invalid()
    records = data.get("block_list")
    if not isinstance(records, list):
        _invalid()
    sectors = []
    for row in records:
        if not isinstance(row, dict):
            _invalid()
        market, code, name = (row.get(k) for k in ("market", "code", "name"))
        if (
            not isinstance(market, str)
            or not isinstance(code, str)
            or not isinstance(name, str)
            or not (market and code and name)
        ):
            _invalid()
        raw_leaders = row.get("leader_stocks")
        leaders = None
        if raw_leaders is not None:
            if not isinstance(raw_leaders, list):
                _invalid()
            leaders = []
            for stock in raw_leaders:
                if not isinstance(stock, dict) or not all(
                    isinstance(stock.get(k), str) and stock[k]
                    for k in ("market", "code")
                ):
                    _invalid()
                leaders.append(_scalar_fields(stock))
        fields = _scalar_fields({k: v for k, v in row.items() if k != "leader_stocks"})
        sectors.append(
            AuctionSector(
                market, code, name, fields, None if leaders is None else tuple(leaders)
            )
        )
    return tuple(sectors)
