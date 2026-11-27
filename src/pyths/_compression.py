"""Snappy原始块离线解码；不是Snappy framed stream。"""

from .errors import ThsProtocolError


def decode_snappy(data: bytes, *, max_output: int = 8 * 1024 * 1024) -> bytes:
    """解码有界原始块，拒绝截断、非法回引及声明长度不符。"""
    if type(max_output) is not int or max_output <= 0:
        raise ValueError("max_output must be positive")
    position = 0

    def take(size: int) -> bytes:
        nonlocal position
        if size < 0 or position + size > len(data):
            raise ThsProtocolError("compression: truncated block")
        value = data[position : position + size]
        position += size
        return value

    expected = 0
    for shift in range(0, 35, 7):
        byte = take(1)[0]
        expected |= (byte & 127) << shift
        if not byte & 128:
            break
    else:
        raise ThsProtocolError("compression: invalid length")
    if expected > min(max_output, 0xFFFFFFFF):
        raise ThsProtocolError("compression: output limit")
    output = bytearray()
    while position < len(data):
        tag = take(1)[0]
        kind = tag & 3
        if kind == 0:
            length = tag >> 2
            if length >= 60:
                length = int.from_bytes(take(length - 59), "little")
            length += 1
            if len(output) + length > expected:
                raise ThsProtocolError("compression: length mismatch")
            output.extend(take(length))
        else:
            if kind == 1:
                length = 4 + ((tag >> 2) & 7)
                offset = ((tag & 224) << 3) | take(1)[0]
            else:
                length = 1 + (tag >> 2)
                offset = int.from_bytes(take(2 if kind == 2 else 4), "little")
            if not 0 < offset <= len(output) or len(output) + length > expected:
                raise ThsProtocolError("compression: invalid copy")
            for _ in range(length):
                output.append(output[-offset])
    if len(output) != expected:
        raise ThsProtocolError("compression: length mismatch")
    return bytes(output)
