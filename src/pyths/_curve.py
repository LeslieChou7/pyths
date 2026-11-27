"""mru.c/mru.e/f支持的cv1/cv3数值曲线子集；纯离线、有界解析。"""

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from ._tb3_number import decode_number
from ._tb3_rle import decode
from .errors import ThsProtocolError

MAX_CURVE_BYTES = 4 * 1024 * 1024
type CurveValue = int | Decimal | None
type CurveExtension = CurveValue | str | tuple[int, ...] | bytes


@dataclass(frozen=True)
class CurveData:
    """单个响应的曲线段；first_index不隐式补前缀或合并历史数据。"""

    first_index: int
    row_count: int
    columns: tuple[tuple[int, int, int], ...]
    fields: Mapping[int, tuple[CurveValue, ...]]
    extensions: Mapping[int, CurveExtension]
    raw_header_word: int


def _extensions(data: bytes, start: int, end: int) -> Mapping[int, CurveExtension]:
    position = start

    def take(size: int) -> bytes:
        nonlocal position
        if size < 0 or position + size > end:
            raise ThsProtocolError("curve: truncated extension")
        result = data[position : position + size]
        position += size
        return result

    result: dict[int, CurveExtension] = {}
    if position == end:
        return MappingProxyType(result)
    count = int.from_bytes(take(2), "little", signed=True)
    if not 0 <= count <= 256:
        raise ThsProtocolError("curve: extension count limit")
    for _ in range(count):
        tag = int.from_bytes(take(2), "little")
        key, kind = tag & 36863, tag & 28672
        if key in result:
            raise ThsProtocolError("curve: duplicate extension")
        if kind == 0:
            size = int.from_bytes(take(2), "little")
            try:
                result[key] = take(size * 2).decode("utf-16-le")
            except UnicodeDecodeError:
                raise ThsProtocolError("curve: invalid UTF-16 extension") from None
        elif kind == 4096:
            result[key] = decode_number(int.from_bytes(take(4), "little"))
        elif kind == 8192:
            result[key] = int.from_bytes(take(4), "little", signed=True)
        elif kind == 12288:
            result[key] = int.from_bytes(take(2), "little", signed=True)
        elif kind == 20480:
            # mru.f skips this fixed-width value. Preserve opaque bytes rather
            # than guessing floating-point semantics or silently losing it.
            result[key] = take(8)
        elif kind == 24576:
            size = int.from_bytes(take(2), "little", signed=True)
            if not 0 <= size <= 100:
                raise ThsProtocolError("curve: extension array limit")
            result[key] = tuple(
                int.from_bytes(take(4), "little", signed=True) for _ in range(size)
            )
        else:
            # Nested structures and unrecognized encodings are not scalars.
            raise ThsProtocolError("curve: unsupported extension structure")
    if any(take(end - position)):
        raise ThsProtocolError("curve: unexplained extension bytes")
    return MappingProxyType(result)


def parse_curve(data: bytes) -> CurveData:
    """读取cv3内部RLE/转置或cv1直排数值列，不推断字段单位或时间。"""
    if not 40 <= len(data) <= MAX_CURVE_BYTES or data[:6] not in (
        b"cv3.0\x00",
        b"cv1.0\x00",
    ):
        raise ThsProtocolError("curve: invalid or oversized header")
    rows, raw_word, first_index, offset, width, count = struct.unpack_from(
        "<iIiHHH", data, 6
    )
    if not 1 <= rows <= 10000 or not 1 <= count <= 256 or first_index < 0:
        raise ThsProtocolError("curve: invalid counts or first index")
    header_end = 24 + count * 4
    size = rows * width
    if not header_end <= offset <= len(data) or not 1 <= size <= MAX_CURVE_BYTES:
        raise ThsProtocolError("curve: invalid data bounds")
    columns = tuple(struct.unpack_from("<HBB", data, 24 + i * 4) for i in range(count))
    keys = tuple(tag & 36863 for tag, _, _ in columns)
    if len(set(keys)) != count:
        raise ThsProtocolError("curve: duplicate column")
    if sum(length for _, length, _ in columns) != width:
        raise ThsProtocolError("curve: row width mismatch")
    if any(
        (tag & 28672, length) not in ((4096, 4), (8192, 4), (12288, 2))
        for tag, length, _ in columns
    ):
        raise ThsProtocolError("curve: unsupported column encoding")
    extensions = _extensions(data, header_end, offset)
    if data[:6] == b"cv1.0\x00":
        if len(data) - offset != size:
            raise ThsProtocolError("curve: uncompressed size mismatch")
        unpacked = data[offset:]
    else:
        if offset + 8 > len(data):
            raise ThsProtocolError("curve: truncated compression header")
        packed_length = int.from_bytes(data[offset : offset + 4], "little")
        declared_size = int.from_bytes(data[offset + 4 : offset + 8], "big")
        if packed_length != len(data) - offset - 4 or declared_size != size:
            raise ThsProtocolError("curve: compressed size mismatch")
        transposed = decode(data[offset + 8 :], size, limit=MAX_CURVE_BYTES)
        unpacked = bytes(
            transposed[column * rows + row]
            for row in range(rows)
            for column in range(width)
        )
    fields: dict[int, tuple[CurveValue, ...]] = {}
    column_offset = 0
    for tag, length, _ in columns:
        values: list[CurveValue] = []
        for row in range(rows):
            position = row * width + column_offset
            value = unpacked[position : position + length]
            if tag & 28672 == 4096:
                values.append(decode_number(int.from_bytes(value, "little")))
            else:
                values.append(int.from_bytes(value, "little", signed=True))
        fields[tag & 36863] = tuple(values)
        column_offset += length
    return CurveData(
        first_index,
        rows,
        columns,
        MappingProxyType(fields),
        extensions,
        raw_word,
    )
