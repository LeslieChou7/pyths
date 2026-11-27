"""1264大小盘快照；仅实现M8窗口4及目标离线页面确认的固定分支。"""

import math
import struct
import time
from datetime import UTC, datetime
from decimal import Decimal

from ._auth import encode_session_request
from ._codec import format_table_string
from ._compression import decode_snappy
from ._headers import decode_response_header, encode_request_header
from ._market_models import MarketMetric, MarketSizeComparison, MarketSizeSide
from ._session import establish_session
from ._tb3 import Cell, metadata, parse
from ._transform import checksum_context, transform_request
from ._transport import TcpTransport
from .errors import ThsNetworkError, ThsProtocolError

MAX_BODY = 4 * 1024 * 1024
_CODES = ("1B0300", "1B0852")


def encode_size_body(
    *, instance_id: int, active_instances: tuple[int, ...] | None = None
) -> bytes:
    """编码静态与窗口4相符的固定两证券请求，不接受任意参数。"""
    instances = (instance_id,) if active_instances is None else active_instances
    if (
        not instances
        or len(instances) > 32
        or instance_id not in instances
        or len(set(instances)) != len(instances)
        or any(type(value) is not int or not 1 <= value <= 65535 for value in instances)
        or type(instance_id) is not int
    ):
        raise ThsProtocolError("market size: invalid instances")
    pages = ",".join(str(value) for value in instances)
    return (
        f"[frame]\r\nid=2312\r\npageList={pages}\r\n"
        f"reqPage={instance_id}\r\nreqPageCount=1\r\n[{instance_id}]\r\n"
        "id=1264\r\nstartrow=0\r\nsortid=-1\r\nrowcount=2\r\n"
        "newrealtime=0\r\nselfstockcustom=1\r\nupdate=1\r\n"
        "columnorder=55|4|34338|34818\r\nmarketlist=16|16\r\n"
        "stocklist=1B0300|1B0852\r\n"
    ).encode("ascii")


def encode_size_request(
    *,
    package_id: int,
    instance_id: int,
    app_info: str,
    session_id: str,
    state_word: int = 0,
    trace_id: str | None = None,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """组合公共请求头与变换；无遥测状态的0分支不复制捕获材料。"""
    if type(package_id) is not int or not 1 <= package_id <= 32767:
        raise ThsProtocolError("market size: invalid package identifier")
    body = encode_size_body(instance_id=instance_id, active_instances=active_instances)
    header = encode_request_header(
        package_id=package_id,
        flags=0x01010000,
        instance_marker=-253,
        data_length=0,
        frame_id=2312,
        text_length=len(body),
        state_word=state_word,
        extension_word=0,
        extension_short=0,
        trace_id=trace_id,
    )
    prefix, suffix = checksum_context(app_info=app_info, session=session_id)
    return transform_request(
        header + body, checksum_prefix=prefix, session_suffix=suffix
    )


def _side(row: dict[int, Cell], code: str) -> MarketSizeSide:
    if not {4, 55, 34338, 34818}.issubset(row):
        raise ThsProtocolError("market size: missing required field")
    name, identity, market, change = (row[key] for key in (55, 4, 34338, 34818))
    if (
        not isinstance(name.value, str)
        or not name.value
        or identity.value != code
        or type(market.value) is not int
        or market.value != 16
    ):
        raise ThsProtocolError("market size: identity mismatch")
    if change.format_byte & 0xF0 != 0x20:
        raise ThsProtocolError("market size: unsupported change format")
    value = change.value
    if value is None:
        return MarketSizeSide(name.value)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ThsProtocolError("market size: invalid change value")
    raw = format_table_string(format(value, "f"), change.format_byte)
    return MarketSizeSide(
        name.value,
        MarketMetric("涨跌幅", raw, value, "%", "rounded"),
    )


def decode_size_response(
    header_bytes: bytes,
    payload: bytes,
    *,
    package_id: int,
    instance_id: int,
) -> MarketSizeComparison:
    """严格关联App正常头及M8独立会话首帧；两行身份必须完整匹配。"""
    header = decode_response_header(header_bytes)
    initial = (
        header.length == 26
        and header.frame_id == 0
        and header.extension == b"\x00\xff"
        and package_id > 0
    )
    normal = (
        header.length == 32
        and header.frame_id == 2312
        and header.extension[:4] == b"\x00" * 4
    )
    if len(header_bytes) != header.length or not (initial or normal):
        raise ThsProtocolError("market size: unsupported header layout")
    if header.package_id != package_id or header.instance_id != instance_id:
        raise ThsProtocolError("market size: correlation mismatch")
    if (
        header.flags != 0x1100
        or header.payload_length != len(payload)
        or len(payload) > MAX_BODY
    ):
        raise ThsProtocolError("market size: invalid flags or payload length")
    body = decode_snappy(payload, max_output=MAX_BODY)
    if len(body) < 24 or struct.unpack_from("<i", body, 6)[0] != 2:
        raise ThsProtocolError("market size: expected two rows")
    fields = metadata(body)
    if fields.get(34055) != 0 or fields.get(34056) != 2:
        raise ThsProtocolError("market size: invalid table bounds")
    rows = parse(body)
    return MarketSizeComparison(_side(rows[0], _CODES[0]), _side(rows[1], _CODES[1]))


def query_size(
    *,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int = 0,
) -> tuple[MarketSizeComparison, datetime]:
    """单次独立匿名连接；所有安全网络重试共用截止时间并释放资源。"""
    if type(retries) is not int or retries not in (0, 1):
        raise ValueError("retries must be 0 or 1")
    if (
        not math.isfinite(connect_timeout)
        or connect_timeout <= 0
        or not math.isfinite(deadline)
    ):
        raise ValueError("invalid market size deadline or timeout")
    if not app_config or not app_info:
        raise ValueError("explicit app_config and app_info required")
    for attempt in range(retries + 1):
        if time.monotonic() >= deadline:
            raise ThsNetworkError("market size: deadline exceeded")
        transport = TcpTransport()
        try:
            transport.connect(
                endpoint, deadline=deadline, connect_timeout=connect_timeout
            )
            init = encode_session_request(
                config=app_config, app_info=app_info, passport=b""
            )
            session = establish_session(transport, init, deadline=deadline)
            packet = encode_size_request(
                package_id=1,
                instance_id=1,
                app_info=app_info,
                session_id=session.session_id,
            )
            transport.send(packet, deadline=deadline)
            for _ in range(20):
                frame = transport.receive(deadline=deadline)
                received_at = datetime.now(UTC)
                header = decode_response_header(frame)
                if (
                    header.payload_length != len(frame) - header.length
                    or header.payload_length > MAX_BODY
                ):
                    raise ThsProtocolError("market size: payload length mismatch")
                if header.flags in (11, 65547):
                    continue
                result = decode_size_response(
                    frame[: header.length],
                    frame[header.length :],
                    package_id=1,
                    instance_id=1,
                )
                return result, received_at
            raise ThsProtocolError("market size: response count limit")
        except ThsNetworkError:
            if attempt == retries:
                raise
        finally:
            transport.close()
    raise ThsNetworkError("market size: retry budget exhausted")
