"""Independent synthetic curve layouts; no captured bytes or network access."""

import struct
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from pyths._curve import MAX_CURVE_BYTES, parse_curve
from pyths.errors import ThsProtocolError


def string_entry(key, value):
    return struct.pack("<HH", key, len(value)) + value.encode("utf-16-le")


def extensions():
    entries = [
        string_entry(4, "TEST"),
        string_entry(55, "指数"),
        struct.pack("<HI", 4096 | 19, 0xA000007D),
        struct.pack("<Hi", 8192 | 32787, 1),
        struct.pack("<HHii", 24576 | 32770, 2, 93000, 150000),
        struct.pack("<H", 20480 | 100) + b"opaque!!",
        struct.pack("<Hh", 12288 | 101, -7),
        struct.pack("<HI", 4096 | 102, 0x80000000),
    ]
    return struct.pack("<h", len(entries)) + b"".join(entries)


def literal_rle(data):
    # Independent ypu literal stream. Zero control bits copy two bytes after
    # the first literal, with eager control-byte reload every eighth bit.
    packed = bytearray([0, data[0]])
    position, left = 1, 8
    padded = data + b"\x00"
    while position < len(data):
        left -= 1
        if left == 0:
            packed.append(0)
            left = 8
        packed.extend(padded[position : position + 2])
        position += 2
    return bytes(packed)


def sample(*, compressed=True, first_index=3, meta=None):
    columns = [(8192 | 1, 4, 4), (4096 | 33016, 4, 4), (12288 | 99, 2, 0)]
    rows = [struct.pack("<iIh", 93000000, 0xA800007D, 0)]
    rows.append(struct.pack("<iIh", 93001000, 0x80000000, -7))
    meta = extensions() if meta is None else meta
    offset = 24 + 4 * len(columns) + len(meta)
    head = (
        (b"cv3.0\x00" if compressed else b"cv1.0\x00")
        + struct.pack("<iIiHHH", 2, 0xFFFFFFFF, first_index, offset, 10, len(columns))
        + b"".join(struct.pack("<HBB", *column) for column in columns)
        + meta
    )
    if not compressed:
        return head + b"".join(rows)
    transposed = bytes(rows[row][column] for column in range(10) for row in range(2))
    packed = literal_rle(transposed)
    return head + struct.pack("<I", len(packed) + 4) + struct.pack(">I", 20) + packed


@pytest.mark.parametrize("compressed", [False, True])
def test_numeric_columns_extensions_and_first_index(compressed):
    curve = parse_curve(sample(compressed=compressed))
    assert curve.first_index == 3 and curve.row_count == 2
    assert curve.raw_header_word == 0xFFFFFFFF
    assert curve.fields[1] == (93000000, 93001000)
    assert curve.fields[33016] == (Decimal("-1.25"), None)
    assert curve.fields[99] == (0, -7)
    assert curve.columns[0] == (8193, 4, 4)
    assert curve.extensions[4] == "TEST"
    assert curve.extensions[55] == "指数"
    assert curve.extensions[19] == Decimal("1.25")
    assert curve.extensions[32787] == 1
    assert curve.extensions[32770] == (93000, 150000)
    assert curve.extensions[100] == b"opaque!!"
    assert curve.extensions[101] == -7
    assert curve.extensions[102] is None


def test_curve_is_immutable_and_not_implicitly_merged():
    curve = parse_curve(sample(first_index=100))
    assert len(curve.fields[1]) == 2
    with pytest.raises(TypeError):
        curve.fields[1] = ()
    with pytest.raises(TypeError):
        curve.extensions[19] = 0
    with pytest.raises(FrozenInstanceError):
        curve.first_index = 0


@pytest.mark.parametrize("compressed", [False, True])
def test_every_truncation_is_rejected(compressed):
    data = sample(compressed=compressed)
    for length in range(len(data)):
        with pytest.raises(ThsProtocolError):
            parse_curve(data[:length])


@pytest.mark.parametrize(
    "offset,fmt,value",
    [
        (6, "<i", -1),
        (6, "<i", 0),
        (6, "<i", 10001),
        (14, "<i", -1),
        (18, "<H", 20),
        (18, "<H", 65535),
        (20, "<H", 0),
        (20, "<H", 9),
        (22, "<H", 0),
        (22, "<H", 257),
        (24, "<H", 16384 | 1),
        (26, "<B", 2),
        (28, "<H", 4096 | 1),
    ],
)
def test_header_and_column_bounds(offset, fmt, value):
    data = bytearray(sample())
    struct.pack_into(fmt, data, offset, value)
    with pytest.raises(ThsProtocolError):
        parse_curve(bytes(data))


def test_unknown_signature_and_input_limit():
    with pytest.raises(ThsProtocolError):
        parse_curve(b"cv2.0\x00" + sample()[6:])
    with pytest.raises(ThsProtocolError):
        parse_curve(b"x" * (MAX_CURVE_BYTES + 1))


def test_decoded_limit_is_checked_before_decompression():
    data = bytearray(sample())
    struct.pack_into("<i", data, 6, 10000)
    struct.pack_into("<H", data, 20, 65535)
    with pytest.raises(ThsProtocolError, match="bounds"):
        parse_curve(bytes(data))


def test_compressed_lengths_and_corruption():
    original = sample()
    offset = struct.unpack_from("<H", original, 18)[0]
    for position, fmt, value in [(offset, "<I", 1), (offset + 4, ">I", 1)]:
        data = bytearray(original)
        struct.pack_into(fmt, data, position, value)
        with pytest.raises(ThsProtocolError):
            parse_curve(bytes(data))
    with pytest.raises(ThsProtocolError):
        parse_curve(original + b"\x00")
    # Contradict the literal stream with a run requiring unavailable input.
    data = bytearray(original)
    data[offset + 8] = 255
    with pytest.raises(ThsProtocolError):
        parse_curve(bytes(data))


@pytest.mark.parametrize(
    "meta",
    [
        b"\xff\xff",
        struct.pack("<h", 257),
        struct.pack("<hHH", 1, 4, 5) + b"A\x00",
        struct.pack("<hHH", 1, 4, 1) + b"\x00\xd8",
        struct.pack("<hHHii", 2, 8192 | 1, 8192 | 1, 1, 2),
        struct.pack("<hHh", 1, 24576 | 1, -1),
        struct.pack("<hHh", 1, 24576 | 1, 101),
        struct.pack("<hHh", 1, 24576 | 1, 1),
        struct.pack("<hH", 1, 28672 | 1) + b"\x06\x00\x00\x00\x00\x00",
        struct.pack("<hH", 1, 16384 | 1),
        struct.pack("<hH", 1, 20480 | 1) + b"short",
        b"\x00\x00\x01",
    ],
)
def test_bad_extensions_are_protocol_errors(meta):
    with pytest.raises(ThsProtocolError):
        parse_curve(sample(meta=meta))


def test_duplicate_extension_and_safe_unknown_scalar():
    repeated = struct.pack("<hHiHi", 2, 8192 | 9, 1, 8192 | 9, 2)
    with pytest.raises(ThsProtocolError, match="duplicate"):
        parse_curve(sample(meta=repeated))
    unknown = struct.pack("<hHi", 1, 8192 | 999, -123)
    curve = parse_curve(sample(meta=unknown))
    assert curve.extensions == {999: -123}


def test_no_extensions_zero_array_and_zero_padding():
    assert parse_curve(sample(meta=b"")).extensions == {}
    meta = struct.pack("<hHh", 1, 24576 | 99, 0) + b"\x00\x00"
    assert parse_curve(sample(meta=meta)).extensions[99] == ()


def test_cv1_rejects_appended_bytes():
    with pytest.raises(ThsProtocolError, match="uncompressed size"):
        parse_curve(sample(compressed=False) + b"\x00")
