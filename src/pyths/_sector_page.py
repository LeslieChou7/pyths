"""板块单页结果组装；离线可用，不推断来源更新状态或全量稳定性。"""

from dataclasses import dataclass
from datetime import datetime

from ._sector_codec import SectorWireRow, decode_sector_response
from ._sector_query import SOURCE, SectorCursor, SectorQuery, SectorRef, encode_query
from .errors import ThsProtocolError


@dataclass(frozen=True)
class SectorItem:
    """保留源顺序和指标；仅板块行提供可用于成分查询的引用。"""

    values: SectorWireRow
    sector: SectorRef | None = None


@dataclass(frozen=True)
class SectorPage:
    """内部结果，接收时间不是源时间；无源排名时不生成排名。"""

    query: SectorQuery
    items: tuple[SectorItem, ...]
    total: int
    page: int
    received_at: datetime
    has_more: bool | None
    next_page: SectorCursor | None
    warnings: tuple[str, ...] = ()
    source: str = SOURCE
    source_time: datetime | None = None
    page_size: int = 20

    @property
    def returned_count(self) -> int:
        return len(self.items)


def assemble_page(
    body: bytes,
    *,
    owner: object,
    query: SectorQuery,
    received_at: datetime,
    cursor: SectorCursor | None = None,
) -> SectorPage:
    """以同一查询校验引用和游标，保留重复行与缺失值，不隐式发送续页。"""
    if not isinstance(received_at, datetime) or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    number, _ = encode_query(owner, query, cursor)
    decoded = decode_sector_response(body, kind=query.kind)
    count = len(decoded.rows)
    if count > 20:
        raise ThsProtocolError(
            "sector statistics: response exceeds requested page size"
        )
    items = tuple(
        SectorItem(
            row,
            SectorRef(owner, row.code, row.market) if query.kind == "block" else None,
        )
        for row in decoded.rows
    )
    offset = (number - 1) * 20
    warnings: tuple[str, ...] = ()
    continuation = None
    if (
        offset > decoded.total
        or offset + count > decoded.total
        or (count == 0 and offset < decoded.total)
    ):
        more = None
        warnings = ("source_total_and_page_inconsistent",)
    elif offset + count == decoded.total:
        more = False
    elif count == 20:
        more = True
        continuation = SectorCursor(owner, query, number + 1)
    else:
        more = None
        warnings = ("short_page_before_source_total",)
    return SectorPage(
        query, items, decoded.total, number, received_at, more, continuation, warnings
    )
