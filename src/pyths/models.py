"""行情显示值模型；不反推精确量额。"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RankingValue:
    """排行原始显示值及格式字节，不恢复舍入前精度。"""

    raw: str
    display: str
    format_byte: int
    unit: str | None = None


@dataclass(frozen=True, repr=False)
class RankingCursor:
    """仅用于生成它的客户端及同一排序；内部结构不属于公开契约。"""

    _owner: object = field(repr=False)
    _sort: str
    _direction: str
    _start: int
    _profile: str = "m7_baseline"


@dataclass(frozen=True)
class StockRankingItem:
    """单行证券身份与已确认字段；排名未由服务端给出时为空。"""

    stock_code: str
    market: str
    name: str
    rank: int | None
    latest: RankingValue | None
    change_rate: RankingValue | None
    turnover: RankingValue | None
    rapid_change_rate: RankingValue | None = None
    large_order_net_volume: RankingValue | None = None
    main_net_inflow: RankingValue | None = None


@dataclass(frozen=True)
class StockRankingPage:
    """固定筛选单页，不承诺跨页原子一致；接收时间不是行情时间。"""

    items: tuple[StockRankingItem, ...]
    scope: str
    sort: str
    direction: str
    total: int | None
    next_page: RankingCursor | None
    has_more: bool | None
    received_at: datetime
    source_time: datetime | None = None
    window_minutes: int | None = None
    window_source: str | None = None
    definition_source: str | None = None
    definition_url: str | None = None


@dataclass(frozen=True)
class QuoteField:
    """原始显示文本、格式字节及应用后缀后的文本。"""

    raw: str
    format_byte: int
    display: str
    unit: str | None = None


@dataclass(frozen=True)
class QuoteSnapshot:
    """单证券1269显示快照；币种和行情时间尚未确认。"""

    stock_code: str
    market: str
    latest: QuoteField | None
    change: QuoteField | None
    change_rate: QuoteField | None
    open: QuoteField | None
    high: QuoteField | None
    low: QuoteField | None
    previous_close: QuoteField | None
    volume: QuoteField | None
    turnover: QuoteField | None
    received_at: datetime | None = None
