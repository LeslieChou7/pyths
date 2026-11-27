"""合成最小响应；不作为真实完整响应或网络兼容证据。"""

import json
from decimal import Decimal

import pytest

from pyths._sector_codec import decode_sector_response
from pyths.errors import ThsBusinessError, ThsProtocolError


def body(row):
    return json.dumps(
        {"status_code": 0, "data": {"total": 509, "list": [row]}}
    ).encode()


def test_identity_precision_missing_and_zero():
    result = decode_sector_response(
        body(
            {
                "stock_code": "000001",
                "stock_market": "33",
                "margin_of_increase": "0.04368",
                "turnover": 0,
                "net_inflow_of_main_force": "-81393550",
                "extra": "ignored",
            }
        ),
        kind="stock",
    )
    row = result.rows[0]
    assert result.total == 509 and len(result.rows) == 1
    assert row.code == "000001" and row.market == "33"
    assert row.change_rate == Decimal("0.04368")
    assert row.turnover == 0 and row.turnover_rate is None
    assert row.main_net_inflow == Decimal(-81393550)


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b'{"status_code":0,"status_code":0}',
        b'{"status_code":true}',
        b'{"status_code":0,"data":{"total":0,"list":[{}]}}',
        b'{"status_code":0,"data":{"total":false,"list":[]}}',
    ],
)
def test_invalid(raw):
    with pytest.raises(ThsProtocolError):
        decode_sector_response(raw, kind="block")


def test_business_failure():
    with pytest.raises(ThsBusinessError):
        decode_sector_response(b'{"status_code":7,"secret":"not logged"}', kind="block")


def test_unknown_market_preserved():
    page = decode_sector_response(
        body({"block_code": "881274", "block_market": "999"}), kind="block"
    )
    assert page.rows[0].market == "999"


def test_fractional_json_amount_retains_decimal_digits():
    # Synthetic envelope using the numeric shape observed in M13-X11.
    raw = (
        b'{"status_code":0,"data":{"total":1,"list":[{"stock_code":"000962",'
        b'"stock_market":"33","net_inflow_of_main_force":65222126.7}]}}'
    )
    page = decode_sector_response(raw, kind="stock")
    assert page.rows[0].main_net_inflow == Decimal("65222126.7")


@pytest.mark.parametrize("value", [True, [], {}, "NaN", "Infinity", "1e101", "SECRET"])
def test_invalid_metric_rejected_without_value_disclosure(value):
    with pytest.raises(ThsProtocolError) as error:
        decode_sector_response(
            body({"stock_code": "000001", "stock_market": "33", "turnover": value}),
            kind="stock",
        )
    assert str(error.value) == "sector statistics: invalid response"


def test_empty_response_preserves_unknown_business_state():
    page = decode_sector_response(
        b'{"status_code":0,"data":{"total":0,"list":[]}}', kind="block"
    )
    assert page.total == 0 and page.rows == ()


def test_unknown_fields_do_not_change_order_or_duplicates():
    row = {"block_code": "881274", "block_market": "48"}
    raw = json.dumps(
        {
            "status_code": 0,
            "data": {"total": 2, "list": [row, row], "unknown_flag": True},
        }
    ).encode()
    page = decode_sector_response(raw, kind="block")
    assert len(page.rows) == 2 and page.rows[0] == page.rows[1]
