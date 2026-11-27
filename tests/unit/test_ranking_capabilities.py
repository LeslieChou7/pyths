"""未知排序不能被响应映射器误当作成交额。"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pyths._ranking import ranking_page
from pyths._tb3 import Cell
from pyths.errors import ThsProtocolError


@pytest.mark.parametrize(
    ("sort", "direction"),
    [("unknown", "desc"), ("turnover", "asc"), ("rapid_change_rate", "asc")],
)
def test_unverified_sort_rejected_even_for_empty_response(
    sort: str, direction: str
) -> None:
    with pytest.raises(ValueError, match="unsupported ranking order"):
        ranking_page(
            (),
            {},
            owner=object(),
            start=0,
            sort=sort,
            direction=direction,
            received_at=datetime.now(UTC),
        )


@pytest.mark.parametrize("number", [None, Decimal(0), Decimal("-1.20")])
def test_rapid_missing_zero_negative_preserved(number):
    row = {
        4: Cell("000001", 15, 0),
        36103: Cell("33", 15, 0),
        55: Cell("Synthetic", 15, 0),
        48: Cell(number, 42, 0),
    }
    page = ranking_page(
        (row,),
        {34056: 1},
        owner=object(),
        start=0,
        sort="rapid_change_rate",
        direction="desc",
        received_at=datetime.now(UTC),
    )
    metric = page.items[0].rapid_change_rate
    if number is None:
        assert metric is None
    else:
        assert Decimal(metric.raw) == number
        assert metric.unit == "%"
    assert page.window_minutes == 5 and page.window_source == "user_confirmed"
    assert page.next_page is None


@pytest.mark.parametrize(
    "number,fmt", [(Decimal("NaN"), 42), ("1.2", 42), (Decimal(1), 58)]
)
def test_rapid_rejects_unconfirmed_value_or_format(number, fmt):
    row = {
        4: Cell("000001", 15, 0),
        36103: Cell("33", 15, 0),
        55: Cell("Synthetic", 15, 0),
        48: Cell(number, fmt, 0),
    }
    with pytest.raises(ThsProtocolError, match="rapid metric"):
        ranking_page(
            (row,),
            {},
            owner=object(),
            start=0,
            sort="rapid_change_rate",
            direction="desc",
            received_at=datetime.now(UTC),
        )


@pytest.mark.parametrize(
    "sort,key,fmt,unit",
    [("large_order_net_volume", 34370, 10, None), ("main_net_inflow", 34391, 58, "亿")],
)
@pytest.mark.parametrize("number", [None, Decimal(0), Decimal("-1.20")])
def test_fund_values_keep_native_scale(sort, key, fmt, unit, number):
    row = {
        4: Cell("000001", 15, 0),
        36103: Cell("33", 15, 0),
        55: Cell("Synthetic", 15, 0),
        key: Cell(number, fmt, 0),
    }
    page = ranking_page(
        (row,),
        {34056: 1},
        owner=object(),
        start=0,
        sort=sort,
        direction="desc",
        received_at=datetime.now(UTC),
    )
    metric = getattr(page.items[0], sort)
    if number is None:
        assert metric is None
    else:
        assert Decimal(metric.raw) == number
        assert metric.unit == unit
    assert page.definition_source == "user_adopted_official"


@pytest.mark.parametrize(
    "number,fmt", [(Decimal("NaN"), 10), ("1.2", 10), (True, 10), (Decimal(1), 255)]
)
@pytest.mark.parametrize(
    "sort,key", [("large_order_net_volume", 34370), ("main_net_inflow", 34391)]
)
def test_fund_invalid_values_rejected(sort, key, number, fmt):
    row = {
        4: Cell("000001", 15, 0),
        36103: Cell("33", 15, 0),
        55: Cell("Synthetic", 15, 0),
        key: Cell(number, fmt, 0),
    }
    with pytest.raises(ThsProtocolError, match="fund metric"):
        ranking_page(
            (row,),
            {},
            owner=object(),
            start=0,
            sort=sort,
            direction="desc",
            received_at=datetime.now(UTC),
        )
