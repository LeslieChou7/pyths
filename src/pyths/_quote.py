"""M2/M3已观察1269字段映射。"""

from datetime import datetime

from ._codec import StringTable, format_table_string
from .errors import ThsProtocolError
from .models import QuoteField, QuoteSnapshot

QUOTE_MARKETS = ("17", "33", "151")


def quote_from_table(
    table: StringTable,
    *,
    stock_code: str,
    market: str,
    received_at: datetime | None = None,
) -> QuoteSnapshot:
    """检查独立证券身份后映射九字段；缺失值不填零。"""
    values = {key: (raw, flag) for key, raw, flag in table.cells}
    if len(values) != len(table.cells):
        raise ThsProtocolError("quote: duplicate field")
    if (
        values.get(4, (None, 0))[0] != stock_code
        or values.get(36103, (None, 0))[0] != market
    ):
        raise ThsProtocolError("quote: security identity mismatch or missing")

    def field(key: int) -> QuoteField | None:
        value = values.get(key)
        if value is None or value[0] == "":
            return None
        raw, flag = value
        unit = "手" if key == 13 else ("%" if key == 34315 else None)
        return QuoteField(raw, flag, format_table_string(raw, flag), unit=unit)

    return QuoteSnapshot(
        stock_code,
        market,
        latest=field(10),
        change=field(34318),
        change_rate=field(34315),
        open=field(7),
        high=field(8),
        low=field(9),
        previous_close=field(6),
        volume=field(13),
        turnover=field(19),
        received_at=received_at,
    )
