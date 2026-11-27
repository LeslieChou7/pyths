"""Synthetic turnover curves and local substitutes; no production requests."""

import importlib
import struct
import time
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pyths._market_turnover import (
    combine_turnover,
    decode_turnover_response,
    encode_turnover_body,
    encode_turnover_request,
    format_amount,
    query_turnover,
)
from pyths._trading_calendar import TRADE_DAYS_2026, previous_trade_date
from pyths._transform import decode_body
from pyths.errors import ThsBusinessError, ThsNetworkError, ThsProtocolError


def packed_time(hhmm):
    return (116 << 20) | (11 << 16) | (3 << 11) | ((hhmm // 100) << 6) | (hhmm % 100)


def test_reference_without_date_extension_requires_request_context_and_matching_bits():
    payload = bytearray(curve(day=None))
    start = int.from_bytes(payload[18:20], "little")
    for i, hhmm in enumerate((930, 1339)):
        stamp = (
            (126 << 20) | (11 << 16) | (2 << 11) | ((hhmm // 100) << 6) | (hhmm % 100)
        )
        struct.pack_into("<I", payload, start + 8 * i, stamp)
    header, body = wire(bytes(payload))
    decoded = decode_turnover_response(
        header, body, package_id=1, instance_id=1, expected_date=date(2026, 11, 2)
    )
    assert decoded.row_count == 2
    with pytest.raises(ThsProtocolError):
        decode_turnover_response(header, body, package_id=1, instance_id=1)
    with pytest.raises(ThsProtocolError):
        decode_turnover_response(
            header, body, package_id=1, instance_id=1, expected_date=date(2026, 11, 3)
        )


def test_observed_compressed_history_header_retains_frame():
    from tests.unit.test_market_size import snappy

    body = snappy(curve())
    head = struct.pack("<HiiHiii", 26, 1, 0x1100, 1, len(body), 2312, 0) + b"\x00\xff"
    assert (
        decode_turnover_response(head, body, package_id=1, instance_id=1).row_count == 2
    )


def test_complete_1500_shape_uses_full_day_comparison_label():
    from pyths._curve import parse_curve

    minutes = tuple(
        h * 100 + m
        for h in (9, 10, 11, 13, 14, 15)
        for m in range(60)
        if (h == 9 and m >= 30)
        or h == 10
        or (h == 11 and m <= 30)
        or (h == 13 and m >= 1)
        or h == 14
        or (h == 15 and m == 0)
    )
    assert len(minutes) == 241
    current = parse_curve(curve(times=minutes, amounts=(1550000000,) * 241))
    reference = parse_curve(
        curve(day=20261102, times=minutes, amounts=(1450000000,) * 241)
    )
    result = combine_turnover(current, reference)
    assert result.current.label == "今日成交额总计"
    assert result.comparison.label == "较上一日"
    assert result.comparison_basis == "上一交易日全日"


def text_entry(key, value):
    return struct.pack("<HH", key, len(value)) + value.encode("utf-16-le")


def curve(
    *,
    day=20261103,
    times=(930, 1339),
    amounts=(100000000, 1550000000),
    code="883957",
    market="48",
    first=0,
    omit=None,
):
    columns = [(8192 | 1, 4, 4), (8192 | 19, 4, 4)]
    columns = [column for column in columns if column[0] & 36863 != omit]
    entries = [text_entry(4, code), text_entry(36103, market)]
    if day is not None:
        entries.append(struct.pack("<Hi", 8192 | 32790, day))
    meta = struct.pack("<h", len(entries)) + b"".join(entries)
    offset = 24 + 4 * len(columns) + len(meta)
    rows = bytearray()
    for index, stamp in enumerate(times):
        values = {1: packed_time(stamp), 19: amounts[index]}
        for tag, _, _ in columns:
            rows.extend(struct.pack("<i", values[tag & 36863]))
    return (
        b"cv1.0\x00"
        + struct.pack(
            "<iIiHHH", len(times), 0, first, offset, 4 * len(columns), len(columns)
        )
        + b"".join(struct.pack("<HBB", *column) for column in columns)
        + meta
        + rows
    )


def wire(body=None, *, package=1, instance=1):
    body = curve() if body is None else body
    head = struct.pack("<HiiHiii", 32, package, 0x120, instance, len(body), 2312, 0)
    return head + b"\x00" * 4 + struct.pack("<i", 9), body


def decoded(**kwargs):
    head, body = wire(curve(**kwargs))
    return decode_turnover_response(head, body, package_id=1, instance_id=1)


def test_calendar_holiday_boundaries_and_supported_year():
    assert previous_trade_date(date(2026, 11, 3)) == date(2026, 11, 2)
    assert previous_trade_date(date(2026, 2, 24)) == date(2026, 2, 13)
    assert previous_trade_date(date(2026, 10, 8)) == date(2026, 9, 30)
    assert len(TRADE_DAYS_2026) == 242
    with pytest.raises(ThsBusinessError, match="year 2026"):
        previous_trade_date(date(2027, 1, 4))
    with pytest.raises(ThsBusinessError, match="previous year"):
        previous_trade_date(date(2026, 1, 5))
    with pytest.raises(ThsBusinessError, match="absent"):
        previous_trade_date(date(2026, 10, 1))
    with pytest.raises(ValueError):
        previous_trade_date(datetime(2026, 11, 3, tzinfo=UTC))


def test_fixed_body_and_request_reconstruction():
    body = encode_turnover_body(kind="current", instance_id=7)
    assert body == (
        b"[frame]\r\nid=2312\r\npageList=7\r\nreqPage=7\r\nreqPageCount=1\r\n"
        b"[7]\r\nid=1229\r\n\r\nstockcode=883957\r\nfstrend=1\r\nmarketcode=48\r\n"
    )
    reference = encode_turnover_body(
        kind="reference", instance_id=7, reference_date=date(2026, 11, 2)
    )
    assert b"id=1271\r\n" in reference
    assert reference.endswith(
        b"preday=0\r\nleftday=1\r\npinterval=1\r\nendtime=20261102\r\n"
    )
    packet = encode_turnover_request(
        kind="current",
        package_id=3,
        instance_id=7,
        app_info="synthetic",
        session_id="synthetic",
    )
    header_length = int.from_bytes(packet[:2], "little")
    assert decode_body(packet[header_length:]) == body
    assert struct.unpack_from("<i", packet, 16)[0] == 2312
    assert struct.unpack_from("<i", packet, 6)[0] == 0x01010000


@pytest.mark.parametrize(
    "instance,active",
    [(0, None), (True, None), (65536, None), (1, ()), (1, (2,)), (1, (1, 1))],
)
def test_invalid_request_instance_rejected(instance, active):
    with pytest.raises(ThsProtocolError):
        encode_turnover_body(
            kind="current", instance_id=instance, active_instances=active
        )


def test_dates_cannot_be_silently_injected_or_defaulted():
    with pytest.raises(ValueError):
        encode_turnover_body(kind="reference", instance_id=1)
    with pytest.raises(ValueError):
        encode_turnover_body(
            kind="current", instance_id=1, reference_date=date(2026, 11, 2)
        )


@pytest.mark.parametrize(
    "value,raw,number,unit",
    [
        (0.0, "0.0", "0.0", None),
        (125.25, "125.25", "125.25", None),
        (100000.0, "10万", "10", "万"),
        (125000.0, "13万", "13", "万"),
        (-125000.0, "-13万", "-13", "万"),
        (149999999.0, "1亿", "1", "亿"),
        (150000000.0, "2亿", "2", "亿"),
        (-150000000.0, "-2亿", "-2", "亿"),
    ],
)
def test_native_double_display_thresholds_and_halfway_cast(value, raw, number, unit):
    metric = format_amount(value, label="金额")
    assert metric.raw == raw
    assert metric.value == Decimal(number)
    assert metric.unit == unit
    assert metric.precision == "rounded" and metric.currency is None


def test_nonfinite_display_rejected():
    with pytest.raises(ThsProtocolError):
        format_amount(float("inf"), label="金额")


def test_same_time_preserves_inputs_and_app_double_difference():
    current = decoded(amounts=(100000000, 1550000000))
    reference = decoded(day=20261102, amounts=(100000000, 1400000000))
    result = combine_turnover(current, reference)
    assert result.current.raw == "16亿"
    assert result.reference.raw == "14亿"
    assert result.comparison.raw == "+2亿"
    assert result.comparison.derivation == "app_current_minus_reference"
    assert result.current_source_value == Decimal(1550000000)
    assert result.reference_source_value == Decimal(1400000000)
    assert result.comparison_basis == "上一交易日同刻"
    assert result.source_time_label == "20261103/1339"
    assert result.reference_time_label == "20261102/1339"
    assert result.source_time is None and result.reference_time is None


def test_missing_same_time_uses_explicit_last_value_fallback():
    result = combine_turnover(
        decoded(amounts=(100000000, 1400000000)),
        decoded(day=20261102, times=(930, 1500), amounts=(100000000, 1550000000)),
    )
    assert result.comparison_basis == "上一交易日末值（同刻缺失回退）"
    assert result.reference_time_label == "20261102/1500"
    assert result.comparison.raw == "-2亿"
    assert result.comparison.label == "较上一交易日末值"


def test_zero_amount_is_not_missing_and_no_change_is_zero():
    result = combine_turnover(
        decoded(amounts=(0, 0)), decoded(day=20261102, amounts=(0, 0))
    )
    assert result.current.value == Decimal(0)
    assert result.comparison.raw == "0.0"


def test_reference_day_must_match_calendar():
    with pytest.raises(ThsProtocolError, match="reference date"):
        combine_turnover(decoded(), decoded(day=20261030))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"code": "000001"},
        {"market": "33"},
        {"day": None},
        {"day": 20260230},
        {"first": 1},
        {"omit": 19},
        {"omit": 1},
        {"amounts": (1, -1)},
        {"times": (1339, 930)},
    ],
)
def test_identity_date_points_and_incremental_boundaries(kwargs):
    with pytest.raises(ThsProtocolError):
        decoded(**kwargs)


@pytest.mark.parametrize(
    "offset,fmt,value",
    [
        (2, "<i", 2),
        (6, "<i", 0x1100),
        (10, "<H", 2),
        (12, "<i", 0),
        (16, "<i", 0),
        (24, "<i", 1),
    ],
)
def test_response_header_identity_flags_length_and_layout(offset, fmt, value):
    head, body = wire()
    changed = bytearray(head)
    struct.pack_into(fmt, changed, offset, value)
    with pytest.raises(ThsProtocolError):
        decode_turnover_response(bytes(changed), body, package_id=1, instance_id=1)


def test_response_truncation_rejected():
    head, body = wire()
    for length in range(len(body)):
        with pytest.raises(ThsProtocolError):
            decode_turnover_response(head, body[:length], package_id=1, instance_id=1)


def install_transport(monkeypatch, *, first_failure=None, current_day=20261103):
    module = importlib.import_module("pyths._market_turnover")
    transports = []
    deadlines = []

    class Transport:
        def __init__(self, **kwargs):
            self.index = len(transports)
            self.closed = False
            self.packet = None
            transports.append(self)

        def connect(self, endpoint, *, deadline, connect_timeout):
            deadlines.append(deadline)
            if self.index == 0 and first_failure is not None:
                raise first_failure

        def send(self, packet, *, deadline):
            deadlines.append(deadline)
            self.packet = packet

        def receive(self, *, deadline):
            deadlines.append(deadline)
            length = int.from_bytes(self.packet[:2], "little")
            body = decode_body(self.packet[length:])
            previous = b"id=1271" in body
            head, payload = wire(curve(day=20261102 if previous else current_day))
            return head + payload

        def close(self):
            self.closed = True

    monkeypatch.setattr(module, "TcpTransport", Transport)
    monkeypatch.setattr(
        module,
        "establish_session",
        lambda *a, **k: type("Session", (), {"session_id": "synthetic"})(),
    )
    return module, transports, deadlines


def test_separate_connections_share_deadline_and_calendar_endtime(monkeypatch):
    _, transports, deadlines = install_transport(monkeypatch)
    deadline = time.monotonic() + 10
    result, received = query_turnover(
        endpoint=("synthetic", 1),
        app_config="synthetic",
        app_info="synthetic",
        connect_timeout=1,
        deadline=deadline,
    )
    assert len(transports) == 2 and all(t.closed for t in transports)
    assert deadlines and set(deadlines) == {deadline}
    packet = transports[1].packet
    body = decode_body(packet[int.from_bytes(packet[:2], "little") :])
    assert b"endtime=20261102" in body
    assert result.source_time_label == "20261103/1339"
    assert received.utcoffset().total_seconds() == 0


def test_safe_network_retry_is_finite_and_resources_released(monkeypatch):
    _, transports, deadlines = install_transport(
        monkeypatch, first_failure=ThsNetworkError("synthetic")
    )
    deadline = time.monotonic() + 10
    query_turnover(
        endpoint=("synthetic", 1),
        app_config="synthetic",
        app_info="synthetic",
        connect_timeout=1,
        deadline=deadline,
        retries=1,
    )
    assert len(transports) == 3 and all(t.closed for t in transports)
    assert set(deadlines) == {deadline}


def test_protocol_error_is_not_retried(monkeypatch):
    _, transports, _ = install_transport(
        monkeypatch, first_failure=ThsProtocolError("synthetic")
    )
    with pytest.raises(ThsProtocolError):
        query_turnover(
            endpoint=("synthetic", 1),
            app_config="synthetic",
            app_info="synthetic",
            connect_timeout=1,
            deadline=time.monotonic() + 10,
            retries=1,
        )
    assert len(transports) == 1 and transports[0].closed


def test_unknown_calendar_year_prevents_reference_network_call(monkeypatch):
    _, transports, _ = install_transport(monkeypatch, current_day=20270104)
    with pytest.raises(ThsBusinessError):
        query_turnover(
            endpoint=("synthetic", 1),
            app_config="synthetic",
            app_info="synthetic",
            connect_timeout=1,
            deadline=time.monotonic() + 10,
        )
    assert len(transports) == 1 and transports[0].closed


def test_expired_budget_prevents_connection(monkeypatch):
    _, transports, _ = install_transport(monkeypatch)
    with pytest.raises(ThsNetworkError):
        query_turnover(
            endpoint=("synthetic", 1),
            app_config="synthetic",
            app_info="synthetic",
            connect_timeout=1,
            deadline=time.monotonic() - 1,
        )
    assert not transports
