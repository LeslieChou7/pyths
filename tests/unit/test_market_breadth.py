"""合成统计资源，仅证明解析和失败边界。"""

import json
import struct
from decimal import Decimal

import pytest

from pyths._market_breadth import (
    decode_breadth_response,
    encode_breadth_body,
    encode_breadth_request,
    parse_resource,
)
from pyths._transform import decode_body, encode_body
from pyths.errors import ThsProtocolError


def resource(**changes):
    value = {
        "all": {
            "total": {"up": 10, "down": 2, "deuce": 0, "tp": 3},
            "data": {"zt": 5, "dt": 1},
        },
        "time": ["10:01"],
        "zt": [6],
        "dt": [2],
    }
    value.update(changes)
    return json.dumps(
        {"hs_datacenter_ztdt": [{"stockcode": "1A0001", "value": json.dumps(value)}]}
    ).encode()


def test_separate_counts_zero_and_source_time():
    breadth, limits, label = parse_resource(resource())
    assert breadth.rising.value == Decimal(10)
    assert breadth.unchanged.value == Decimal(0)
    assert breadth.total is None
    assert breadth.other[0].label == "tp"
    assert limits.limit_up.value == Decimal(6)
    assert limits.limit_down.value == Decimal(2)
    assert label == "10:01"


def test_exact_app_zero_fallback_is_explicitly_reproduced():
    _, limits, _ = parse_resource(resource(zt=[0], dt=[0]))
    assert limits.limit_up.value == Decimal(5)
    assert limits.limit_down.value == Decimal(1)


def test_no_curve_uses_aggregate_without_inventing_time():
    _, limits, label = parse_resource(resource(time=[], zt=[], dt=[]))
    assert limits.limit_up.value == Decimal(5)
    assert label is None


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{",
        b"[]",
        b"\xff",
        b"{}",
        resource(time=["10:01", "10:02"]),
        resource(zt=[-1]),
        resource(zt=[True]),
    ],
)
def test_invalid_or_inconsistent_resource(data):
    with pytest.raises(ThsProtocolError):
        parse_resource(data)


@pytest.mark.parametrize("instance", [0, -1, True, 65536])
def test_invalid_instance_before_network(instance):
    with pytest.raises(ThsProtocolError):
        encode_breadth_body(instance_id=instance)


def test_unicode_resource_request_is_fixed_business():
    body = encode_breadth_body(instance_id=7).decode("utf-16-le")
    assert "id=6001\r\npageList=7\r\n" in body
    assert "[7]\r\nid=1002\r\nkey=hs_datacenter_ztdt\r\n" in body


def test_resource_flag_is_encoded_before_network_with_synthetic_context():
    packet = encode_breadth_request(
        package_id=1,
        instance_id=7,
        app_info="synthetic-app",
        session_id="synthetic-session",
    )
    length = int.from_bytes(packet[:2], "little")
    assert int.from_bytes(packet[6:10], "little") == 0x40000
    assert decode_body(packet[length:]) == encode_breadth_body(instance_id=7)


def synthetic_response(*, instance=1, marker=b"\x03\xff"):
    data = resource()
    # Independent literal-only Snappy, wrapped in the observed native alphabet.
    value = len(data)
    size = bytearray()
    while value >= 128:
        size.append((value & 127) | 128)
        value >>= 7
    size.append(value)
    length = len(data) - 1
    width = max(1, (length.bit_length() + 7) // 8)
    packed = (
        bytes(size)
        + bytes([(59 + width) << 2])
        + length.to_bytes(width, "little")
        + data
    )
    body = encode_body(packed)
    head = struct.pack("<HiiHiii", 26, 1, 0x100B, instance, len(body), 6001, 0) + marker
    return head, body


def test_native_mapping_precedes_snappy_and_resource_parse():
    head, payload = synthetic_response()
    result, limits, _ = decode_breadth_response(
        head, payload, package_id=1, instance_id=1
    )
    assert result.rising.raw == "10"
    assert limits.limit_up.raw == "6"


@pytest.mark.parametrize("instance,marker", [(2, b"\x03\xff"), (1, b"\x00\xff")])
def test_wrong_correlation_or_unknown_mapping_marker_rejected(instance, marker):
    head, payload = synthetic_response(instance=instance, marker=marker)
    with pytest.raises(ThsProtocolError):
        decode_breadth_response(head, payload, package_id=1, instance_id=1)
