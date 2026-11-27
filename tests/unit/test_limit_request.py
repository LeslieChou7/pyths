from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from pyths._limit_request import (
    POOL_DEFAULTS,
    LimitFilters,
    LimitPoolQuery,
    encode_limit_query,
)


@pytest.mark.parametrize("pool", POOL_DEFAULTS)
def test_observed_pool_defaults(pool):
    url = encode_limit_query(LimitPoolQuery(pool, date(2026, 11, 17)))
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.hostname == "data.10jqka.com.cn"
    assert parsed.path.endswith("/" + POOL_DEFAULTS[pool][0])
    assert query["date"] == ["20261117"]
    assert query["limit"] == ["15"]
    assert query["filter"] == ["HS,GEM2STAR"]
    assert query["order_field"] == [POOL_DEFAULTS[pool][2]]


def test_filters_and_page_are_explicit():
    q = LimitPoolQuery(
        "limit_down",
        date(2026, 11, 13),
        LimitFilters(include_st=True, include_unopened=True),
    )
    params = parse_qs(urlsplit(encode_limit_query(q, page=2)).query)
    assert params["filter"] == ["HS,GEM2STAR,ST,NEW"]
    assert params["page"] == ["2"]


@pytest.mark.parametrize("page", [True, 0, -1, 10001, "2"])
def test_reject_invalid_pages(page):
    with pytest.raises(ValueError):
        encode_limit_query(LimitPoolQuery("limit_up", date(2026, 11, 17)), page=page)


def test_reject_injection_and_datetime():
    with pytest.raises(ValueError):
        encode_limit_query(
            LimitPoolQuery("limit_up", date(2026, 11, 17), sort_field="10&token=x")
        )
    with pytest.raises(ValueError):
        encode_limit_query(
            LimitPoolQuery("limit_up", datetime(2026, 11, 17, tzinfo=UTC))
        )
    with pytest.raises(ValueError):
        LimitFilters(markets=("HS", "HS")).to_wire()
