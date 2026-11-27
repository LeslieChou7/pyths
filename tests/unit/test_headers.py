"""合成响应头；尚无真实原始响应头对照。"""

import struct

import pytest

from pyths._headers import decode_response_header, encode_request_header
from pyths.errors import ThsProtocolError


def test_header_fields() -> None:
    data = struct.pack("<HiiHiii", 32, 17, 0x1100, 9, 100, 23, 0) + b"\x00" * 8
    header = decode_response_header(data)
    assert (header.package_id, header.instance_id, header.frame_id) == (17, 9, 23)
    assert header.flags == 0x1100
    for end in range(len(data)):
        with pytest.raises(ThsProtocolError):
            decode_response_header(data[:end])


def request_header(**changes: int | str | None) -> bytes:
    values = {
        "package_id": 1,
        "flags": 2,
        "instance_marker": -253,
        "data_length": 0,
        "frame_id": 3,
        "text_length": 4,
        "state_word": 5,
        "extension_word": 6,
        "extension_short": 7,
        "trace_id": None,
    }
    values.update(changes)
    return encode_request_header(**values)


def test_request_layout_and_trace() -> None:
    expected = struct.pack("<HiiHiiiiIH", 34, 1, 2, 0xFF03, 0, 3, 4, 5, 6, 7)
    assert request_header() == expected
    content = b"traceid=synthetic"
    expected = (36 + len(content)).to_bytes(2, "little") + expected[2:]
    assert (
        request_header(trace_id="synthetic")
        == expected + bytes([len(content), 0]) + content
    )


@pytest.mark.parametrize("value", [-32769, 65536, True])
def test_marker_no_silent_truncation(value: int) -> None:
    with pytest.raises(ThsProtocolError):
        request_header(instance_marker=value)


@pytest.mark.parametrize("value", ["", "x&y", "x=y", "x\r\n", "中文"])
def test_trace_validation(value: str) -> None:
    with pytest.raises(ThsProtocolError):
        request_header(trace_id=value)
