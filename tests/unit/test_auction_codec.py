"""合成边界，不需要设备或网络。"""

import json
from decimal import Decimal

import pytest

from pyths._auction_codec import decode_auction_ranking
from pyths.errors import ThsBusinessError, ThsProtocolError


def body(row: list[object]) -> bytes:
    fields = ("market", "code", "bidZf", "grade", "unknown")
    headers = [{"code": key, "name": key, "type": "raw"} for key in fields]
    data = {"header_list": headers, "data_list": [row], "total": 1, "current_page": 0}
    return json.dumps({"status_code": 0, "data": data}).encode()


def test_source_order_identity_and_precision() -> None:
    page = decode_auction_ranking(body(["33", "000026", -1.28, None, 0]))
    assert tuple(page.rows[0]) == tuple(column.code for column in page.columns)
    assert tuple(page.rows[0].values()) == ("33", "000026", Decimal("-1.28"), None, 0)
    assert (page.total, page.current_page) == (1, 0)


@pytest.mark.parametrize(
    "raw",
    [
        body(["33", "000026"]),
        body(["33", 26, 0, None, 1]),
        body(["33", "000026", 0, None, 1])[:-1],
        b'{"status_code":0,"status_code":0}',
    ],
)
def test_incompatible_response(raw: bytes) -> None:
    with pytest.raises(ThsProtocolError):
        decode_auction_ranking(raw)


def test_business_error() -> None:
    with pytest.raises(ThsBusinessError):
        decode_auction_ranking(b'{"status_code":3}')


def test_success_with_explicit_null_data() -> None:
    page = decode_auction_ranking(b'{"status_code":0,"status_msg":"ok","data":null}')
    assert page.source_data_null and page.total is None and page.current_page is None
    assert page.rows == page.columns == ()
    with pytest.raises(ThsProtocolError):
        decode_auction_ranking(b'{"status_code":0}')
