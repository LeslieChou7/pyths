"""M10a纯离线候选编解码；不联网、不导出公开能力，窗口仍待确认。"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ._codec import format_table_string
from ._ranking_capabilities import RankingCapability
from ._ranking_request import _encode_ranking_body, _encode_ranking_packet
from ._ranking_response import decode_ranking_response
from ._tb3 import Cell
from .errors import ThsProtocolError

_FIELDS = {
    "rapid_change_rate": 48,
    "large_order_net_volume": 34370,
    "main_net_inflow": 34391,
}
_SUFFIXES = {0: None, 32: "%", 48: "亿", 64: "万", 80: "万亿"}


@dataclass(frozen=True)
class AdvancedMetric:
    """原生数值及显示后缀；后缀不能替代统计单位或币种定义。"""

    raw: str
    value: Decimal
    display: str
    format_byte: int
    display_unit: str | None


@dataclass(frozen=True)
class AdvancedItem:
    """离线候选行；不补造服务端排名或指标语义。"""

    stock_code: str
    market: str
    name: str
    rapid_change_rate: AdvancedMetric | None
    large_order_net_volume: AdvancedMetric | None
    main_net_inflow: AdvancedMetric | None


@dataclass(frozen=True)
class AdvancedPage:
    """已观察表结构的离线结果，不是公开SDK能力或网络兼容声明。"""

    items: tuple[AdvancedItem, ...]
    sort: str
    start: int
    total: int | None
    has_more: bool | None
    received_at: datetime
    window: None = None
    unknowns: tuple[str, ...] = (
        "快速涨幅窗口未知，未满足公开门槛",
        "资金指标统计窗口、分类算法、分母和币种尚未冻结",
        "显示值不能用于恢复舍入前金额或自行计算排行",
    )


def _sort_field(sort: str) -> int:
    if not isinstance(sort, str) or sort not in _FIELDS:
        raise ValueError("unsupported advanced ranking candidate")
    return _FIELDS[sort]


def encode_advanced_body(
    *,
    sort: str,
    instance_id: int,
    start: int = 0,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """仅重建三种已观察降序请求正文；不绕过公开能力表。"""
    return _encode_ranking_body(
        selected=RankingCapability(_sort_field(sort), 0, "m10_offline_candidate"),
        instance_id=instance_id,
        start=start,
        active_instances=active_instances,
    )


def encode_advanced_request(
    *,
    sort: str,
    instance_id: int,
    package_id: int,
    app_info: str,
    session_id: str,
    start: int = 0,
) -> bytes:
    """研究用完整候选请求；无网络或公开入口。"""
    body = encode_advanced_body(sort=sort, instance_id=instance_id, start=start)
    return _encode_ranking_packet(
        body=body,
        package_id=package_id,
        app_info=app_info,
        session_id=session_id,
    )


def _metric(cell: Cell | None) -> AdvancedMetric | None:
    if cell is None or cell.value is None:
        return None
    value = cell.value
    if type(value) is int:
        value = Decimal(value)
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or type(cell.format_byte) is not int
        or not 0 <= cell.format_byte <= 255
        or cell.format_byte & 240 not in _SUFFIXES
    ):
        raise ThsProtocolError("advanced ranking: unsupported metric")
    raw = format(value, "f")
    return AdvancedMetric(
        raw,
        value,
        format_table_string(raw, cell.format_byte),
        cell.format_byte,
        _SUFFIXES[cell.format_byte & 240],
    )


def advanced_page(
    rows: tuple[dict[int, Cell], ...],
    fields: dict[int, str | int],
    *,
    sort: str,
    start: int,
    received_at: datetime,
) -> AdvancedPage:
    """映射已解码表；独立调用也验证页边界和证券身份。"""
    field_id = _sort_field(sort)
    total = fields.get(34056)
    if (
        type(start) is not int
        or start < 0
        or fields.get(34055) != start
        or (total is not None and (type(total) is not int or total < start + len(rows)))
        or len(rows) > 24
    ):
        raise ThsProtocolError("advanced ranking: invalid page bounds")
    items = []
    for row in rows:
        identities = [row[key].value if key in row else None for key in (4, 36103, 55)]
        if any(not isinstance(value, str) or not value for value in identities):
            raise ThsProtocolError("advanced ranking: missing identity")
        code, market, name = (str(value) for value in identities)
        if (
            len(code) != 6
            or not code.isascii()
            or not code.isdigit()
            or not market.isascii()
            or not market.isdigit()
        ):
            raise ThsProtocolError("advanced ranking: invalid identity")
        if field_id not in row:
            raise ThsProtocolError("advanced ranking: missing sorting field")
        items.append(
            AdvancedItem(
                code, market, name, *(_metric(row.get(key)) for key in _FIELDS.values())
            )
        )
    count = total if type(total) is int else None
    return AdvancedPage(
        tuple(items),
        sort,
        start,
        count,
        None if count is None else start + len(rows) < count,
        received_at,
    )


def decode_advanced_response(
    header: bytes,
    payload: bytes,
    *,
    sort: str,
    package_id: int,
    instance_id: int,
    start: int,
    received_at: datetime,
    allow_initial_frame_zero: bool = False,
) -> AdvancedPage:
    """复用1282关联；仅在已观察同族初始布局时显式允许frame0。"""
    _sort_field(sort)
    rows, fields = decode_ranking_response(
        header,
        payload,
        package_id=package_id,
        instance_id=instance_id,
        start=start,
        allow_initial_frame_zero=allow_initial_frame_zero,
    )
    return advanced_page(rows, fields, sort=sort, start=start, received_at=received_at)
