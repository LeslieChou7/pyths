"""M14原生区间和停复牌记录；未知口径不推导状态。"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

StockAnomalyKind = Literal["current", "history"]
TradingStatusKind = Literal["suspension", "resumption"]


@dataclass(frozen=True, repr=False)
class StockAnomalyCursor:
    """仅由同客户端、同类查询产生的不透明续页。"""

    _owner: object = field(repr=False)
    _kind: StockAnomalyKind
    _page: int


@dataclass(frozen=True, repr=False)
class TradingStatusCursor:
    """仅由同客户端、同类查询产生的不透明续页。"""

    _owner: object = field(repr=False)
    _kind: TradingStatusKind
    _page: int


@dataclass(frozen=True)
class StockAnomaly:
    """源类型码和整数日期保持原样，不按代码猜测证券类别。"""

    stock_code: str
    market: str
    name: str | None
    ths_code: str
    monitor_type_raw: int
    start_date_raw: int
    end_date_raw: int


@dataclass(frozen=True)
class TradingStatusEvent:
    """日期标签、缺失原文与数值分开；不生成实际复牌状态。"""

    stock_code: str
    name: str
    reason: str
    suspension_date_raw: str
    resumption_date_raw: str
    resumption_label: str | None
    price_raw: str
    price: Decimal | None
    change_raw: str
    change: Decimal | None
    index_change_raw: str
    index_change: Decimal | None
    days_raw: int | None
    market: None = None


@dataclass(frozen=True)
class StockAnomalyPage:
    """单页源顺序；总数不是本响应条数，时间为本机接收时间。"""

    kind: StockAnomalyKind
    items: tuple[StockAnomaly, ...]
    total: int
    received_at: datetime
    source: str
    has_more: bool | None = None
    next_page: StockAnomalyCursor | None = None


@dataclass(frozen=True)
class TradingStatusPage:
    """单页来源记录，不承诺全量或跨页原子一致。"""

    kind: TradingStatusKind
    items: tuple[TradingStatusEvent, ...]
    received_at: datetime
    source: str
    total: int | None = None
    has_more: bool | None = None
    next_page: TradingStatusCursor | None = None
