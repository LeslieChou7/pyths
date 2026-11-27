"""合成最小边界样本，不作为线上协议兼容证明。"""

import json
from decimal import Decimal

import pytest

from pyths._event_codec import decode_anomalies, decode_trading_status
from pyths.errors import ThsBusinessError, ThsProtocolError


@pytest.mark.parametrize(
    "name,count",
    [
        ("monitor", 2),
        ("history", 20),
        ("history-page2", 20),
        ("resumption", 10),
        ("suspension", 10),
        ("resumption-page2", 10),
        ("suspension-page2", 10),
    ],
)
def test_synthetic_page_sizes(name, count):
    if name.startswith(("monitor", "history")):
        rows, total = decode_anomalies(
            json.dumps(
                {
                    "status_code": 0,
                    "data": {"total_num": count + 1, "list": [anomaly()] * count},
                }
            ).encode()
        )
        assert total >= len(rows)
    else:
        rows = decode_trading_status(json.dumps([status()] * count).encode())
    assert len(rows) == count


def anomaly(**changes):
    row = {
        "stock_code": "000001",
        "stock_market": "unknown",
        "stock_name": None,
        "ths_code": "000001.SZ",
        "monitor_type": 99,
        "start_date": 1,
        "end_date": 2,
    }
    row.update(changes)
    return row


def status(**changes):
    row = {
        "Code": "000001",
        "Name": "sample",
        "Reason": "reason",
        "Price": "0.00",
        "Change": "未开盘",
        "indexChange": "0.00",
        "tpDate": "2026-01-01",
        "fpDate": "未公布",
        "isFp": "预复牌日期",
        "Days": 0,
    }
    row.update(changes)
    return row


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode()


def test_anomaly_raw_and_duplicates():
    row = anomaly(extra="ignored")
    items, total = decode_anomalies(
        encode({"status_code": 0, "data": {"total_num": 2, "list": [row, row]}})
    )
    assert total == 2 and len(items) == 2 and items[0] == items[1]
    assert items[0].stock_code == "000001" and items[0].name is None
    assert items[0].monitor_type_raw == 99 and items[0].start_date_raw == 1


def test_status_missing_zero_and_duplicates():
    rows = decode_trading_status(encode([status(), status()]))
    assert len(rows) == 2 and rows[0] == rows[1]
    assert rows[0].price == Decimal("0.00") and rows[0].change is None
    assert rows[0].change_raw == "未开盘" and rows[0].days_raw == 0
    assert rows[0].resumption_date_raw == "未公布" and rows[0].market is None


def test_empty_lists():
    assert decode_trading_status(b"[]") == ()
    assert decode_anomalies(
        encode({"status_code": 0, "data": {"total_num": 0, "list": []}})
    ) == ((), 0)


@pytest.mark.parametrize(
    "body", [b"", b"[", b'{"x":1,"x":2}', b"NaN", b"\xff", b"null"]
)
def test_malformed(body):
    for decoder in (decode_anomalies, decode_trading_status):
        with pytest.raises(ThsProtocolError):
            decoder(body)


def test_business_failure_no_source_message():
    with pytest.raises(ThsBusinessError) as error:
        decode_anomalies(b'{"status_code":1,"status_msg":"secret"}')
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"Code": 1},
        {"Code": "123"},
        {"Days": True},
        {"Name": "bad\nvalue"},
        {"Price": None},
    ],
)
def test_bad_status(changes):
    with pytest.raises(ThsProtocolError):
        decode_trading_status(encode([status(**changes)]))


@pytest.mark.parametrize(
    "changes", [{"start_date": True}, {"stock_market": None}, {"monitor_type": -1}]
)
def test_bad_anomaly(changes):
    with pytest.raises(ThsProtocolError):
        decode_anomalies(
            encode(
                {
                    "status_code": 0,
                    "data": {"total_num": 1, "list": [anomaly(**changes)]},
                }
            )
        )
