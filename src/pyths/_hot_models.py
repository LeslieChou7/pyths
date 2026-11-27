"""热榜源值与App显示；热度算法和排名变化基准保留未知。"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

HotBoardId = Literal["stock_hour", "stock_24h"]


@dataclass(frozen=True)
class HotBoard:
    """本地已验证能力配置，并非服务端实时发现。"""

    id: HotBoardId
    name: str
    time_window_label: str
    scope_description: str
    object_type: Literal["stock"] = "stock"
    pagination: Literal["single_response"] = "single_response"


@dataclass(frozen=True)
class HotMetric:
    """源文本、可确认Decimal及派生显示；unit未知不补造。"""

    raw: str
    value: Decimal
    display: str | None
    unit: str | None = None
    derivation: str | None = None


@dataclass(frozen=True, repr=False)
class HotRankingCursor:
    """不透明续页类型；当前来源无续页，所有非空游标均被拒绝。"""

    _owner: object = field(repr=False)
    _board: str


@dataclass(frozen=True)
class HotRankItem:
    """源顺序条目；市场不猜测，排名不由行号生成。"""

    stock_code: str
    market: str | None
    name: str | None
    rank: int | None
    heat: HotMetric | None
    rank_change: int | None
    latest: HotMetric | None = None
    change_rate: HotMetric | None = None


@dataclass(frozen=True)
class HotRankingPage:
    """单响应快照；100条不代表全榜，接收时间不代表来源时间。"""

    board: HotBoardId
    items: tuple[HotRankItem, ...]
    received_at: datetime
    source: str
    unknowns: tuple[str, ...]
    total: int | None = None
    next_page: HotRankingCursor | None = None
    has_more: bool | None = None
    source_time: datetime | None = None
    source_time_label: str | None = None
    pagination: Literal["single_response"] = "single_response"

    @property
    def returned_count(self) -> int:
        """本响应条目数，不是服务端总数。"""
        return len(self.items)
