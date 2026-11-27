"""单实例1269请求组合；仅覆盖目标已观察的新头文本路径。"""

from ._codec import encode_1269_body
from ._headers import encode_request_header
from ._transform import checksum_context, transform_request
from .errors import ThsProtocolError


def encode_quote_request(
    *,
    stock_code: str,
    market: str,
    package_id: int,
    frame_id: int,
    instance_id: int,
    app_info: str,
    session_id: str,
) -> bytes:
    """生成应用报文；关联编号由会话层分配，不复用捕获值。"""
    body = encode_1269_body(
        stock_code=stock_code,
        market=market,
        frame_id=frame_id,
        instance_id=instance_id,
    )
    header = encode_request_header(
        package_id=package_id,
        flags=0x01010000,
        instance_marker=-253,
        data_length=0,
        frame_id=frame_id,
        text_length=len(body),
        state_word=0,
        extension_word=0,
        extension_short=0,
        trace_id=None,
    )
    prefix, suffix = checksum_context(app_info=app_info, session=session_id)
    return transform_request(
        header + body, checksum_prefix=prefix, session_suffix=suffix
    )


def encode_stop_request(
    *, package_id: int, frame_id: int, app_info: str, session_id: str
) -> bytes:
    """按qlu.b停止当前frame的页列表；使用独立包号和现有会话校验。"""
    if type(frame_id) is not int or not 0 <= frame_id <= 2147483647:
        raise ThsProtocolError("stop request: invalid frame identifier")
    body = f"[frame]\r\nid={frame_id}\r\npageList=\r\n".encode("ascii")
    header = encode_request_header(
        package_id=package_id,
        flags=0x01060000,
        instance_marker=-253,
        data_length=0,
        frame_id=frame_id,
        text_length=len(body),
        state_word=0,
        extension_word=0,
        extension_short=0,
        trace_id=None,
    )
    prefix, suffix = checksum_context(app_info=app_info, session=session_id)
    return transform_request(
        header + body, checksum_prefix=prefix, session_suffix=suffix
    )
