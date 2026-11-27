import unittest
from decimal import Decimal

from pyths._tb3_number import decode_number
from pyths.errors import ThsProtocolError


class NumberTests(unittest.TestCase):
    def test_sign_scale_and_missing(self):
        for raw, expected in [
            (0, Decimal(0)),
            (0xA000013C, Decimal("3.16")),
            (0xA00007DF, Decimal("20.15")),
            (0xA800013C, Decimal("-3.16")),
            (0x2000013C, Decimal(31600)),
            (0x80000000, None),
            (0xFFFFFFFF, None),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(decode_number(raw), expected)

    def test_invalid_word(self):
        for value in [True, -1, 0x100000000, "316"]:
            with self.assertRaises(ThsProtocolError):
                decode_number(value)
