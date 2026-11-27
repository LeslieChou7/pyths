"""合成最小向量；真实正文在主仓库显式核对。"""

import pytest

from pyths._transform import (
    checksum,
    checksum_context,
    decode_body,
    encode_body,
    transform_request,
)
from pyths.errors import ThsProtocolError


@pytest.mark.parametrize(
    ("raw", "encoded"),
    [
        (b"", b""),
        (b"\x00", b"aa=="),
        (b"\x00\x00", b"aaa="),
        (b"\xff\xff\xff", b"////"),
    ],
)
def test_fixed_vectors(raw: bytes, encoded: bytes) -> None:
    assert encode_body(raw) == encoded
    assert decode_body(encoded) == raw


@pytest.mark.parametrize("encoded", [b"?", b"a", b"aa=", b"aa===", b"aC=="])
def test_invalid_encoding(encoded: bytes) -> None:
    with pytest.raises(ThsProtocolError):
        decode_body(encoded)


def test_limits_and_crc_empty() -> None:
    assert checksum(b"") == 0xFFFFFFFF
    assert checksum(b"abc") == 1219131554
    with pytest.raises(ThsProtocolError):
        encode_body(b"abc", max_input=2)
    with pytest.raises(ThsProtocolError):
        decode_body(b"aaaa", max_output=2)


@pytest.mark.parametrize("flags", [0x01010000, 0x00070000])
def test_request_transform_with_explicit_synthetic_context(flags: int) -> None:
    header = bytearray(34)
    header[:2] = (34).to_bytes(2, "little")
    header[6:10] = flags.to_bytes(4, "little")
    result = transform_request(
        bytes(header) + b"abc", checksum_prefix=b"", session_suffix=b""
    )
    assert int.from_bytes(result[12:16], "little") == 4
    assert int.from_bytes(result[28:32], "little") == 1219131554
    assert decode_body(result[34:]) == b"abc"
    with pytest.raises(ThsProtocolError):
        transform_request(b"", checksum_prefix=b"", session_suffix=b"")


def test_explicit_context() -> None:
    assert checksum_context(app_info="synthetic", session="") == (
        b"syntheticTONG",
        b"0",
    )
    assert checksum_context(app_info="synthetic", session="test") == (
        b"syntheticTONG",
        b"test",
    )
    with pytest.raises(ThsProtocolError):
        checksum_context(app_info="", session="")


def test_wire_native_terminators_and_missing_padding():
    from pyths._transform import decode_wire_body

    assert decode_wire_body(b"aa==\x00") == b"\x00"
    assert decode_wire_body(b"aa==") == b"\x00"
    assert decode_wire_body(b"aa==ignored") == b"\x00"
    assert decode_wire_body(b"aa\x00ignored") == b"\x00"
    assert decode_wire_body(b"aa") == b"\x00"
    assert decode_wire_body(b"aa==\x00\x00") == b"\x00"
    assert decode_wire_body(b"a\x00a==") == b""
    assert decode_wire_body(b"aaaa\n") == b"\x00\x00\x00"
    for malformed in (b"a=", b"?a=="):
        with pytest.raises(ThsProtocolError):
            decode_wire_body(malformed)
