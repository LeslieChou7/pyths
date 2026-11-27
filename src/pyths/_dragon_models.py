"""龙虎榜候选行、完整事件及原生金额；单位未知不补造。"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

DragonTigerStatus = Literal["published", "pending", "non_trading_day", "unknown"]


@dataclass(frozen=True)
class DragonTigerReason:
    """保留来源原因ID和全文；多原因仍属于同一源事件。"""

    id: str
    content: str


@dataclass(frozen=True, repr=False)
class DragonTigerEntryRef:
    """列表候选引用，尚不足以唯一标识事件；日期仅为请求上下文。"""

    _owner: object = field(repr=False)
    market: str
    stock_code: str
    request_date: date
    range_days: int


@dataclass(frozen=True)
class DragonTigerEntry:
    """保留列表原序、范围天数和来源金额，不猜上榜理由。"""

    ref: DragonTigerEntryRef
    stock_name: str
    buy_value: Decimal | None
    sell_value: Decimal | None
    net_value: Decimal | None
    change: Decimal | None
    net_rate: Decimal | None
    hot_rank: int | None
    limit_reason: str | None
    amount_unit: None = None


@dataclass(frozen=True, repr=False)
class DragonTigerCursor:
    """默认全部榜固定筛选的续页；绑定客户端、日期和页大小。"""

    _owner: object = field(repr=False)
    request_date: date
    _page: int
    _size: int = 50


@dataclass(frozen=True)
class DragonTigerCalendar:
    """来源日期覆盖及最后日期更新状态；time单位保持未知。"""

    trade_days: tuple[date, ...]
    last_date: date
    last_update_status: bool
    source_time_raw: int | None
    received_at: datetime


@dataclass(frozen=True)
class DragonTigerPage:
    """请求日期不是服务端回显日期；空列表不推导披露状态。"""

    items: tuple[DragonTigerEntry, ...]
    total: int
    stock_count: int | None
    page: int
    size: int
    next_page: DragonTigerCursor | None
    has_more: bool
    status: DragonTigerStatus
    request_date: date
    received_at: datetime
    source_date: date | None = None


@dataclass(frozen=True, repr=False)
class DragonTigerEventRef:
    """完整复合身份；不是伪造的服务端事件ID。"""

    _owner: object = field(repr=False)
    market: str
    stock_code: str
    request_date: date
    range_days: int
    range_type: str
    start_date: date
    end_date: date
    reasons: tuple[DragonTigerReason, ...]


@dataclass(frozen=True)
class DragonTigerEvent:
    """事件描述符，多原因共享原生汇总，不重复拆分金额。"""

    ref: DragonTigerEventRef
    stock_name: str
    reasons: tuple[DragonTigerReason, ...]
    buy_value: Decimal | None
    sell_value: Decimal | None
    net_value: Decimal | None
    amount_unit: None = None


@dataclass(frozen=True)
class DragonTigerSeat:
    """方向内源席位；id/name不用于跨方向合并。"""

    id: str
    org_id: str | None
    name: str
    short_name: str | None
    direction: Literal["buy", "sell"]
    rank: int
    buy_value: Decimal | None
    sell_value: Decimal | None
    net_value: Decimal | None
    amount_unit: None = None


@dataclass(frozen=True)
class DragonTigerDetail:
    """恰好匹配一个完整事件的详情，不暗中合计席位。"""

    ref: DragonTigerEventRef
    stock_name: str
    reasons: tuple[DragonTigerReason, ...]
    buy_value: Decimal | None
    sell_value: Decimal | None
    net_value: Decimal | None
    buy_seats: tuple[DragonTigerSeat, ...]
    sell_seats: tuple[DragonTigerSeat, ...]
    received_at: datetime
    amount_unit: None = None
