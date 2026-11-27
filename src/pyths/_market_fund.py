"""窗口5的1229/DDE双来源资金快照；不推断其分类算法或币种。"""

import math
import struct
import time
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from ._auth import encode_session_request
from ._compression import decode_snappy
from ._curve import MAX_CURVE_BYTES, parse_curve
from ._headers import decode_response_header, encode_request_header
from ._market_models import MarketFundFlow, MarketFundFlowPart, MarketMetric
from ._session import establish_session
from ._transform import checksum_context, transform_request
from ._transport import TcpTransport
from .errors import ThsNetworkError, ThsProtocolError

type FundSource = Literal["sh", "sz"]
_SOURCES = {"sh": ("1A0001", "16"), "sz": ("399001", "32")}


def _identity(kind: FundSource) -> tuple[str, str]:
    if kind not in _SOURCES:
        raise ValueError("unsupported market fund source")
    return _SOURCES[kind]


def encode_fund_body(
    *,
    kind: FundSource,
    instance_id: int,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """编码固定1229请求，保留实际观察到的业务参数前空行。"""
    code, market = _identity(kind)
    instances = (instance_id,) if active_instances is None else active_instances
    if (
        not instances
        or len(instances) > 32
        or instance_id not in instances
        or len(set(instances)) != len(instances)
        or any(type(value) is not int or not 1 <= value <= 65535 for value in instances)
        or type(instance_id) is not int
    ):
        raise ThsProtocolError("market fund: invalid instances")
    pages = ",".join(str(value) for value in instances)
    return (
        f"[frame]\r\nid=9001\r\npageList={pages}\r\n"
        f"reqPage={instance_id}\r\nreqPageCount=1\r\n[{instance_id}]\r\n"
        f"id=1229\r\n\r\nstockcode={code}\r\nmarketcode={market}\r\ntech=DDE\r\n"
    ).encode("ascii")


def encode_fund_request(
    *,
    kind: FundSource,
    package_id: int,
    instance_id: int,
    app_info: str,
    session_id: str,
    state_word: int = 0,
    trace_id: str | None = None,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """组合公共线上头和会话变换；不复制捕获状态或trace。"""
    if type(package_id) is not int or not 1 <= package_id <= 32767:
        raise ThsProtocolError("market fund: invalid package identifier")
    body = encode_fund_body(
        kind=kind, instance_id=instance_id, active_instances=active_instances
    )
    header = encode_request_header(
        package_id=package_id,
        flags=0x01010000,
        instance_marker=-253,
        data_length=0,
        frame_id=9001,
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


def decode_fund_response(
    header_bytes: bytes,
    payload: bytes,
    *,
    kind: FundSource,
    package_id: int,
    instance_id: int,
) -> MarketFundFlowPart:
    """只接收已关联的完整初始DDE曲线；缺失末点或增量段明确失败。"""
    code, market = _identity(kind)
    header = decode_response_header(header_bytes)
    initial = (
        header.length == 26
        and header.frame_id == 0
        and header.extension == b"\x00\xff"
        and header.flags in (0x120, 0x1120)
        and package_id > 0
    )
    normal = (
        header.length == 32
        and header.frame_id == 9001
        and header.extension[:4] == b"\x00" * 4
        and header.flags == 0x120
    )
    if len(header_bytes) != header.length or not (initial or normal):
        raise ThsProtocolError("market fund: unsupported header layout")
    if header.package_id != package_id or header.instance_id != instance_id:
        raise ThsProtocolError("market fund: correlation mismatch")
    if header.payload_length != len(payload) or len(payload) > MAX_CURVE_BYTES:
        raise ThsProtocolError("market fund: unsupported payload")
    body = (
        decode_snappy(payload, max_output=MAX_CURVE_BYTES)
        if initial and header.flags == 0x1120
        else payload
    )
    if body[:6] != b"cv3.0\x00":
        raise ThsProtocolError("market fund: unsupported curve layout")
    curve = parse_curve(body)
    if curve.first_index != 0:
        raise ThsProtocolError("market fund: incremental curve not supported")
    if (
        curve.extensions.get(4) != code
        or curve.extensions.get(36103) != market
        or curve.extensions.get(33282) != "DDE"
    ):
        raise ThsProtocolError("market fund: source identity mismatch")
    name = curve.extensions.get(55)
    net, times = curve.fields.get(33016), curve.fields.get(1)
    if not isinstance(name, str) or not name or not net or not times:
        raise ThsProtocolError("market fund: missing required field")
    value, stamp = net[-1], times[-1]
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or type(stamp) is not int
    ):
        raise ThsProtocolError("market fund: missing net point or time label")
    return MarketFundFlowPart(
        code,
        market,
        MarketMetric(name + " DDE净流入", format(value, "f"), value),
        source_time_label=str(stamp),
    )


def _float32(value: float) -> float:
    try:
        rounded = float(struct.unpack("<f", struct.pack("<f", value))[0])
    except (struct.error, OverflowError):
        raise ThsProtocolError("market fund: amount outside float32 bounds") from None
    if not math.isfinite(rounded):
        raise ThsProtocolError("market fund: invalid float32 amount")
    return rounded


def combine_fund(sh: MarketFundFlowPart, sz: MarketFundFlowPart) -> MarketFundFlow:
    """复现App两侧缩放、float32求和及Java两位小数显示；非精确金额合计。"""
    if (sh.stock_code, sh.market) != _SOURCES["sh"] or (
        sz.stock_code,
        sz.market,
    ) != _SOURCES["sz"]:
        raise ThsProtocolError("market fund: invalid sum sources")
    values = (sh.net.value, sz.net.value)
    if any(value is None for value in values):
        raise ThsProtocolError("market fund: missing sum source")
    scaled: list[float] = []
    for value in values:
        if value is None:
            raise ThsProtocolError("market fund: missing sum source")
        scaled.append(_float32(float(value) / 100000000.0))
    total = _float32(scaled[0] + scaled[1])
    # Java Formatter uses HALF_UP for %.2f (including exact binary ties), not
    # Python's half-even formatting. The float32 result is widened exactly.
    with localcontext() as context:
        context.prec = 50
        display_value = Decimal.from_float(total).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return MarketFundFlow(
        net=MarketMetric(
            "大盘资金净流入",
            ("+" if total > _float32(0.01) else "")
            + format(display_value, ".2f")
            + "亿",
            display_value,
            "亿",
            "rounded",
            derivation="app_sum_float32_dde",
        ),
        classification="大盘资金净流入；分类算法未知",
        sources=(sh, sz),
    )


def query_one(
    *,
    kind: FundSource,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int = 0,
) -> tuple[MarketFundFlowPart, datetime]:
    """单来源独立匿名连接；完成或失败均释放，不合并增量或复用缓存。"""
    _identity(kind)
    if type(retries) is not int or retries not in (0, 1):
        raise ValueError("retries must be 0 or 1")
    if (
        not math.isfinite(connect_timeout)
        or connect_timeout <= 0
        or not math.isfinite(deadline)
        or not app_config
        or not app_info
    ):
        raise ValueError("explicit app configuration and valid timeouts required")
    for attempt in range(retries + 1):
        if time.monotonic() >= deadline:
            raise ThsNetworkError("market fund: deadline exceeded")
        transport = TcpTransport()
        try:
            transport.connect(
                endpoint, deadline=deadline, connect_timeout=connect_timeout
            )
            init = encode_session_request(
                config=app_config, app_info=app_info, passport=b""
            )
            session = establish_session(transport, init, deadline=deadline)
            packet = encode_fund_request(
                kind=kind,
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
                    or header.payload_length > MAX_CURVE_BYTES
                ):
                    raise ThsProtocolError("market fund: invalid response length")
                if header.flags in (11, 65547):
                    continue
                return (
                    decode_fund_response(
                        frame[: header.length],
                        frame[header.length :],
                        kind=kind,
                        package_id=1,
                        instance_id=1,
                    ),
                    received_at,
                )
            raise ThsProtocolError("market fund: response count limit")
        except ThsNetworkError:
            if attempt == retries:
                raise
        finally:
            transport.close()
    raise ThsNetworkError("market fund: retry budget exhausted")


def query_fund(
    *,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int = 0,
) -> tuple[MarketFundFlow, datetime]:
    """顺序获取两侧并按App显示方式合计，共用调用方总截止时间。"""
    sh, _ = query_one(
        kind="sh",
        endpoint=endpoint,
        app_config=app_config,
        app_info=app_info,
        connect_timeout=connect_timeout,
        deadline=deadline,
        retries=retries,
    )
    sz, received_at = query_one(
        kind="sz",
        endpoint=endpoint,
        app_config=app_config,
        app_info=app_info,
        connect_timeout=connect_timeout,
        deadline=deadline,
        retries=retries,
    )
    return combine_fund(sh, sz), received_at
