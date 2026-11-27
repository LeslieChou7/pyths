"""Mapping of observed 1282 rows; preserves server order and display precision."""

from datetime import datetime
from decimal import Decimal

from ._codec import format_table_string
from ._ranking_capabilities import capability
from ._tb3 import Cell
from .errors import ThsProtocolError
from .models import RankingCursor, RankingValue, StockRankingItem, StockRankingPage


def ranking_page(
    rows: tuple[dict[int, Cell], ...],
    fields: dict[int, str | int],
    *,
    owner: object,
    start: int,
    sort: str,
    direction: str,
    received_at: datetime,
) -> StockRankingPage:
    selected = capability(sort, direction)
    items = []
    for row in rows:

        def identity(key: int, row: dict[int, Cell] = row) -> str:
            cell = row.get(key)
            if cell is None or not isinstance(cell.value, str) or not cell.value:
                raise ThsProtocolError("ranking: missing security identity")
            return cell.value

        code, market, name = identity(4), identity(36103), identity(55)
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ThsProtocolError("ranking: invalid security code")
        if not market.isascii() or not market.isdigit():
            raise ThsProtocolError("ranking: invalid market identity")
        if selected.sort_id not in row:
            raise ThsProtocolError("ranking: missing sorting field")

        def value(key: int, row: dict[int, Cell] = row) -> RankingValue | None:
            cell = row.get(key)
            if cell is None or cell.value is None:
                return None
            if key == 48 and (
                not isinstance(cell.value, (Decimal, int))
                or isinstance(cell.value, bool)
                or not Decimal(cell.value).is_finite()
                or type(cell.format_byte) is not int
                or not 0 <= cell.format_byte <= 255
                or cell.format_byte & 240 != 32
            ):
                raise ThsProtocolError("ranking: unsupported rapid metric")
            if key in (34370, 34391) and (
                not isinstance(cell.value, (Decimal, int))
                or isinstance(cell.value, bool)
                or not Decimal(cell.value).is_finite()
                or type(cell.format_byte) is not int
                or not 0 <= cell.format_byte <= 255
                or cell.format_byte & 240 not in (0, 32, 48, 64, 80)
            ):
                raise ThsProtocolError("ranking: unsupported fund metric")
            raw = (
                format(cell.value, "f")
                if isinstance(cell.value, Decimal)
                else str(cell.value)
            )
            display = format_table_string(raw, cell.format_byte)
            unit = "%" if key in (34818, 48) else None
            if key in (34370, 34391):
                unit = {0: None, 32: "%", 48: "亿", 64: "万", 80: "万亿"}[
                    cell.format_byte & 240
                ]
            return RankingValue(raw, display, cell.format_byte, unit)

        items.append(
            StockRankingItem(
                code,
                market,
                name,
                None,
                value(10),
                value(34818),
                value(19),
                value(48) if selected.sort_id == 48 else None,
                value(34370) if selected.sort_id == 34370 else None,
                value(34391) if selected.sort_id == 34391 else None,
            )
        )
    raw_total = fields.get(34056)
    total = raw_total if type(raw_total) is int else None
    following = start + len(rows)
    has_more = None if total is None else following < total
    cursor = (
        RankingCursor(owner, sort, direction, following, selected.profile)
        if rows and has_more is not False
        else None
    )
    return StockRankingPage(
        tuple(items),
        selected.profile,
        sort,
        direction,
        total,
        cursor,
        has_more,
        received_at,
        window_minutes=selected.window_minutes,
        window_source=selected.window_source,
        definition_source=selected.definition_source,
        definition_url=selected.definition_url,
    )
