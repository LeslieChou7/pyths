"""Offline wpu numeric structure; display rounding remains unverified."""

from decimal import Decimal

from .errors import ThsProtocolError


def decode_number(word: int) -> Decimal | None:
    """Decode the observed unsigned 32-bit word without inferring units."""
    if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
        raise ThsProtocolError("invalid numeric word")
    if word in (0x80000000, 0xFFFFFFFF):
        return None
    mantissa = word & 0x07FFFFFF
    exponent = (word >> 28) & 7
    if word & 0x08000000:
        mantissa = -mantissa
    return Decimal(mantissa).scaleb(-exponent if word & 0x80000000 else exponent)
