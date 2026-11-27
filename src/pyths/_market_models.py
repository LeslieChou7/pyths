"""市场概览的SDK数据契约；类型名称不代表已确认的服务端字段。"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal


def _aware(value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("market timestamps must include a timezone")


@dataclass(frozen=True)
class MarketMetric:
    """保留原名原文；数值及精度性质仅由已确认来源提供。"""

    label: str
    raw: str
    value: Decimal | None = None
    unit: str | None = None
    precision: Literal["exact", "rounded", "unknown"] = "unknown"
    currency: str | None = None
    derivation: str | None = None

    def __post_init__(self) -> None:
        if self.value is not None and (
            not isinstance(self.value, Decimal) or not self.value.is_finite()
        ):
            raise ValueError("market numeric values must be finite Decimal values")
        if self.precision not in ("exact", "rounded", "unknown"):
            raise ValueError("invalid market precision")


@dataclass(frozen=True)
class MarketComponentMeta:
    """单组件来源与时间；本机接收时间不能替代来源时间。"""

    source_id: str
    received_at: datetime
    source_time: datetime | None = None
    scope_description: str | None = None
    source_time_label: str | None = None
    unknowns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.received_at)
        _aware(self.source_time)


@dataclass(frozen=True)
class MarketComponentError:
    """安全失败分类；不保存URL、凭据、报文或原始异常消息。"""

    category: Literal[
        "network",
        "protocol",
        "authentication",
        "rate_limit",
        "business",
        "timeout",
        "unsupported",
    ]

    def __post_init__(self) -> None:
        if self.category not in (
            "network",
            "protocol",
            "authentication",
            "rate_limit",
            "business",
            "timeout",
            "unsupported",
        ):
            raise ValueError("invalid market error category")


@dataclass(frozen=True)
class ComponentResult[T]:
    """未请求、成功及失败互不混淆；失败时没有可冒充成功的数据。"""

    status: Literal["ok", "error", "not_requested"] = "not_requested"
    data: T | None = None
    metadata: MarketComponentMeta | None = None
    error: MarketComponentError | None = None

    def __post_init__(self) -> None:
        if self.status == "ok":
            valid = (
                self.data is not None
                and self.metadata is not None
                and self.error is None
            )
        elif self.status == "error":
            valid = self.data is None and self.error is not None
        elif self.status == "not_requested":
            valid = self.data is None and self.metadata is None and self.error is None
        else:
            valid = False
        if not valid:
            raise ValueError("inconsistent market component result")


@dataclass(frozen=True)
class MarketBreadth:
    """来源提供的涨跌分类；缺失不补零，不假定分类穷尽或互斥。"""

    rising: MarketMetric | None = None
    falling: MarketMetric | None = None
    unchanged: MarketMetric | None = None
    total: MarketMetric | None = None
    other: tuple[MarketMetric, ...] = ()


@dataclass(frozen=True)
class MarketLimitCounts:
    """来源的涨跌停指标；具体封板或触及口径保留在原始标签。"""

    limit_up: MarketMetric | None = None
    limit_down: MarketMetric | None = None
    other: tuple[MarketMetric, ...] = ()


@dataclass(frozen=True)
class MarketTurnover:
    """当前额与原生比较；不反推参考额或推算本地变化率。"""

    current: MarketMetric | None = None
    comparison: MarketMetric | None = None
    reference: MarketMetric | None = None
    comparison_basis: str | None = None
    reference_time: datetime | None = None
    reference_time_label: str | None = None
    source_time: datetime | None = None
    source_time_label: str | None = None
    current_source_value: Decimal | None = None
    reference_source_value: Decimal | None = None

    def __post_init__(self) -> None:
        _aware(self.reference_time)
        _aware(self.source_time)
        for value in (self.current_source_value, self.reference_source_value):
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise ValueError("turnover source values must be finite Decimal values")


@dataclass(frozen=True)
class MarketFundFlowPart:
    """资金合计的独立来源；两侧缺失不能当成真实零。"""

    stock_code: str
    market: str
    net: MarketMetric
    source_time: datetime | None = None
    source_time_label: str | None = None

    def __post_init__(self) -> None:
        _aware(self.source_time)


@dataclass(frozen=True)
class MarketFundFlow:
    """来源资金名称与值；不将未知分类自行改称主力资金。"""

    net: MarketMetric | None = None
    inflow: MarketMetric | None = None
    outflow: MarketMetric | None = None
    classification: str | None = None
    sources: tuple[MarketFundFlowPart, ...] = ()


@dataclass(frozen=True)
class MarketSizeSide:
    """大小盘其中一侧；两侧时间可不同且均可未知。"""

    label: str
    value: MarketMetric | None = None
    source_time: datetime | None = None
    source_time_label: str | None = None

    def __post_init__(self) -> None:
        _aware(self.source_time)


@dataclass(frozen=True)
class MarketSizeComparison:
    """来源两侧的当前快照，不假定其对应某两个指数。"""

    large: MarketSizeSide | None = None
    small: MarketSizeSide | None = None


@dataclass(frozen=True)
class MarketOverview:
    """独立组件的组合结果，不承诺跨组件原子快照。"""

    breadth: ComponentResult[MarketBreadth] = field(default_factory=ComponentResult)
    limit_counts: ComponentResult[MarketLimitCounts] = field(
        default_factory=ComponentResult
    )
    turnover: ComponentResult[MarketTurnover] = field(default_factory=ComponentResult)
    fund_flow: ComponentResult[MarketFundFlow] = field(default_factory=ComponentResult)
    size_comparison: ComponentResult[MarketSizeComparison] = field(
        default_factory=ComponentResult
    )
    scope: Literal["m8_baseline"] = field(default="m8_baseline", init=False)
