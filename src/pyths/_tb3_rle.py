"""Observed ypu.a internal RLE decoder; pure offline operation."""

from .errors import ThsProtocolError


def decode(data: bytes, size: int, *, limit: int = 8 * 1024 * 1024) -> bytes:
    if type(size) is not int or not 1 <= size <= limit:
        raise ThsProtocolError("invalid output size")
    pos = 0

    def byte() -> int:
        nonlocal pos
        if pos >= len(data):
            raise ThsProtocolError("truncated input")
        value = data[pos]
        pos += 1
        return value

    control = byte()
    left = 8

    def bit() -> int:
        nonlocal control, left
        value = control >> 7
        control = (control << 1) & 255
        left -= 1
        if left == 0:
            control = byte()
            left = 8
        return value

    last = byte()
    out = bytearray([last])
    while len(out) < size:
        if bit() == 0:
            out.append(byte())
            last = byte()
            out.append(last)
            continue
        if bit() == 0:
            last = byte()
            out.append(last)
        count = 1
        if bit():
            count = 2
            if bit():
                count = 4
                if bit():
                    count = 5
                    if bit():
                        count = 9
                        if bit():
                            if bit():
                                count = 12
                                while True:
                                    length = byte()
                                    if length > 127:
                                        length = ((length - 128) << 8) + byte()
                                    count += length
                                    if count > size + 1 - len(out):
                                        raise ThsProtocolError("run exceeds output")
                                    if length != 32767:
                                        break
                            else:
                                count = 11
                        else:
                            count += bit()
                    elif bit():
                        count += 2 + bit()
                    else:
                        count += bit()
            else:
                count += bit()
        if count > size + 1 - len(out):
            raise ThsProtocolError("run exceeds output")
        out.extend(bytes([last]) * count)
    if len(out) not in (size, size + 1):
        raise ThsProtocolError("output mismatch")
    return bytes(out[:size])
