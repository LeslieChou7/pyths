"""已确认1269响应路径的离线跨层校验。"""

from ._codec import StringTable, decode_tb1_strings
from ._compression import decode_snappy
from ._headers import decode_response_header
from .errors import ThsProtocolError


def decode_1269_response(
    header_bytes: bytes,
    payload: bytes,
    *,
    package_id: int,
    frame_id: int,
    instance_id: int,
    max_output: int = 8 * 1024 * 1024,
    allow_initial_frame_zero: bool = False,
) -> StringTable:
    """校验单个已关联响应并解压读表；调用者提供独立关联预期。"""
    header = decode_response_header(header_bytes)
    if len(header_bytes) != header.length:
        raise ThsProtocolError("response: header boundary mismatch")
    initial_zero = (
        allow_initial_frame_zero
        and header.length == 26
        and package_id > 0
        and frame_id == 2267
        and header.frame_id == 0
    )
    if (header.package_id, header.instance_id) != (package_id, instance_id) or (
        header.frame_id != frame_id and not initial_zero
    ):
        raise ThsProtocolError("response: correlation mismatch")
    if header.payload_length != len(payload):
        raise ThsProtocolError("response: payload length mismatch")
    if header.flags not in (0x100, 0x1100):
        raise ThsProtocolError("response: unsupported flags")
    if header.flags == 0x100:
        if len(payload) > max_output:
            raise ThsProtocolError("response: output limit")
        return decode_tb1_strings(payload)
    return decode_tb1_strings(decode_snappy(payload, max_output=max_output))
