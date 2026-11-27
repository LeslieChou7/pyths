"""Synthetic wire framing; not evidence of production error codes."""

import struct

import pytest

from pyths._ranking_response import decode_ranking_response
from pyths.errors import ThsProtocolError


def wire():
    # Build caption, one title, two scalar extension entries independently.
    ext = b"\x00" * 4 + struct.pack("<HH i H i", 2, 34055 | 8192, 0, 34056 | 8192, 1)
    offset = 28 + len(ext)
    table = (
        b"tb3.0\x00"
        + struct.pack("<iIiHHH", 1, 0, 0, offset, 3, 1)
        + struct.pack("<HBB", 4, 2, 0)
        + ext
        + struct.pack("<I", 8)
        + struct.pack(">I", 3)
        + b"\x00A\x00\x0f"
    )
    # Snappy independent single literal; input length exceeds short-literal limit.
    size = len(table)
    payload = (
        bytes([size, (size - 1) << 2]) + table
        if size < 60
        else bytes([size, 240, size - 1]) + table
    )
    head = (
        struct.pack("<HiiHiii", 32, 7, 0x1130, 8, len(payload), 2312, 0)
        + b"\x00" * 4
        + b"\x09\x00\x00\x00"
    )
    return head, payload


def test_valid_wire_and_unknown_final_extension():
    head, payload = wire()
    rows, fields = decode_ranking_response(
        head, payload, package_id=7, instance_id=8, start=0
    )
    assert rows[0][4].value == "A"
    assert fields[34056] == 1


@pytest.mark.parametrize(
    "offset,fmt,value",
    [
        (2, "<i", 9),
        (6, "<i", 0x1100),
        (10, "<H", 9),
        (12, "<i", 1),
        (16, "<i", 0),
        (24, "<i", 1),
    ],
)
def test_reject_mismatch(offset, fmt, value):
    head, payload = wire()
    head = bytearray(head)
    struct.pack_into(fmt, head, offset, value)
    with pytest.raises(ThsProtocolError):
        decode_ranking_response(
            bytes(head), payload, package_id=7, instance_id=8, start=0
        )


def test_page_origin_mismatch_and_corrupt_compression():
    head, payload = wire()
    with pytest.raises(ThsProtocolError):
        decode_ranking_response(head, payload, package_id=7, instance_id=8, start=24)
    with pytest.raises(ThsProtocolError):
        decode_ranking_response(
            head, payload[:-1], package_id=7, instance_id=8, start=0
        )


def test_observed_ranking_initial_header_is_explicitly_scoped():
    head, payload = wire()
    initial = bytearray(head[:24] + b"\x00\xff")
    struct.pack_into("<H", initial, 0, 26)
    struct.pack_into("<i", initial, 16, 0)
    with pytest.raises(ThsProtocolError):
        decode_ranking_response(
            bytes(initial), payload, package_id=7, instance_id=8, start=0
        )
    rows, _ = decode_ranking_response(
        bytes(initial),
        payload,
        package_id=7,
        instance_id=8,
        start=0,
        allow_initial_frame_zero=True,
    )
    assert len(rows) == 1
    for offset, fmt, value in [(2, "<i", -1), (10, "<H", 9), (24, "<H", 0)]:
        bad = bytearray(initial)
        struct.pack_into(fmt, bad, offset, value)
        with pytest.raises(ThsProtocolError):
            decode_ranking_response(
                bytes(bad),
                payload,
                package_id=7,
                instance_id=8,
                start=0,
                allow_initial_frame_zero=True,
            )


def test_normal_26_byte_ranking_header():
    head, payload = wire()
    head = bytearray(head[:24] + b"\x00\xff")
    struct.pack_into("<H", head, 0, 26)
    rows, _ = decode_ranking_response(
        bytes(head), payload, package_id=7, instance_id=8, start=0
    )
    assert len(rows) == 1
    struct.pack_into("<i", head, 16, 2267)
    with pytest.raises(ThsProtocolError):
        decode_ranking_response(
            bytes(head), payload, package_id=7, instance_id=8, start=0
        )


def test_out_of_range_origin_with_first_page_rows_is_not_empty():
    # Reproduce observed start==total plus a nonempty first-page body.
    from pyths._headers import decode_response_header
    from tests.ranking_fixture import reply, table

    packet = reply(0x1130, table(2), package=1, instance=1)
    header = decode_response_header(packet)
    with pytest.raises(ThsProtocolError, match="invalid page bounds"):
        decode_ranking_response(
            packet[: header.length],
            packet[header.length :],
            package_id=1,
            instance_id=1,
            start=2,
            allow_initial_frame_zero=True,
        )
