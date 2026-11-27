"""最小启动响应协调；不读取App登录态或持久化会话。"""

import json
from dataclasses import dataclass, field

from ._auth import decode_session_reply
from ._headers import decode_response_header
from ._transform import decode_wire_body
from ._transport import TcpTransport
from .errors import ThsAuthenticationError, ThsProtocolError


@dataclass(frozen=True, repr=False)
class SessionContext:
    """仅内存保存服务端会话值，默认对象表示不暴露内容。"""

    session_id: str = field(repr=False)


def establish_session(
    transport: TcpTransport, packet: bytes, *, deadline: float
) -> SessionContext:
    """要求明确成功帧与独立sessionId同时到达，最多处理20帧。"""
    authenticated = False
    session_id = None
    try:
        transport.send(packet, deadline=deadline)
        for _ in range(20):
            frame = transport.receive(deadline=deadline)
            header = decode_response_header(frame)
            body = frame[header.length :]
            if len(body) != header.payload_length:
                raise ThsProtocolError("session: payload length mismatch")
            if header.length != 26 or header.flags not in (6, 11, 65547):
                raise ThsProtocolError("session: unsupported response")
            marker = int.from_bytes(header.extension, "little", signed=True)
            if marker == -253:
                body = decode_wire_body(body)
            if header.flags == 6:
                reply = decode_session_reply(body)
                if header.frame_id != 2201 or reply.status & 0x22:
                    raise ThsAuthenticationError("session: initialization rejected")
                authenticated = True
            else:
                try:
                    metadata = json.loads(body.decode("gbk"))
                except (ValueError, UnicodeError):
                    raise ThsProtocolError("session: invalid metadata") from None
                if not isinstance(metadata, dict):
                    raise ThsProtocolError("session: invalid metadata structure")
                if "sessionId" in metadata:
                    value = metadata["sessionId"]
                    if not isinstance(value, str) or not value:
                        raise ThsProtocolError("session: invalid session identifier")
                    if session_id is not None and session_id != value:
                        raise ThsProtocolError(
                            "session: inconsistent session identifier"
                        )
                    session_id = value
            if authenticated and session_id is not None:
                return SessionContext(session_id)
        raise ThsProtocolError("session: response count limit")
    except BaseException:
        transport.close()
        raise
