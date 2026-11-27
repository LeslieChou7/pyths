import struct

from pyths._request import encode_quote_request, encode_stop_request
from pyths._transform import checksum, decode_body


def test_quote_request_independent_body_and_header():
    packet = encode_quote_request(
        stock_code="000001",
        market="33",
        package_id=7,
        frame_id=8,
        instance_id=9,
        app_info="synthetic",
        session_id="synthetic session",
    )
    assert packet[:12] == b"\x22\x00\x07\x00\x00\x00\x00\x00\x01\x01\x03\xff"
    assert packet[16:20] == b"\x08\x00\x00\x00"
    assert packet[24:28] == b"\x00" * 4
    body = (
        b"[frame]\r\nid=8\r\npageList=9\r\nreqPage=9\r\nreqPageCount=1\r\n"
        b"[9]\r\nid=1269\r\nstockcode=000001\r\nmarketcode=33\r\n"
    )
    assert int.from_bytes(packet[20:24], "little") == len(body)
    assert int.from_bytes(packet[12:16], "little") == len(packet) - 34
    assert decode_body(packet[34:]) == body


def test_stop_request_has_independent_header_body_and_session_checksum():
    packet = encode_stop_request(
        package_id=8, frame_id=2267, app_info="synthetic", session_id="private-sentinel"
    )
    expected = b"[frame]\r\nid=2267\r\npageList=\r\n"
    assert packet[:12] == struct.pack("<HiiH", 34, 8, 0x01060000, 0xFF03)
    assert packet[16:24] == struct.pack("<ii", 2267, len(expected))
    assert decode_body(packet[34:]) == expected
    assert int.from_bytes(packet[28:32], "little") == checksum(
        b"syntheticTONG" + expected + b"private-sentinel"
    )
