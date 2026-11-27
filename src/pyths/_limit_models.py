"""M15单页、统计及查询引用；来源口径未知时不作派生。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from ._limit_codec import LimitPoolRow, LimitValue
from ._limit_request import LimitPoolQuery


@dataclass(frozen=True, repr=False)
class LimitPoolCursor:
    """只属于生成它的客户端及完整查询，不可跨进程恢复。"""

    _owner: object = field(repr=False)
    _query: LimitPoolQuery
    _page: int


@dataclass(frozen=True)
class LimitPoolPage:
    """单页原序和重复项；源总数不等于返回条数。"""

    query: LimitPoolQuery
    items: tuple[LimitPoolRow, ...]
    source_date_raw: str | None
    page: int
    page_size: int
    total: int
    page_count: int
    received_at: datetime
    has_more: bool | None
    next_page: LimitPoolCursor | None
    summary_raw: Mapping[str, LimitValue] = field(repr=False)
    warnings: tuple[str, ...] = ()
    source: str = "limit_focus_mobile_v2"
    source_page: int | None = None

    @property
    def returned_count(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class LimitSummarySide:
    """原生num/open_num/rate；不推断证券或事件口径，rate不乘100。"""

    num: int | None
    open_num: int | None
    rate: Decimal | None


@dataclass(frozen=True)
class LimitFocusSummary:
    """六统计，昨日日期未回显时保持未知；接收时间不是源时点。"""

    query: LimitPoolQuery
    source_date_raw: str | None
    today: LimitSummarySide
    yesterday: LimitSummarySide
    received_at: datetime
    warnings: tuple[str, ...] = ()
    yesterday_date_raw: str | None = None
    source_time: datetime | None = None
    source: str = "limit_focus_mobile_v2"
