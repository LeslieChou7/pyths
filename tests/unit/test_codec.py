"""合成正文预期；真实载荷对照由主仓库显式执行。"""

import pytest

from pyths._codec import (
    decode_tb1_header,
    decode_tb1_strings,
    encode_1269_body,
    format_table_string,
)
from pyths.errors import ThsProtocolError


def test_request_body() -> None:
    assert encode_1269_body(
        stock_code="000001", market="33", frame_id=2, instance_id=3
    ) == (
        b"[frame]\r\nid=2\r\npageList=3\r\nreqPage=3\r\n"
        b"reqPageCount=1\r\n[3]\r\nid=1269\r\nstockcode=000001\r\nmarketcode=33\r\n"
    )


@pytest.mark.parametrize("value", ["", "x\r\nid=1", "x\x00", "[x]", "x=y"])
def test_parameter_injection(value: str) -> None:
    with pytest.raises(ThsProtocolError, match="invalid parameter"):
        encode_1269_body(stock_code=value, market="33", frame_id=2, instance_id=3)


def test_synthetic_table_header() -> None:
    import struct

    data = b"tb1.0\x00" + struct.pack("<iIiHHHHBB", 1, 0, 0, 28, 5, 1, 8198, 4, 0)
    header = decode_tb1_header(data)
    assert header.row_count == 1
    assert header.columns == ((8198, 4, 0),)
    for end in range(len(data)):
        with pytest.raises(ThsProtocolError):
            decode_tb1_header(data[:end])


def synthetic_strings() -> bytes:
    """合成一个字段，非真实行情样本。"""
    import struct

    metadata = b"\x00\x00\x00\x00" + struct.pack("<HHHi", 1, 0xE008, 1, 10)
    offset = 28 + len(metadata)
    return (
        b"tb1.0\x00"
        + struct.pack("<iIiHHHHBB", 1, 0, 0, offset, 9, 1, 0, 8, 0)
        + metadata
        + "1.2\x00".encode("utf-16-le")
        + b"\x0a"
    )


def test_transposed_string_and_truncation() -> None:
    data = synthetic_strings()
    table = decode_tb1_strings(data)
    assert table.cells == ((10, "1.2", 10),)
    assert table.header.row_count == 1
    assert table.cell_offsets == (table.header.data_offset,)
    assert table.extensions[0][:2] == (32776, 0xE008)
    for end in range(len(data)):
        with pytest.raises(ThsProtocolError):
            decode_tb1_strings(data[:end])
    with pytest.raises(ThsProtocolError, match="trailing"):
        decode_tb1_strings(data + b"\x00")


def test_invalid_transpose_mapping() -> None:
    data = bytearray(synthetic_strings())
    data[6:10] = (2).to_bytes(4, "little")
    with pytest.raises(ThsProtocolError, match="transpose"):
        decode_tb1_strings(bytes(data))


@pytest.mark.parametrize(
    ("flag", "suffix"),
    [(0, ""), (16, "万手"), (32, "%"), (48, "亿"), (64, "万"), (80, "万亿")],
)
def test_format_suffix(flag: int, suffix: str) -> None:
    assert format_table_string("1.2", flag | 10) == "1.2" + suffix
