"""Synthetic framing helpers; no production data."""

import struct


def table(start):
    columns = [(4, 12), (36103, 4), (55, 8), (4096 | 34818, 4)]
    row = (
        "000001".encode("utf-16-le")
        + b"\x0f"
        + "33".encode("utf-16-le")
        + b"\x0f"
        + "Test".encode("utf-16-le")
        + b"\x0f"
        + struct.pack("<I", 0xA0000001)
        + b"\x2a"
    )
    # Independent literal-only ypu stream, with eager control-byte reload.
    packed = bytearray([0, row[0]])
    position, left = 1, 8
    padded = row + b"\x00"
    while position < len(row):
        left -= 1
        if left == 0:
            packed.append(0)
            left = 8
        packed.extend(padded[position : position + 2])
        position += 2
    metadata = b"\x00" * 10 + struct.pack(
        "<HH i H i", 2, 34055 | 8192, start, 34056 | 8192, 2
    )
    offset = 24 + 4 * len(columns) + len(metadata)
    body = (
        b"tb3.0\x00"
        + struct.pack("<iIiHHH", 1, 0, 0, offset, len(row), len(columns))
        + b"".join(struct.pack("<HBB", tag, width, 0) for tag, width in columns)
        + metadata
        + struct.pack("<I", len(packed) + 4)
        + struct.pack(">I", len(row))
        + packed
    )
    size = len(body)
    return bytes([size, 240, size - 1]) + body


def reply(flags, body, *, frame=0, instance=0, package=0, marker=b"\x00\xff"):
    return (
        struct.pack("<HiiHiii", 26, package, flags, instance, len(body), frame, 0)
        + marker
        + body
    )
