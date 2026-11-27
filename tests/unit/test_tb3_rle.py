from pyths.errors import ThsProtocolError

"""Synthetic control-bit cases derived independently from ypu.a smali."""
import unittest

from pyths._tb3_rle import decode


class RleTests(unittest.TestCase):
    def test_literals(self):
        self.assertEqual(decode(b"\x00ABC", 3), b"ABC")
        self.assertEqual(decode(b"\x80AB", 3), b"ABB")

    def test_repeat_tree(self):
        for control, count in [
            (0xC0, 1),
            (0xE0, 2),
            (0xE8, 3),
            (0xF0, 4),
            (0xF8, 5),
            (0xF9, 6),
            (0xFA, 7),
            (0xFB, 8),
            (0xFC, 9),
            (0xFD, 10),
            (0xFE, 11),
        ]:
            with self.subTest(count=count):
                self.assertEqual(
                    decode(bytes([control, 65, 0]), count + 1), b"A" * (count + 1)
                )

    def test_extended_run(self):
        self.assertEqual(decode(bytes([255, 65, 0, 8]), 21), b"A" * 21)

    def test_bounds(self):
        for data, size in [(b"", 1), (b"\x00A", 3), (b"\xffA\x00\x7f", 5)]:
            with self.subTest(data=data), self.assertRaises(ThsProtocolError):
                decode(data, size)
        for size in [0, -1, True, 8388609]:
            with self.assertRaises(ThsProtocolError):
                decode(b"", size)
