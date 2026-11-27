"""独立合成Snappy向量，非App真实报文。"""

import pytest

from pyths._compression import decode_snappy
from pyths.errors import ThsProtocolError


@pytest.mark.parametrize(
    "copy", [b"\x01\x02", b"\x0e\x02\x00", b"\x0f\x02\x00\x00\x00"]
)
def test_copy_and_overlap(copy: bytes) -> None:
    assert decode_snappy(b"\x07\x08xab" + copy) == b"xababab"


def test_literal_and_boundaries() -> None:
    assert decode_snappy(b"\x03\x08abc") == b"abc"
    assert decode_snappy(b"\x00") == b""
    for data in (b"", b"\x80" * 5, b"\x03\x08ab", b"\x03\x01\x00", b"\x00\x00x"):
        with pytest.raises(ThsProtocolError):
            decode_snappy(data)
    with pytest.raises(ThsProtocolError, match="limit"):
        decode_snappy(b"\x03\x08abc", max_output=2)


def test_extended_literal_and_varint() -> None:
    # 独立合成：130字节声明，literal长度减一使用2字节小端。
    literal = bytes(range(130))
    assert decode_snappy(b"\x82\x01\xf4\x81\x00" + literal) == literal
    for block in (
        b"\x82\x01\xf4\x81",  # 扩展长度截断
        b"\x82\x01\xf4\x81\x00" + literal[:-1],
        b"\x81\x80\x80\x80\x10",  # 声明超过uint32
        b"\x01\x02\x01",  # 2字节copy偏移截断
        b"\x01\x03\x01\x00\x00",  # 4字节copy偏移截断
    ):
        with pytest.raises(ThsProtocolError):
            decode_snappy(block)
