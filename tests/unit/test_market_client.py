"""组合入口的离线调度、失败及预算契约。"""

import time
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from pyths import (
    MarketBreadth,
    MarketLimitCounts,
    MarketSizeComparison,
    ThsClientClosedError,
    ThsNetworkError,
    ths,
)


def client(**kwargs):
    return ths(
        endpoint=("127.0.0.1", 9),
        app_config="synthetic",
        app_info="synthetic",
        **kwargs,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scope": "all_a"},
        {"components": ()},
        {"components": "breadth"},
        {"components": ("breadth", "breadth")},
        {"components": ("unknown",)},
        {"allow_partial": 1},
    ],
)
def test_invalid_selection_before_sources(kwargs):
    with patch("pyths.client.query_overview") as query:
        with pytest.raises(ValueError):
            client().get_market_overview(**kwargs)
        query.assert_not_called()


def test_shared_statistics_requested_once_and_unselected_state():
    received = datetime.now(UTC)
    with patch(
        "pyths._market.query_breadth",
        return_value=(MarketBreadth(), MarketLimitCounts(), received, "10:01"),
    ) as query:
        result = client().get_market_overview(components=("breadth", "limit_counts"))
    assert query.call_count == 1
    assert result.breadth.status == result.limit_counts.status == "ok"
    assert result.breadth.metadata.received_at == received
    assert result.breadth.metadata.source_time is None
    assert result.breadth.metadata.source_time_label == "10:01"
    assert (
        result.turnover.status
        == result.fund_flow.status
        == result.size_comparison.status
        == "not_requested"
    )


def test_strict_failure_stops_before_other_sources():
    with (
        patch(
            "pyths._market.query_breadth",
            side_effect=ThsNetworkError("sensitive sentinel"),
        ),
        patch("pyths._market.query_size") as sizes,
    ):
        with pytest.raises(ThsNetworkError):
            client().get_market_overview(components=("breadth", "size_comparison"))
        sizes.assert_not_called()


def test_partial_failure_and_independent_source_time():
    received = datetime.now(UTC)
    with (
        patch(
            "pyths._market.query_breadth",
            side_effect=ThsNetworkError("sensitive sentinel"),
        ),
        patch(
            "pyths._market.query_size", return_value=(MarketSizeComparison(), received)
        ),
    ):
        result = client().get_market_overview(
            components=("breadth", "limit_counts", "size_comparison"),
            allow_partial=True,
        )
    assert result.breadth.status == result.limit_counts.status == "error"
    assert result.breadth.error.category == "network"
    assert result.size_comparison.status == "ok"
    assert "sensitive sentinel" not in repr(result)


def test_shared_deadline_and_retry_configuration():
    received = datetime.now(UTC)
    with (
        patch(
            "pyths._market.query_breadth",
            return_value=(MarketBreadth(), MarketLimitCounts(), received, None),
        ) as breadth,
        patch(
            "pyths._market.query_size", return_value=(MarketSizeComparison(), received)
        ) as size,
    ):
        client(retries=1).get_market_overview(components=("breadth", "size_comparison"))
    assert breadth.call_args.kwargs["deadline"] == size.call_args.kwargs["deadline"]
    assert breadth.call_args.kwargs["retries"] == size.call_args.kwargs["retries"] == 1


def test_expired_deadline_never_starts_sources():
    from pyths._market import query_overview

    with patch("pyths._market.query_breadth") as query:
        result = query_overview(
            scope="m8_baseline",
            components=("breadth", "limit_counts"),
            allow_partial=True,
            endpoint=("127.0.0.1", 9),
            app_config="synthetic",
            app_info="synthetic",
            connect_timeout=1,
            deadline=time.monotonic() - 1,
            retries=0,
        )
    query.assert_not_called()
    assert (
        result.breadth.error.category == result.limit_counts.error.category == "timeout"
    )


def test_closed_and_missing_configuration_never_query():
    c = ths()
    with pytest.raises(ValueError):
        c.get_market_overview(components=("breadth",))
    c.close()
    with pytest.raises(ThsClientClosedError):
        c.get_market_overview()
