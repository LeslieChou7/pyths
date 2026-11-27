import json
from decimal import Decimal
from pathlib import Path

import pytest

from pyths._limit_codec import decode_limit_pool
from pyths.errors import ThsBusinessError, ThsProtocolError

BASE = Path(__file__).resolve().parents[1] / "fixtures/synthetic"


def sample():
    return json.loads((BASE / "limit-pool.json").read_bytes())


def test_raw_values_and_summary():
    result = decode_limit_pool((BASE / "limit-pool.json").read_bytes())
    assert result.date_raw == "20261117"
    assert len(result.rows) == 3 and result.total == 36
    assert result.summary["today"]["num"] == 37
    assert result.summary["yesterday"]["rate"] == Decimal("0.625")
    assert result.rows[0].code == "900201"
    assert result.rows[0].market == "33"
    assert result.rows[0].fields["latest"] == Decimal("13.75")
    assert result.rows[0].fields["first_limit_up_time"] == "1760000010"


def test_duplicates_unknown_fields_zero_and_immutable():
    obj = sample()
    row = obj["data"]["info"][0]
    row["future"] = {"nested": [None, 0, True]}
    obj["data"]["info"] = [row, row]
    obj["data"]["limit_up_count"]["today"] = {"num": 0, "open_num": None, "rate": None}
    result = decode_limit_pool(json.dumps(obj).encode())
    assert result.rows[0] == result.rows[1]
    assert result.rows[0].fields["future"]["nested"] == (None, 0, True)
    assert result.summary["today"]["num"] == 0
    with pytest.raises(TypeError):
        result.rows[0].fields["latest"] = 0


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b'{"status_code":0,"status_code":1}',
        b'{"status_code":NaN}',
        b"\xff",
        b"[]",
    ],
)
def test_malformed(body):
    with pytest.raises(ThsProtocolError):
        decode_limit_pool(body)


@pytest.mark.parametrize(
    "change", ["bool_page", "bad_code", "bad_rate", "overflow_rows"]
)
def test_invalid_structure(change):
    obj = sample()
    if change == "bool_page":
        obj["data"]["page"]["page"] = True
    elif change == "bad_code":
        obj["data"]["info"][0]["code"] = 2983
    elif change == "bad_rate":
        obj["data"]["limit_up_count"]["today"]["rate"] = True
    else:
        obj["data"]["page"]["limit"] = 1
    with pytest.raises(ThsProtocolError):
        decode_limit_pool(json.dumps(obj).encode())


def test_empty_and_error_redaction():
    obj = sample()
    obj["data"]["info"] = []
    assert decode_limit_pool(json.dumps(obj).encode()).rows == ()
    with pytest.raises(ThsBusinessError) as error:
        decode_limit_pool(b'{"status_code":1,"msg":"secret-token"}')
    assert "secret-token" not in str(error.value)


def test_historical_context_and_summary_alignment():
    monday = decode_limit_pool((BASE / "limit-history-20261116.json").read_bytes())
    friday = decode_limit_pool((BASE / "limit-history-20261113.json").read_bytes())
    assert monday.date_raw == "20261116" and friday.date_raw == "20261113"
    assert monday.summary["yesterday"] == friday.summary["today"]
    assert (monday.total, friday.total) == (60, 33)


@pytest.mark.parametrize(
    "field,source_key", [("199112", "change_rate"), ("10", "latest")]
)
@pytest.mark.parametrize("direction", ["0", "1"])
def test_sort_projection(field, source_key, direction):
    page = decode_limit_pool(
        (BASE / f"limit-sort-{field}-{direction}.json").read_bytes()
    )
    values = [row.fields[source_key] for row in page.rows]
    assert values == sorted(values, reverse=direction == "0")


def test_adjacent_and_last_page_metadata():
    second = decode_limit_pool((BASE / "limit-page2.json").read_bytes())
    final = decode_limit_pool((BASE / "limit-page3.json").read_bytes())
    assert (second.page, final.page) == (2, 3)
    assert second.page_count == final.page_count == 3
    assert second.total == final.total == 33
    assert len(final.rows) == 3


def test_empty_market_keeps_statistics():
    page = decode_limit_pool((BASE / "limit-empty.json").read_bytes())
    assert page.page == page.total == page.page_count == 0
    assert page.rows == ()
    assert page.summary["today"]["num"] == 2
    assert page.summary["yesterday"]["rate"] == 0
