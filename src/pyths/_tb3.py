"""Observed tb3.0 row layout; display formatting and business mapping separate."""

import struct
from dataclasses import dataclass
from decimal import Decimal

from ._tb3_number import decode_number
from ._tb3_rle import decode


def _text(data: bytes) -> str:
    try:
        return data.decode("utf-16-le")
    except UnicodeDecodeError:
        raise ThsProtocolError("table: invalid UTF-16 text") from None


from .errors import ThsProtocolError


@dataclass(frozen=True)
class Cell:
    value: str | int | Decimal | None
    format_byte: int
    offset: int


def metadata(data: bytes) -> dict[int, str | int]:
    """Read caption/column titles then the observed scalar extensions."""
    if len(data) < 24 or data[:6] not in (b"tb3.0\x00", b"tb1.0\x00"):
        raise ThsProtocolError("unsupported table header")
    end, count = struct.unpack_from("<H2xH", data, 18)
    position = 24 + count * 4
    if not position <= end <= len(data):
        raise ThsProtocolError("metadata bounds")

    def take(size: int) -> bytes:
        nonlocal position
        if size < 0 or position + size > end:
            raise ThsProtocolError("truncated metadata")
        value = data[position : position + size]
        position += size
        return value

    def text() -> str:
        length = int.from_bytes(take(2), "little")
        return _text(take(length * 2))

    text()  # caption
    for _ in range(count):
        text()
    result: dict[int, str | int] = {}
    if position == end:
        return result
    length = int.from_bytes(take(2), "little", signed=True)
    if not 0 <= length <= 100:
        raise ThsProtocolError("extension count limit")
    for _ in range(length):
        tag = int.from_bytes(take(2), "little")
        key, kind = tag & 36863, tag & 28672
        if key in result:
            raise ThsProtocolError("duplicate extension")
        if kind == 0:
            result[key] = text()
        elif kind == 8192 and key != 34068:
            result[key] = int.from_bytes(take(4), "little", signed=True)
        else:
            raise ThsProtocolError("unsupported extension")
    if any(take(end - position)):
        raise ThsProtocolError("unexplained metadata bytes")
    return result


def parse(data: bytes) -> tuple[dict[int, Cell], ...]:
    """Read the observed compressed multi-column table with bounded output."""
    if len(data) < 24 or data[:6] not in (b"tb3.0\x00", b"tb1.0\x00"):
        raise ThsProtocolError("unsupported table header")
    rows, _, _, offset, width, count = struct.unpack_from("<iIiHHH", data, 6)
    end = 24 + count * 4
    if not 0 <= rows <= 10000 or not 1 <= count <= 256:
        raise ThsProtocolError("table count limit")
    if not end <= offset <= len(data) or width * rows > 8388608:
        raise ThsProtocolError("table bounds")
    columns = tuple(struct.unpack_from("<HBB", data, 24 + i * 4) for i in range(count))
    if sum(c[1] + 1 for c in columns) != width:
        raise ThsProtocolError("row width mismatch")
    if len({c[0] & 36863 for c in columns}) != count:
        raise ThsProtocolError("duplicate column")
    if rows == 0:
        raise ThsProtocolError("empty table layout not verified")
    if data[:6] == b"tb1.0\x00":
        if len(data) - offset != rows * width:
            raise ThsProtocolError("uncompressed size mismatch")
        unpacked = data[offset:]
    else:
        if offset + 8 > len(data):
            raise ThsProtocolError("truncated compression header")
        packed_length = int.from_bytes(data[offset : offset + 4], "little")
        size = int.from_bytes(data[offset + 4 : offset + 8], "big")
        if size != rows * width or packed_length != len(data) - offset - 4:
            raise ThsProtocolError("compressed size mismatch")
        raw = decode(data[offset + 8 :], size)
        unpacked = bytes(raw[c * rows + r] for r in range(rows) for c in range(width))
    result: list[dict[int, Cell]] = []
    for row in range(rows):
        position = row * width
        cells: dict[int, Cell] = {}
        for tag, length, _ in columns:
            body = unpacked[position : position + length]
            kind = tag & 28672
            value: str | int | Decimal | None
            if kind == 0 and length % 2 == 0:
                value = _text(body).strip("".join(chr(n) for n in range(33)))
            elif kind == 4096 and length == 4:
                value = decode_number(int.from_bytes(body, "little"))
            elif (kind, length) in ((8192, 4), (12288, 2)):
                value = int.from_bytes(body, "little", signed=True)
            else:
                raise ThsProtocolError("unsupported column encoding")
            cells[tag & 36863] = Cell(value, unpacked[position + length], position)
            position += length + 1
        result.append(cells)
    return tuple(result)
