"""Synthetic 1229/DDE framing and local substitutes; no production traffic."""

import importlib
import json
import struct
import time
from decimal import Decimal

import pytest

from pyths._market_fund import (
    combine_fund,
    decode_fund_response,
    encode_fund_body,
    encode_fund_request,
    query_fund,
    query_one,
)
from pyths._market_models import MarketFundFlowPart, MarketMetric
from pyths._transform import decode_body
from pyths.errors import ThsAuthenticationError, ThsNetworkError, ThsProtocolError


def encoded_number(amount):
    magnitude, exponent = abs(amount), 0
    while magnitude > 0x07FFFFFF and magnitude % 10 == 0:
        exponent += 1
        magnitude //= 10
    assert magnitude <= 0x07FFFFFF and exponent <= 7
    return magnitude | exponent << 28 | (0x08000000 if amount < 0 else 0)


def text(key, value):
    return struct.pack("<HH", key, len(value)) + value.encode("utf-16-le")


def curve(
    *,
    kind="sh",
    code=None,
    market=None,
    tech="DDE",
    first_index=0,
    missing=False,
    omit_time=False,
    stamp=93001000,
    omit_name=False,
):
    code = code or ("1A0001" if kind == "sh" else "399001")
    market = market or ("16" if kind == "sh" else "32")
    entries = [text(4, code), text(36103, market), text(33282, tech)]
    if not omit_name:
        entries.append(text(55, "Synthetic"))
    entries.append(struct.pack("<HI", 4096 | 19, encoded_number(100000000)))
    meta = struct.pack("<h", len(entries)) + b"".join(entries)
    columns = [(8192 | 1, 4, 4), (4096 | 33016, 4, 4)]
    if omit_time:
        columns.pop(0)
    amount = -125000000 if kind == "sh" else -250000000
    word = 0x80000000 if missing else encoded_number(amount)
    rows = [struct.pack("<iI", stamp - 1000, encoded_number(-100000000))]
    rows.append(struct.pack("<iI", stamp, word))
    if omit_time:
        rows = [row[4:] for row in rows]
    width = sum(column[1] for column in columns)
    transpose = bytes(rows[row][column] for column in range(width) for row in range(2))
    packed = bytearray([0, transpose[0]])
    position, left = 1, 8
    padded = transpose + b"\x00"
    while position < len(transpose):
        left -= 1
        if left == 0:
            packed.append(0)
            left = 8
        packed.extend(padded[position : position + 2])
        position += 2
    offset = 24 + 4 * len(columns) + len(meta)
    return (
        b"cv3.0\x00"
        + struct.pack(
            "<iIiHHH", 2, 0xFFFFFFFF, first_index, offset, width, len(columns)
        )
        + b"".join(struct.pack("<HBB", *column) for column in columns)
        + meta
        + struct.pack("<I", len(packed) + 4)
        + struct.pack(">I", width * 2)
        + packed
    )


def wire(payload=None, *, kind="sh", **kwargs):
    payload = curve(kind=kind, **kwargs) if payload is None else payload
    header = (
        struct.pack("<HiiHiii", 32, 1, 0x0120, 1, len(payload), 9001, 0)
        + b"\x00" * 4
        + struct.pack("<i", 4)
    )
    return header, payload


def decode(header, payload, *, kind="sh"):
    return decode_fund_response(header, payload, kind=kind, package_id=1, instance_id=1)


def test_request_body_preserves_empty_line_and_exact_source():
    body = encode_fund_body(kind="sh", instance_id=7, active_instances=(6, 7))
    assert body == (
        b"[frame]\r\nid=9001\r\npageList=6,7\r\nreqPage=7\r\nreqPageCount=1\r\n"
        b"[7]\r\nid=1229\r\n\r\nstockcode=1A0001\r\nmarketcode=16\r\ntech=DDE\r\n"
    )
    sz = encode_fund_body(kind="sz", instance_id=1)
    assert sz.endswith(b"stockcode=399001\r\nmarketcode=32\r\ntech=DDE\r\n")
    packet = encode_fund_request(
        kind="sh",
        package_id=4,
        instance_id=7,
        app_info="synthetic",
        session_id="synthetic",
    )
    length = int.from_bytes(packet[:2], "little")
    assert int.from_bytes(packet[16:20], "little") == 9001
    assert int.from_bytes(packet[6:10], "little") == 0x01010000
    assert decode_body(packet[length:]) == encode_fund_body(kind="sh", instance_id=7)
    assert b"traceid=" not in packet[:length]


@pytest.mark.parametrize(
    "instance,active", [(0, None), (True, None), (1, (2,)), (1, (1, 1))]
)
def test_invalid_request_instances(instance, active):
    with pytest.raises(ThsProtocolError):
        encode_fund_body(kind="sh", instance_id=instance, active_instances=active)


@pytest.mark.parametrize("kind", ["sh", "sz"])
def test_decode_identity_latest_value_and_raw_time(kind):
    result = decode(*wire(kind=kind), kind=kind)
    assert result.stock_code == ("1A0001" if kind == "sh" else "399001")
    assert result.market == ("16" if kind == "sh" else "32")
    assert result.net.value == Decimal(-125000000 if kind == "sh" else -250000000)
    assert result.net.unit is None and result.net.currency is None
    assert result.source_time is None
    assert result.source_time_label == "93001000"


@pytest.mark.parametrize(
    "offset,fmt,value",
    [
        (2, "<i", 2),
        (6, "<i", 0x1120),
        (10, "<H", 2),
        (12, "<i", 0),
        (16, "<i", 0),
        (16, "<i", 2312),
        (24, "<i", 1),
    ],
)
def test_response_header_is_strict(offset, fmt, value):
    header, payload = wire()
    changed = bytearray(header)
    struct.pack_into(fmt, changed, offset, value)
    with pytest.raises(ThsProtocolError):
        decode(bytes(changed), payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"code": "1B0300"},
        {"market": "32"},
        {"tech": "OTHER"},
        {"first_index": 1},
        {"missing": True},
        {"omit_time": True},
        {"omit_name": True},
    ],
)
def test_wrong_identity_incremental_or_missing_latest_is_not_zero(kwargs):
    with pytest.raises(ThsProtocolError):
        decode(*wire(**kwargs))


def test_truncated_extra_short_header_and_oversized_payload():
    header, payload = wire()
    for head in [header[:12], header[:26], header + b"\x00"]:
        with pytest.raises(ThsProtocolError):
            decode(head, payload)
    for body in [payload[:-1], payload + b"\x00", b"x" * (4 * 1024 * 1024 + 1)]:
        with pytest.raises(ThsProtocolError):
            decode(header, body)


def part(kind, amount, stamp="raw"):
    return MarketFundFlowPart(
        "1A0001" if kind == "sh" else "399001",
        "16" if kind == "sh" else "32",
        MarketMetric(
            "Synthetic", str(amount), Decimal(amount) if amount is not None else None
        ),
        source_time_label=stamp,
    )


def test_combined_display_keeps_both_sources_and_independent_times():
    sh, sz = decode(*wire()), decode(*wire(kind="sz", stamp=94000000), kind="sz")
    result = combine_fund(sh, sz)
    assert result.net.raw == "-3.75亿"
    assert result.net.value == Decimal("-3.75")
    assert result.net.derivation == "app_sum_float32_dde"
    assert result.net.precision == "rounded" and result.net.currency is None
    assert result.classification == "大盘资金净流入；分类算法未知"
    assert result.inflow is None and result.outflow is None
    assert [source.source_time_label for source in result.sources] == [
        "93001000",
        "94000000",
    ]


@pytest.mark.parametrize(
    "amount,expected", [(212500000, "+2.13亿"), (-212500000, "-2.13亿"), (0, "0.00亿")]
)
def test_java_format_ties_use_half_up(amount, expected):
    assert combine_fund(part("sh", amount), part("sz", 0)).net.raw == expected


@pytest.mark.parametrize(
    "amount,expected",
    [(1, "0.00亿"), (1000000, "0.01亿"), (1000001, "+0.01亿"), (-1000001, "-0.01亿")],
)
def test_positive_prefix_follows_app_float32_neutral_threshold(amount, expected):
    result = combine_fund(part("sh", amount), part("sz", 0))
    assert result.net.raw == expected
    assert result.net.value == Decimal(expected.removesuffix("亿"))


def test_float32_sum_is_explicitly_not_an_exact_decimal_sum():
    result = combine_fund(part("sh", 1677721700000000), part("sz", -1677721600000000))
    assert result.net.raw == "0.00亿"
    assert result.sources[0].net.value + result.sources[1].net.value == Decimal(
        100000000
    )


def test_missing_source_identity_and_float32_overflow_are_rejected():
    with pytest.raises(ThsProtocolError):
        combine_fund(part("sh", None), part("sz", 0))
    with pytest.raises(ThsProtocolError):
        combine_fund(part("sz", 1), part("sh", 2))
    with pytest.raises(ThsProtocolError):
        combine_fund(part("sh", "1e500"), part("sz", 0))


def reply(flags, body, *, frame=0):
    return (
        struct.pack("<HiiHiii", 26, 0, flags, 0, len(body), frame, 0)
        + b"\x00\xff"
        + body
    )


def install_transport(
    monkeypatch,
    *,
    failure=None,
    failed_source="sz",
    metadata_count=0,
    metadata_body=b"{}",
):
    module = importlib.import_module("pyths._market_fund")
    calls, failures = [], [failure] if failure else []

    class Transport:
        def __init__(self):
            self.responses = []
            self.closed = False
            self.number = sum(call[0] == "connect" for call in calls)

        def connect(self, endpoint, *, deadline, connect_timeout):
            calls.append(("connect", deadline))

        def send(self, packet, *, deadline):
            flags = int.from_bytes(packet[6:10], "little")
            calls.append(("send", flags, deadline))
            if flags == 0x70000:
                self.responses = [
                    reply(6, b"\x00" * 9, frame=2201),
                    reply(11, json.dumps({"sessionId": "synthetic"}).encode()),
                ]
            else:
                length = int.from_bytes(packet[:2], "little")
                body = decode_body(packet[length:])
                assert b"id=1229\r\n\r\n" in body
                kind = "sh" if b"stockcode=1A0001\r\n" in body else "sz"
                calls.append(("source", kind))
                header, payload = wire(
                    kind=kind, stamp=93001000 if kind == "sh" else 94000000
                )
                self.responses = [
                    reply(11, metadata_body) for _ in range(metadata_count)
                ]
                self.responses.append(header + payload)
                if failures and kind == failed_source:
                    self.responses = [failures.pop(0)]

        def receive(self, *, deadline):
            calls.append(("receive", deadline))
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        def close(self):
            if not self.closed:
                calls.append(("close",))
                self.closed = True

    monkeypatch.setattr(module, "TcpTransport", Transport)
    return calls


def query(**kwargs):
    return query_fund(
        endpoint=("127.0.0.1", 1),
        app_config="synthetic",
        app_info="synthetic",
        connect_timeout=5,
        deadline=time.monotonic() + 15,
        **kwargs,
    )


def test_two_independent_connections_shared_deadline_and_release(monkeypatch):
    calls = install_transport(monkeypatch, metadata_count=1)
    result, received = query()
    assert result.net.raw == "-3.75亿"
    assert received.tzinfo is not None
    assert [call[1] for call in calls if call[0] == "source"] == ["sh", "sz"]
    assert sum(call[0] == "close" for call in calls) == 2
    assert sum(call[0] == "connect" for call in calls) == 2
    assert (
        len({call[-1] for call in calls if call[0] in ("connect", "send", "receive")})
        == 1
    )
    assert [call[1] for call in calls if call[0] == "send"] == [0x70000, 0x01010000] * 2


@pytest.mark.parametrize("source,closed", [("sh", 1), ("sz", 2)])
def test_either_side_failure_releases_every_started_connection(
    monkeypatch, source, closed
):
    calls = install_transport(
        monkeypatch, failure=ThsProtocolError("synthetic"), failed_source=source
    )
    with pytest.raises(ThsProtocolError):
        query(retries=1)
    assert sum(call[0] == "close" for call in calls) == closed
    assert sum(call[0] == "connect" for call in calls) == closed


def test_only_safe_network_failure_retries_with_same_budget(monkeypatch):
    calls = install_transport(monkeypatch, failure=ThsNetworkError("synthetic"))
    assert query(retries=1)[0].net.raw == "-3.75亿"
    assert sum(call[0] == "close" for call in calls) == 3
    assert len({call[1] for call in calls if call[0] == "connect"}) == 1


def test_auth_failure_does_not_retry_or_return_zero(monkeypatch):
    calls = install_transport(monkeypatch, failure=ThsAuthenticationError("synthetic"))
    with pytest.raises(ThsAuthenticationError):
        query(retries=1)
    assert sum(call[0] == "connect" for call in calls) == 2
    assert sum(call[0] == "close" for call in calls) == 2


def test_default_network_failure_never_retries(monkeypatch):
    calls = install_transport(monkeypatch, failure=ThsNetworkError("synthetic"))
    with pytest.raises(ThsNetworkError):
        query()
    assert sum(call[0] == "connect" for call in calls) == 2
    assert sum(call[0] == "close" for call in calls) == 2


def test_ignored_metadata_cannot_bypass_size_limit(monkeypatch):
    calls = install_transport(
        monkeypatch, metadata_count=1, metadata_body=b"x" * (4 * 1024 * 1024 + 1)
    )
    with pytest.raises(ThsProtocolError, match="response length"):
        query()
    assert sum(call[0] == "close" for call in calls) == 1


def test_response_count_limit_and_expired_budget(monkeypatch):
    calls = install_transport(monkeypatch, metadata_count=20)
    with pytest.raises(ThsProtocolError, match="response count"):
        query()
    assert sum(call[0] == "close" for call in calls) == 1
    before = len(calls)
    with pytest.raises(ThsNetworkError, match="deadline"):
        query_one(
            kind="sh",
            endpoint=("127.0.0.1", 1),
            app_config="synthetic",
            app_info="synthetic",
            connect_timeout=5,
            deadline=time.monotonic() - 1,
        )
    assert len(calls) == before
