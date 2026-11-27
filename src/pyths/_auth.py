"""已观察启动正文布局；不生成凭据或风控材料。"""

import struct
import time
import uuid
from dataclasses import dataclass, field

from ._headers import encode_request_header
from ._transform import checksum_context, transform_request
from .errors import ThsProtocolError


@dataclass(frozen=True, repr=False)
class SessionReply:
    """启动响应已确认前段；后续数据和成功语义仍须独立处理。"""

    status: int
    random_value: int
    passport: bytes = field(repr=False)
    user_info: str | None = field(repr=False)
    message: str | None = field(repr=False)
    tail: bytes = field(repr=False)
    raw_payload: bytes = field(repr=False)


def decode_session_reply(payload: bytes) -> SessionReply:
    """按i6v.a/s/o/n读取前段；不据状态字节推定会话成功。"""
    if len(payload) < 9:
        raise ThsProtocolError("auth response: truncated")
    position = 3

    def sized(*, units: int = 1) -> bytes:
        nonlocal position
        if position + 2 > len(payload):
            raise ThsProtocolError("auth response: truncated length")
        size = int.from_bytes(payload[position : position + 2], "little", signed=True)
        position += 2
        if size < 0 or size * units > len(payload) - position:
            raise ThsProtocolError("auth response: invalid field length")
        data = payload[position : position + size * units]
        position += size * units
        return data

    status = payload[0]
    random_value = int.from_bytes(payload[1:3], "little", signed=True)
    passport = sized()
    try:
        user_info = sized().decode("gbk", errors="replace") if status & 0x80 else None
        message = sized(units=2).decode("utf-16-le", errors="surrogatepass")
    except UnicodeError:
        raise ThsProtocolError("auth response: invalid text encoding") from None
    return SessionReply(
        status,
        random_value,
        passport,
        user_info,
        message or None,
        payload[position:],
        payload,
    )


def make_session_trace() -> str:
    """按目标启动路径生成trace；时间为Unix毫秒，随机部分不含设备信息。"""
    milliseconds = time.time_ns() // 1_000_000
    if not 0 <= milliseconds <= 9_999_999_999_999:
        raise ThsProtocolError("auth: unsupported trace timestamp")
    return f"3{24578:07d}{milliseconds:013d}{uuid.uuid4().hex[:11]}"


def encode_session_body(
    *, config: str, passport: bytes, risk_parameters: str | None = None
) -> bytes:
    """编码j6v.g正文，所有材料显式传入；不包含应用头和发送变换。"""
    try:
        config_bytes = config.encode("utf-16-le")
        risk_bytes = risk_parameters.encode("gbk") if risk_parameters else b""
    except UnicodeError:
        raise ThsProtocolError("auth: unsupported text encoding") from None
    units = len(config_bytes) // 2
    # 长度采用short；在未核实服务端无符号语义前限制为正有符号范围。
    if any(size > 32767 for size in (units, len(passport), len(risk_bytes))):
        raise ThsProtocolError("auth: field length exceeds supported bounds")
    result = struct.pack("<H", units) + config_bytes
    result += struct.pack("<H", len(passport)) + passport
    if risk_bytes:
        result += struct.pack("<H", len(risk_bytes)) + risk_bytes
    return result


def encode_session_request(
    *,
    config: str,
    app_info: str,
    passport: bytes,
    risk_parameters: str | None = None,
) -> bytes:
    """组合目标新头启动请求；返回应用报文，外层封装交传输层。"""
    body = encode_session_body(
        config=config, passport=passport, risk_parameters=risk_parameters
    )
    header = encode_request_header(
        package_id=0,
        flags=0x00070000,
        instance_marker=-253,
        data_length=len(body),
        frame_id=0,
        text_length=0,
        state_word=0,
        extension_word=0,
        extension_short=0,
        trace_id=make_session_trace(),
    )
    prefix, suffix = checksum_context(app_info=app_info, session="")
    return transform_request(
        header + body, checksum_prefix=prefix, session_suffix=suffix
    )
