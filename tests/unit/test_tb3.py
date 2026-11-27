"""Minimal synthetic tb3 layout, independent of production captures."""

import struct
import unittest

from pyths._tb3 import metadata, parse
from pyths.errors import ThsProtocolError


def sample():
    head = b"tb3.0\x00" + struct.pack("<iIiHHH", 1, 0, 0, 28, 3, 1)
    column = struct.pack("<HBB", 4, 2, 0)
    packed = b"\x00A\x00\x0f"
    return (
        head
        + column
        + struct.pack("<I", len(packed) + 4)
        + struct.pack(">I", 3)
        + packed
    )


class TableTests(unittest.TestCase):
    def test_observed_uncompressed_single_row_branch(self):
        head = b"tb1.0\x00" + struct.pack("<iIiHHH", 1, 0, 0, 28, 3, 1)
        data = head + struct.pack("<HBB", 4, 2, 0) + b"A\x00\x0f"
        self.assertEqual(parse(data)[0][4].value, "A")
        with self.assertRaises(ThsProtocolError):
            parse(data + b"\x00")

    def test_invalid_utf16_is_protocol_error(self):
        data = bytearray(sample())
        data[-2] = 0xD8
        with self.assertRaises(ThsProtocolError):
            parse(bytes(data))

    def test_scalar_extensions_and_padding(self):
        data = sample()
        ext = b"\x00" * 4 + struct.pack("<HH i", 1, 34056 | 8192, 5579) + b"\x00\x00"
        head = bytearray(data[:28])
        struct.pack_into("<H", head, 18, 28 + len(ext))
        full = bytes(head) + ext + data[28:]
        self.assertEqual(metadata(full), {34056: 5579})
        self.assertEqual(parse(full)[0][4].value, "A")
        changed = bytearray(full)
        changed[28 + len(ext) - 1] = 1
        with self.assertRaises(ThsProtocolError):
            metadata(bytes(changed))

    def test_minimal_column(self):
        rows = parse(sample())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4].value, "A")
        self.assertEqual(rows[0][4].format_byte, 15)

    def test_every_truncation(self):
        data = sample()
        for length in range(len(data)):
            with self.subTest(length=length), self.assertRaises(ThsProtocolError):
                parse(data[:length])

    def test_invalid_counts_width_type_and_lengths(self):
        for offset, fmt, value in [
            (6, "<i", -1),
            (6, "<i", 10001),
            (20, "<H", 4),
            (22, "<H", 257),
            (24, "<H", 0x4004),
            (28, "<I", 999),
            (32, ">I", 999),
        ]:
            data = bytearray(sample())
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ThsProtocolError):
                parse(bytes(data))
