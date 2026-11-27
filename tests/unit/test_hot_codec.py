import json
from decimal import Decimal, Inexact, localcontext

import pytest

from pyths import ThsBusinessError, ThsProtocolError
from pyths._hot_codec import MAX_BODY, MAX_ROWS, decode_hot_response
from tests.hot_fixture import payload


def test_source_order_identity_and_optional_fields():
    rows = decode_hot_response(payload())
    assert [(r.stock_code, r.market, r.rank) for r in rows] == [
        ("000001", "33", 2),
        ("600001", "17", 1),
    ]
    assert rows[0].heat.raw == "635459.0"
    assert rows[0].heat.value == Decimal("635459.0")
    assert rows[0].heat.display == "63.5万热度"
    assert rows[1].heat.display == "649.0万热度"
    assert rows[0].rank_change == -3 and rows[1].rank_change == 5
    assert rows[0].latest is rows[0].change_rate is None


def test_missing_is_not_zero_and_unknown_fields_do_not_become_quotes():
    row = decode_hot_response(
        payload(
            [
                {
                    "code": "000001",
                    "extra": {"public": [1]},
                    "range": "8.00%",
                    "latest": "1.23",
                }
            ]
        )
    )[0]
    assert row.market is row.name is row.rank is row.heat is row.rank_change is None
    assert row.change_rate is row.latest is None
    assert decode_hot_response(payload([])) == ()


def test_duplicates_are_preserved_without_merging():
    assert [
        r.stock_code
        for r in decode_hot_response(payload([{"code": "000001"}, {"code": "000001"}]))
    ] == ["000001", "000001"]


@pytest.mark.parametrize(
    ("raw", "display"),
    [
        ("0", "0热度"),
        ("9999.9", "9999热度"),
        ("10000", "10000热度"),
        ("10001", "1.0万热度"),
        ("10500", "1.1万热度"),
        ("11500", "1.1万热度"),
        ("57500", "5.8万热度"),
        ("-0.1", "-1热度"),
    ],
)
def test_app_binary64_rounding_and_threshold(raw, display):
    row = decode_hot_response(payload([{"code": "000001", "rate": raw}]))[0]
    assert row.heat.display == display
    assert row.heat.derivation == "app_number_floor_or_wan_fixed1"
    assert row.heat.unit is None


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"\xff",
        b"[]",
        b"null",
        b"{}",
        b'{"status_code":true}',
        b'{"status_code":0,"data":{"stock_list":null}}',
        b'{"status_code":0,"status_code":0,"data":{"stock_list":[]}}',
        b'{"status_code":0,"data":{"stock_list":[{"code":"000001","rate":NaN}]}}',
        b'{"status_code":"0","data":{"stock_list":[]}}',
        b" " * (MAX_BODY + 1),
    ],
    ids=[
        "empty",
        "truncated",
        "invalid_utf8",
        "array",
        "null",
        "missing_status",
        "bool_status",
        "null_list",
        "duplicate_key",
        "nan",
        "string_status",
        "oversized",
    ],
)
def test_invalid_envelope(body):
    with pytest.raises(ThsProtocolError):
        decode_hot_response(body)


@pytest.mark.parametrize(
    "change",
    [
        {"code": 1},
        {"code": "12345"},
        {"code": "000001\n"},
        {"market": True},
        {"name": {"bad": "name"}},
        {"name": "\ud800"},
        {"order": True},
        {"order": 0},
        {"order": "oops"},
        {"rate": True},
        {"rate": "NaN"},
        {"rate": "1e999"},
        {"rate": "1" * 129},
        {"rate": "1000000000000000001"},
        {"hot_rank_chg": 1.5},
        {"hot_rank_chg": True},
        {"hot_rank_chg": 1_000_000_001},
    ],
)
def test_invalid_rows(change):
    with pytest.raises(ThsProtocolError):
        decode_hot_response(payload([{"code": "000001", **change}]))


def test_bounds_and_business_errors_are_safe():
    for rows in [[None], [{"code": "000001"}] * (MAX_ROWS + 1)]:
        with pytest.raises(ThsProtocolError):
            decode_hot_response(payload(rows))
    nested = {}
    for _ in range(34):
        nested = {"nested": nested}
    with pytest.raises(ThsProtocolError):
        decode_hot_response(payload([{"code": "000001", "extra": nested}]))
    with pytest.raises(ThsProtocolError):
        decode_hot_response(
            payload([{"code": "000001", **{f"k{i}": i for i in range(129)}}])
        )
    with pytest.raises(ThsBusinessError) as caught:
        decode_hot_response(
            json.dumps({"status_code": 7, "status_msg": "secret-token"}).encode()
        )
    assert "secret-token" not in str(caught.value)


def test_callers_decimal_context_cannot_change_display_or_resource_bounds():
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        row = decode_hot_response(payload([{"code": "000001", "rate": "6489718"}]))[0]
        assert row.heat.value == Decimal(6489718)
        assert row.heat.display == "649.0万热度"
        with pytest.raises(ThsProtocolError):
            decode_hot_response(
                payload([{"code": "000001", "rate": "1000000000000000001"}])
            )
