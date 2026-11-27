"""M8 fs9/hs_datacenter_ztdt的固定只读统计路径。"""

import json
from datetime import UTC, datetime
from decimal import Decimal

from ._auth import encode_session_request
from ._compression import decode_snappy
from ._headers import decode_response_header, encode_request_header
from ._market_models import MarketBreadth, MarketLimitCounts, MarketMetric
from ._session import establish_session
from ._transform import checksum_context, decode_wire_body, transform_request
from ._transport import TcpTransport
from .errors import ThsNetworkError, ThsProtocolError

MAX_BODY = 4 * 1024 * 1024


def encode_breadth_body(*, instance_id: int) -> bytes:
    """固定6001/1002的UTF-16正文，见M8窗口5；无账号字段。"""
    if type(instance_id) is not int or not 1 <= instance_id <= 65535:
        raise ThsProtocolError("market breadth: invalid instance")
    return (
        f"[frame]\r\nid=6001\r\npageList={instance_id}\r\n"
        f"reqPage={instance_id}\r\nreqPageCount=1\r\n[{instance_id}]\r\n"
        "id=1002\r\nkey=hs_datacenter_ztdt\r\naction=subscribe\r\n"
        "stockcode=1A0001\r\nmarketcode=16\r\n\r\n"
    ).encode("utf-16-le")


def encode_breadth_request(
    *,
    package_id: int,
    instance_id: int,
    app_info: str,
    session_id: str,
    state_word: int = 0,
    trace_id: str | None = None,
) -> bytes:
    """组合已观察资源请求头与公共会话变换。"""
    if type(package_id) is not int or not 1 <= package_id <= 32767:
        raise ThsProtocolError("market breadth: invalid package")
    body = encode_breadth_body(instance_id=instance_id)
    header = encode_request_header(
        package_id=package_id,
        flags=0x40000,
        instance_marker=-253,
        data_length=0,
        frame_id=6001,
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


def parse_resource(data: bytes) -> tuple[MarketBreadth, MarketLimitCounts, str | None]:
    """读取公共统计；时间仅有时分时不制造日期，tp保留原字段名。"""
    if len(data) > MAX_BODY:
        raise ThsProtocolError("market breadth: resource limit")
    try:
        root = json.loads(data.decode("utf-8"))
        entries = root["hs_datacenter_ztdt"]
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError
        item = entries[0]
        if item["stockcode"] != "1A0001":
            raise ValueError
        value = item["value"]
        if isinstance(value, str):
            value = json.loads(value)
        total = value["all"]["total"]
        all_data = value["all"]["data"]

        def metric(label: str, number: object) -> MarketMetric:
            if type(number) is not int or not 0 <= number <= 10_000_000:
                raise ValueError
            return MarketMetric(label, str(number), Decimal(number), "家", "exact")

        rising = metric("上涨家数", total["up"])
        falling = metric("下跌家数", total["down"])
        unchanged = metric("平盘家数", total["deuce"]) if "deuce" in total else None
        other = (metric("tp", total["tp"]),) if "tp" in total else ()
        breadth = MarketBreadth(rising, falling, unchanged, other=other)
        times = value.get("time", [])
        ups, downs = value.get("zt", []), value.get("dt", [])
        if not all(isinstance(series, list) for series in (times, ups, downs)):
            raise ValueError
        if len(times) > 2000 or len(times) != len(ups) or len(times) != len(downs):
            raise ValueError
        # Match the App's last-point preference, including its zero fallback.
        up = (ups[-1] if times else None) or all_data["zt"]
        down = (downs[-1] if times else None) or all_data["dt"]
        label = times[-1] if times else None
        if label is not None and (not isinstance(label, str) or len(label) > 32):
            raise ValueError
        limits = MarketLimitCounts(metric("涨停家数", up), metric("跌停家数", down))
        return breadth, limits, label
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError):
        raise ThsProtocolError("market breadth: invalid public resource") from None


def decode_breadth_response(
    header_bytes: bytes,
    payload: bytes,
    *,
    package_id: int,
    instance_id: int,
) -> tuple[MarketBreadth, MarketLimitCounts, str | None]:
    """6001资源自身的关联与压缩规则，不套用1269或1282例外。"""
    header = decode_response_header(header_bytes)
    if (
        len(header_bytes) != header.length
        or header.length != 26
        or (header.package_id, header.instance_id, header.frame_id)
        != (package_id, instance_id, 6001)
        or header.flags != 0x100B
        or header.extension != b"\x03\xff"
        or header.payload_length != len(payload)
        or len(payload) > MAX_BODY
    ):
        raise ThsProtocolError("market breadth: response mismatch")
    decoded = decode_wire_body(payload, max_output=MAX_BODY)
    return parse_resource(decode_snappy(decoded, max_output=MAX_BODY))


def query_breadth(
    *,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int = 0,
) -> tuple[MarketBreadth, MarketLimitCounts, datetime, str | None]:
    """独立匿名连接取首次统计，结束即关闭，不维持后台订阅。"""
    if type(retries) is not int or retries not in (0, 1):
        raise ValueError("retries must be 0 or 1")
    for attempt in range(retries + 1):
        transport = TcpTransport(max_frame_size=MAX_BODY + 32)
        try:
            transport.connect(
                endpoint, deadline=deadline, connect_timeout=connect_timeout
            )
            packet = encode_session_request(
                config=app_config, app_info=app_info, passport=b""
            )
            session = establish_session(transport, packet, deadline=deadline)
            transport.send(
                encode_breadth_request(
                    package_id=1,
                    instance_id=1,
                    app_info=app_info,
                    session_id=session.session_id,
                ),
                deadline=deadline,
            )
            for _ in range(20):
                frame = transport.receive(deadline=deadline)
                received = datetime.now(UTC)
                header = decode_response_header(frame)
                if (
                    header.payload_length != len(frame) - header.length
                    or header.payload_length > MAX_BODY
                ):
                    raise ThsProtocolError("market breadth: payload length mismatch")
                if header.flags in (11, 65547):
                    continue
                breadth, limits, label = decode_breadth_response(
                    frame[: header.length],
                    frame[header.length :],
                    package_id=1,
                    instance_id=1,
                )
                return breadth, limits, received, label
            raise ThsProtocolError("market breadth: response count limit")
        except ThsNetworkError:
            if attempt == retries:
                raise
        finally:
            transport.close()
    raise ThsNetworkError("market breadth: retry budget exhausted")
