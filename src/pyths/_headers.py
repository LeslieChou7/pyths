"""响应应用头离线读取；不实现鉴权或负载变换。"""

import struct
from dataclasses import dataclass

from .errors import ThsProtocolError


@dataclass(frozen=True)
class ResponseHeader:
    length: int
    package_id: int
    flags: int
    instance_id: int
    payload_length: int
    frame_id: int
    raw_final: int
    extension: bytes


def decode_response_header(data: bytes) -> ResponseHeader:
    """解析静态证据支持的24/26/32字节响应头。"""
    if len(data) < 24:
        raise ThsProtocolError("header: truncated")
    values = struct.unpack_from("<HiiHiii", data)
    length = values[0]
    if length not in (24, 26, 32) or length > len(data):
        raise ThsProtocolError("header: unsupported length")
    return ResponseHeader(
        length,
        values[1],
        values[2],
        values[3],
        values[4],
        values[5],
        values[6],
        data[24:length],
    )


def encode_request_header(
    *,
    package_id: int,
    flags: int,
    instance_marker: int,
    data_length: int,
    frame_id: int,
    text_length: int,
    state_word: int,
    extension_word: int,
    extension_short: int,
    trace_id: str | None,
) -> bytes:
    """编码已确认的新请求头ASCII扩展子集；状态和扩展值必须显式提供。"""
    numbers = (
        package_id,
        flags,
        instance_marker,
        data_length,
        frame_id,
        text_length,
        state_word,
        extension_word,
        extension_short,
    )
    if any(type(value) is not int for value in numbers):
        raise ThsProtocolError("request header: invalid numeric field")
    if not -32768 <= instance_marker <= 65535 or data_length < 0 or text_length < 0:
        raise ThsProtocolError("request header: invalid numeric field")
    extension = b""
    if trace_id is not None:
        if not trace_id or any(char in trace_id for char in "&=\r\n\x00"):
            raise ThsProtocolError("request header: invalid trace identifier")
        try:
            content = ("traceid=" + trace_id).encode("ascii")
        except UnicodeEncodeError:
            raise ThsProtocolError(
                "request header: unsupported extension encoding"
            ) from None
        if len(content) > 65535 - 36:
            raise ThsProtocolError("request header: extension limit")
        extension = struct.pack("<H", len(content)) + content
    length = 34 + len(extension)
    try:
        return (
            struct.pack(
                "<HiiHiiiiIH",
                length,
                package_id,
                flags,
                instance_marker & 0xFFFF,
                data_length,
                frame_id,
                text_length,
                state_word,
                extension_word,
                extension_short,
            )
            + extension
        )
    except (struct.error, TypeError):
        raise ThsProtocolError("request header: invalid numeric field") from None
