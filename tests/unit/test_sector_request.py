"""合成编码检查；参数组合支持范围仍由实际验收确定。"""

import json

import pytest

from pyths._sector_request import encode_sector_request

BASE = {
    "kind": "block",
    "category": "region",
    "start": "20261113110500",
    "end": "20261113150000",
    "history_type": "0",
    "sort": "change_rate",
    "direction": "desc",
}


def test_observed_region_intraday_shape():
    body = json.loads(encode_sector_request(**BASE))
    assert body == {
        "type": 4,
        "history_info": {
            "history_type": "0",
            "start_date": "20261113110500",
            "end_date": "20261113150000",
        },
        "page_info": {"page": 1, "page_size": 20},
        "sort_info": {"sort_field": "0", "sort_type": "desc"},
    }


def test_stock_identity_and_multi_day():
    data = {
        **BASE,
        "kind": "stock",
        "category": None,
        "code": "001234",
        "market": "48",
        "history_type": "1",
        "start": "20261102000000",
        "end": "20261113000000",
    }
    body = json.loads(encode_sector_request(**data))
    assert body["block_code"] == "001234" and body["block_market"] == "48"
    assert "type" not in body


@pytest.mark.parametrize(
    "change",
    [
        {"page": True},
        {"page": 0},
        {"category": "unknown"},
        {"start": "20260230093000"},
        {"start": "20261114110500"},
        {"start": "20261113110501"},
        {"history_type": "1"},
        {"code": "881274"},
        {"direction": "0"},
    ],
)
def test_invalid_before_sending(change):
    with pytest.raises(ValueError):
        encode_sector_request(**{**BASE, **change})
