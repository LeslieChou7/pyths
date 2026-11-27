"""目标hxsecurity样本的离线正文映射和校验算法。"""

import base64
import binascii
import struct

from .errors import ThsProtocolError

_STANDARD = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_ALPHABET = bytes.fromhex(
    "6143634d65544b68786e777a6d6f506273473445765538677964303242337136664956"
    "5758595a6a41705272447475486b694c6c4e314f39463553374a512b2f"
)


def checksum_context(*, app_info: str, session: str) -> tuple[bytes, bytes]:
    """构造已确认校验前后缀；应用配置和会话由调用方显式注入。"""
    try:
        if not app_info:
            raise ThsProtocolError("transform: missing application context")
        return app_info.encode("utf-8") + b"TONG", (session or "0").encode("utf-8")
    except UnicodeEncodeError:
        raise ThsProtocolError("transform: invalid context encoding") from None


def encode_body(data: bytes, *, max_input: int = 1024 * 1024) -> bytes:
    """自定义字母表编码；不生成校验输入或会话材料。"""
    if len(data) > max_input:
        raise ThsProtocolError("transform: input limit")
    return base64.b64encode(data).translate(bytes.maketrans(_STANDARD, _ALPHABET))


def decode_body(data: bytes, *, max_output: int = 8 * 1024 * 1024) -> bytes:
    """严格读取对应字母表，拒绝非规范填充。"""
    if len(data) > ((max_output + 2) // 3) * 4:
        raise ThsProtocolError("transform: output limit")
    try:
        result = base64.b64decode(
            data.translate(bytes.maketrans(_ALPHABET, _STANDARD)), validate=True
        )
    except binascii.Error:
        raise ThsProtocolError("transform: invalid encoding") from None
    if len(result) > max_output or encode_body(result, max_input=max_output) != data:
        raise ThsProtocolError("transform: noncanonical encoding")
    return result


def checksum(data: bytes) -> int:
    """高位CRC-32，追加低字节优先长度后取反；返回无符号32位。"""
    state = 0

    def update(value: int, byte: int) -> int:
        value ^= byte << 24
        for _ in range(8):
            value = (
                (value << 1) ^ (0x04C11DB7 if value & 0x80000000 else 0)
            ) & 0xFFFFFFFF
        return value

    for byte in data:
        state = update(state, byte)
    size = len(data)
    while size:
        state = update(state, size & 255)
        size >>= 8
    return state ^ 0xFFFFFFFF


def decode_wire_body(data: bytes, *, max_output: int = 8 * 1024 * 1024) -> bytes:
    """按native在首个NUL/填充停止；允许省略填充，保持离线严格逆算独立。"""
    if len(data) > ((max_output + 2) // 3) * 4 + 4:
        raise ThsProtocolError("wire transform: input limit")
    stop = min(
        (
            position
            for position in (data.find(b"\x00"), data.find(b"="))
            if position >= 0
        ),
        default=len(data),
    )
    content = data[:stop].replace(b" ", b"+")
    if len(content) % 4 == 1:
        if stop < len(data) and data[stop] == ord("="):
            raise ThsProtocolError("wire transform: invalid padding")
        # native在EOF/NUL时不计入仅含一个索引的末组。
        content = content[:-1]
    if any(char not in _ALPHABET for char in content):
        raise ThsProtocolError("wire transform: invalid encoding")
    standard = content.translate(bytes.maketrans(_ALPHABET, _STANDARD))
    try:
        result = base64.b64decode(standard + b"=" * (-len(standard) % 4), validate=True)
    except binascii.Error:
        raise ThsProtocolError("wire transform: invalid encoding") from None
    if len(result) > max_output:
        raise ThsProtocolError("wire transform: output limit")
    return result


def transform_request(
    packet: bytes, *, checksum_prefix: bytes, session_suffix: bytes
) -> bytes:
    """显式注入完整校验前后缀；仅实现已确认的新头正文映射分支。"""
    if len(packet) < 34:
        raise ThsProtocolError("transform: truncated request header")
    header_length = int.from_bytes(packet[:2], "little")
    flags = int.from_bytes(packet[6:10], "little")
    if not 34 <= header_length <= len(packet) or flags not in (
        0x01010000,
        0x00070000,
        0x01060000,
        0x00040000,
    ):
        raise ThsProtocolError("transform: unsupported request header")
    body = packet[header_length:]
    encoded = encode_body(body)
    header = bytearray(packet[:header_length])
    struct.pack_into("<I", header, 12, len(encoded))
    struct.pack_into(
        "<I", header, 28, checksum(checksum_prefix + body + session_suffix)
    )
    return bytes(header) + encoded
