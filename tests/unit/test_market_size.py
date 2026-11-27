"""Synthetic 1264 framing and local transport substitutes, never production I/O."""

import importlib
import json
import struct
import time
from decimal import Decimal

import pytest

from pyths._market_size import (
    decode_size_response,
    encode_size_body,
    encode_size_request,
    query_size,
)
from pyths._transform import decode_body
from pyths.errors import ThsAuthenticationError, ThsNetworkError, ThsProtocolError


def table(
    *,
    codes=("1B0300", "1B0852"),
    markets=(16, 16),
    words=(0xA000007D, 0xA80000FA),
    change_format=34,
    omit=None,
    optional=False,
    total=2,
    start=0,
):
    columns = [(55, 12), (4, 12), (8192 | 34338, 4), (4096 | 34818, 4)]
    columns = [(key, width) for key, width in columns if key & 36863 != omit]
    if optional:
        columns.append((99, 2))
    rows = bytearray()
    for index, name in enumerate(("Large", "Small")):
        values = {
            55: name.ljust(6, "\x00").encode("utf-16-le") + b"\x0f",
            4: codes[index].encode("utf-16-le") + b"\x0f",
            34338: struct.pack("<iB", markets[index], 15),
            34818: struct.pack("<IB", words[index], change_format),
            99: b"X\x00\x0f",
        }
        for key, _ in columns:
            rows.extend(values[key & 36863])
    meta = b"\x00\x00" * (1 + len(columns))
    meta += struct.pack("<HHiHi", 2, 34055 | 8192, start, 34056 | 8192, total)
    offset = 24 + 4 * len(columns) + len(meta)
    width = sum(size + 1 for _, size in columns)
    return (
        b"tb1.0\x00"
        + struct.pack("<iIiHHH", 2, 0, 0, offset, width, len(columns))
        + b"".join(struct.pack("<HBB", key, size, 0) for key, size in columns)
        + meta
        + rows
    )


def snappy(data):
    size = len(data)
    prefix = bytearray()
    while size > 127:
        prefix.append((size & 127) | 128)
        size >>= 7
    prefix.append(size)
    length = len(data) - 1
    if length < 60:
        prefix.append(length << 2)
    else:
        count = max(1, (length.bit_length() + 7) // 8)
        prefix.append((59 + count) << 2)
        prefix.extend(length.to_bytes(count, "little"))
    return bytes(prefix) + data


def wire(body=None, *, package=1, instance=1):
    payload = snappy(table() if body is None else body)
    head = (
        struct.pack("<HiiHiii", 32, package, 0x1100, instance, len(payload), 2312, 0)
        + b"\x00" * 4
        + struct.pack("<i", 18)
    )
    return head, payload


def decode(head, payload):
    return decode_size_response(head, payload, package_id=1, instance_id=1)


def test_body_fixed_parameters_and_active_instance_binding():
    actual = encode_size_body(instance_id=9, active_instances=(8, 9))
    assert actual == (
        b"[frame]\r\nid=2312\r\npageList=8,9\r\nreqPage=9\r\nreqPageCount=1\r\n"
        b"[9]\r\nid=1264\r\nstartrow=0\r\nsortid=-1\r\nrowcount=2\r\n"
        b"newrealtime=0\r\nselfstockcustom=1\r\nupdate=1\r\n"
        b"columnorder=55|4|34338|34818\r\nmarketlist=16|16\r\n"
        b"stocklist=1B0300|1B0852\r\n"
    )
    packet = encode_size_request(
        package_id=7, instance_id=9, app_info="synthetic", session_id="synthetic"
    )
    length = int.from_bytes(packet[:2], "little")
    assert struct.unpack_from("<i", packet, 2)[0] == 7
    assert struct.unpack_from("<i", packet, 16)[0] == 2312
    assert decode_body(packet[length:]) == encode_size_body(instance_id=9)
    assert b"traceid=" not in packet[:length]


@pytest.mark.parametrize(
    "instance,active",
    [(0, None), (65536, None), (True, None), (1, ()), (1, (2,)), (1, (1, 1))],
)
def test_invalid_instance_lists(instance, active):
    with pytest.raises(ThsProtocolError):
        encode_size_body(instance_id=instance, active_instances=active)


def test_names_values_and_unknown_optional_column_are_preserved():
    result = decode(*wire(table(optional=True)))
    assert result.large.label == "Large" and result.small.label == "Small"
    assert result.large.value.value == Decimal("1.25")
    assert result.large.value.raw == "1.25%"
    assert result.small.value.value == Decimal("-2.50")
    assert result.small.value.raw == "-2.50%"
    assert result.large.value.precision == "rounded"
    assert result.large.value.unit == "%"
    assert result.large.source_time is None and result.small.source_time is None


def test_zero_and_numeric_missing_sentinel_are_distinct():
    result = decode(*wire(table(words=(0xA0000000, 0x80000000))))
    assert result.large.value.value == Decimal("0.00")
    assert result.large.value.raw == "0.00%"
    assert result.small.value is None


@pytest.mark.parametrize(
    "offset,fmt,value",
    [
        (2, "<i", 2),
        (6, "<i", 0x0100),
        (10, "<H", 2),
        (12, "<i", -1),
        (12, "<i", 0),
        (16, "<i", 0),
        (16, "<i", 2267),
        (24, "<i", 1),
    ],
)
def test_wrong_header_correlation_flags_or_length(offset, fmt, value):
    head, payload = wire()
    head = bytearray(head)
    struct.pack_into(fmt, head, offset, value)
    with pytest.raises(ThsProtocolError):
        decode(bytes(head), payload)


def test_truncated_extra_and_unverified_short_headers():
    head, payload = wire()
    for candidate in (head[:12], head[:26], head + b"\x00"):
        with pytest.raises(ThsProtocolError):
            decode(candidate, payload)
    with pytest.raises(ThsProtocolError):
        decode(head, payload[:-1])
    with pytest.raises(ThsProtocolError):
        decode(head, payload + b"\x00")


@pytest.mark.parametrize(
    "args",
    [
        {"codes": ("1B0852", "1B0300")},
        {"codes": ("000001", "1B0852")},
        {"markets": (17, 16)},
        {"omit": 55},
        {"omit": 4},
        {"omit": 34338},
        {"omit": 34818},
        {"change_format": 15},
        {"start": 1},
        {"total": 3},
    ],
)
def test_wrong_identity_missing_fields_or_bounds(args):
    with pytest.raises(ThsProtocolError):
        decode(*wire(table(**args)))


def test_table_truncation_row_count_and_expansion_limit():
    body = table()
    with pytest.raises(ThsProtocolError):
        decode(*wire(body[:-1]))
    changed = bytearray(body)
    struct.pack_into("<i", changed, 6, 1)
    with pytest.raises(ThsProtocolError):
        decode(*wire(bytes(changed)))
    head, _ = wire()
    # Independent varint declaration of 4MiB+1, no output allocation needed.
    payload = b"\x81\x80\x80\x02"
    changed_head = bytearray(head)
    struct.pack_into("<i", changed_head, 12, len(payload))
    with pytest.raises(ThsProtocolError, match="output limit"):
        decode(bytes(changed_head), payload)


def handshake_reply(flags, body, *, frame=0):
    return (
        struct.pack("<HiiHiii", 26, 0, flags, 0, len(body), frame, 0)
        + b"\x00\xff"
        + body
    )


def install_transport(
    monkeypatch, *, failure=None, metadata_count=0, metadata_body=b"{}"
):
    module = importlib.import_module("pyths._market_size")
    calls = []
    remaining_failures = [failure] if failure is not None else []

    class Transport:
        def __init__(self):
            self.responses = []
            self.closed = False

        def connect(self, endpoint, *, deadline, connect_timeout):
            calls.append(("connect", deadline))
            if remaining_failures and isinstance(
                remaining_failures[0], ThsNetworkError
            ):
                raise remaining_failures.pop(0)

        def send(self, packet, *, deadline):
            flags = int.from_bytes(packet[6:10], "little")
            calls.append(("send", flags, deadline))
            if flags == 0x70000:
                self.responses = [
                    handshake_reply(6, b"\x00" * 9, frame=2201),
                    handshake_reply(
                        11, json.dumps({"sessionId": "synthetic"}).encode()
                    ),
                ]
            else:
                length = int.from_bytes(packet[:2], "little")
                assert b"id=1264\r\n" in decode_body(packet[length:])
                head, payload = wire()
                self.responses = [
                    handshake_reply(11, metadata_body) for _ in range(metadata_count)
                ]
                self.responses.append(head + payload)
                if remaining_failures:
                    self.responses = [remaining_failures.pop(0)]

        def receive(self, *, deadline):
            calls.append(("receive", deadline))
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        def close(self):
            if not self.closed:
                calls.append(("close",))
                self.closed = True

    monkeypatch.setattr(module, "TcpTransport", Transport)
    return calls


def query(**kwargs):
    return query_size(
        endpoint=("127.0.0.1", 1),
        app_config="synthetic",
        app_info="synthetic",
        connect_timeout=5,
        deadline=time.monotonic() + 15,
        **kwargs,
    )


def test_query_cross_layer_success_and_independent_release(monkeypatch):
    calls = install_transport(monkeypatch, metadata_count=1)
    result, received_at = query()
    assert result.large.label == "Large"
    assert received_at.tzinfo is not None
    assert sum(c[0] == "connect" for c in calls) == 1
    assert sum(c[0] == "close" for c in calls) == 1
    sends = [c for c in calls if c[0] == "send"]
    assert [c[1] for c in sends] == [0x70000, 0x01010000]
    assert len({c[-1] for c in calls if c[0] in ("connect", "send", "receive")}) == 1


def test_query_retry_is_finite_and_uses_same_deadline(monkeypatch):
    calls = install_transport(monkeypatch, failure=ThsNetworkError("synthetic"))
    result, _ = query(retries=1)
    assert result.large.label == "Large"
    assert sum(c[0] == "connect" for c in calls) == 2
    assert sum(c[0] == "close" for c in calls) == 2
    assert len({c[1] for c in calls if c[0] == "connect"}) == 1


@pytest.mark.parametrize("failure", [ThsProtocolError, ThsAuthenticationError])
def test_query_nonnetwork_failures_never_retry(monkeypatch, failure):
    calls = install_transport(monkeypatch, failure=failure("synthetic"))
    with pytest.raises(failure):
        query(retries=1)
    assert sum(c[0] == "connect" for c in calls) == 1
    assert sum(c[0] == "close" for c in calls) == 1


def test_query_response_count_limit_releases(monkeypatch):
    calls = install_transport(monkeypatch, metadata_count=20)
    with pytest.raises(ThsProtocolError, match="response count limit"):
        query()
    assert sum(c[0] == "close" for c in calls) == 1


def test_query_metadata_cannot_bypass_response_size_limit(monkeypatch):
    calls = install_transport(
        monkeypatch, metadata_count=1, metadata_body=b"x" * (4 * 1024 * 1024 + 1)
    )
    with pytest.raises(ThsProtocolError, match="payload length"):
        query()
    assert sum(c[0] == "close" for c in calls) == 1


def test_expired_budget_never_connects(monkeypatch):
    calls = install_transport(monkeypatch)
    with pytest.raises(ThsNetworkError, match="deadline"):
        query_size(
            endpoint=("127.0.0.1", 1),
            app_config="synthetic",
            app_info="synthetic",
            connect_timeout=5,
            deadline=time.monotonic() - 1,
        )
    assert calls == []
