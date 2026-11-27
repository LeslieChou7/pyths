"""合成数据验证概览模型边界，不证明真实协议兼容。"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from pyths._market_models import (
    ComponentResult,
    MarketBreadth,
    MarketComponentError,
    MarketComponentMeta,
    MarketFundFlow,
    MarketMetric,
    MarketOverview,
    MarketSizeComparison,
    MarketSizeSide,
    MarketTurnover,
)


def test_zero_negative_and_missing_values_stay_distinct():
    breadth = MarketBreadth(rising=MarketMetric("涨", "0", Decimal(0)))
    funds = MarketFundFlow(
        net=MarketMetric("原资金名", "-82.00亿", Decimal("-82.00"), "亿")
    )
    turnover = MarketTurnover(
        current=MarketMetric(
            "今日实时成交额", "11474亿", Decimal(11474), "亿", "rounded"
        ),
        comparison=MarketMetric(
            "较上一日此时", "+1294亿", Decimal(1294), "亿", "rounded"
        ),
        comparison_basis="上一日此时",
    )
    assert breadth.rising.value == Decimal(0)
    assert breadth.unchanged is None
    assert funds.net.raw == "-82.00亿"
    assert funds.net.value == Decimal("-82.00")
    assert turnover.reference is None
    assert turnover.reference_time is None
    assert turnover.current.precision == "rounded"


def test_components_and_size_sides_preserve_independent_times():
    now = datetime(2026, 11, 3, 1, 40, tzinfo=UTC)
    earlier = now - timedelta(minutes=1)
    breadth = ComponentResult(
        status="ok",
        data=MarketBreadth(),
        metadata=MarketComponentMeta(
            "synthetic-breadth", now, earlier, unknowns=("统计集合",)
        ),
    )
    size = MarketSizeComparison(
        large=MarketSizeSide("来源大盘名称", source_time=earlier),
        small=MarketSizeSide("来源小盘名称"),
    )
    result = MarketOverview(
        breadth=breadth,
        size_comparison=ComponentResult(
            status="ok",
            data=size,
            metadata=MarketComponentMeta("synthetic-size", now),
        ),
        fund_flow=ComponentResult(
            status="error", error=MarketComponentError("authentication")
        ),
    )
    assert result.scope == "m8_baseline"
    assert result.breadth.metadata.source_time == earlier
    assert result.size_comparison.metadata.source_time is None
    assert result.size_comparison.data.large.source_time == earlier
    assert result.size_comparison.data.small.source_time is None
    assert result.turnover.status == "not_requested"
    assert result.fund_flow.error.category == "authentication"


def test_results_and_nested_metrics_are_immutable():
    metric = MarketMetric("合成", "--")
    with pytest.raises(FrozenInstanceError):
        metric.raw = "0"
    with pytest.raises(FrozenInstanceError):
        MarketOverview().scope = "other"


@pytest.mark.parametrize(
    "category",
    [
        "network",
        "protocol",
        "authentication",
        "rate_limit",
        "business",
        "timeout",
        "unsupported",
    ],
)
def test_failure_representation_contains_only_safe_category(category):
    result = ComponentResult(status="error", error=MarketComponentError(category))
    assert result.data is None
    assert result.error.category == category


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "ok"},
        {"status": "ok", "data": 1},
        {"status": "error"},
        {"status": "not_requested", "data": 0},
        {"status": "error", "data": 0, "error": MarketComponentError("network")},
    ],
)
def test_inconsistent_results_are_rejected(kwargs):
    with pytest.raises(ValueError, match="inconsistent"):
        ComponentResult(**kwargs)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), 0.1])
def test_invalid_numeric_values_are_not_published(value):
    with pytest.raises(ValueError, match="finite Decimal"):
        MarketMetric("合成", "raw", value)


def test_naive_time_is_not_misrepresented_as_source_or_received_time():
    naive = datetime(2026, 11, 3)  # noqa: DTZ001 -- deliberate invalid input
    with pytest.raises(ValueError, match="timezone"):
        MarketComponentMeta("synthetic", naive)
    with pytest.raises(ValueError, match="timezone"):
        MarketSizeSide("合成", source_time=naive)
