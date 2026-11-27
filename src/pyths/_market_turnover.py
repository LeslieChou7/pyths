"""M8成交额曲线及App比较；无本机日历昨日或工作日推算。"""

import math
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from ._auth import encode_session_request
from ._compression import decode_snappy
from ._curve import MAX_CURVE_BYTES, CurveData, CurveValue, parse_curve
from ._headers import decode_response_header, encode_request_header
from ._market_models import MarketMetric, MarketTurnover
from ._session import establish_session
from ._trading_calendar import previous_trade_date
from ._transform import checksum_context, transform_request
from ._transport import TcpTransport
from .errors import ThsNetworkError, ThsProtocolError

type TurnoverKind = Literal["current", "reference"]
_PAGES = {"current": 1229, "reference": 1271}


def _date(value: object) -> date:
    if type(value) is not int or not 10000101 <= value <= 99991231:
        raise ThsProtocolError("market turnover: invalid source date")
    text = str(value)
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        raise ThsProtocolError("market turnover: invalid source date") from None


def encode_turnover_body(
    *,
    kind: TurnoverKind,
    instance_id: int,
    reference_date: date | None = None,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """编码ms9/os9固定证券曲线；历史日期来自已核验源日期及交易日历。"""
    if kind not in _PAGES:
        raise ValueError("unsupported market turnover source")
    if kind == "reference":
        if type(reference_date) is not date:
            raise ValueError("reference date required")
    elif reference_date is not None:
        raise ValueError("current turnover does not accept a reference date")
    instances = (instance_id,) if active_instances is None else active_instances
    if (
        type(instance_id) is not int
        or not instances
        or len(instances) > 32
        or instance_id not in instances
        or len(set(instances)) != len(instances)
        or any(type(value) is not int or not 1 <= value <= 65535 for value in instances)
    ):
        raise ThsProtocolError("market turnover: invalid instances")
    pages = ",".join(str(value) for value in instances)
    body = (
        f"[frame]\r\nid=2312\r\npageList={pages}\r\n"
        f"reqPage={instance_id}\r\nreqPageCount=1\r\n[{instance_id}]\r\n"
        f"id={_PAGES[kind]}\r\n\r\nstockcode=883957\r\n"
        f"fstrend={1 if kind == 'current' else 0}\r\nmarketcode=48"
    )
    if reference_date is not None:
        body += (
            "\r\npreday=0\r\nleftday=1\r\npinterval=1\r\n"
            f"endtime={reference_date:%Y%m%d}"
        )
    return (body + "\r\n").encode("ascii")


def encode_turnover_request(
    *,
    kind: TurnoverKind,
    package_id: int,
    instance_id: int,
    app_info: str,
    session_id: str,
    reference_date: date | None = None,
    state_word: int = 0,
    trace_id: str | None = None,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """组合公共头与会话变换；独立会话接受性需单独真实验收。"""
    if type(package_id) is not int or not 1 <= package_id <= 32767:
        raise ThsProtocolError("market turnover: invalid package identifier")
    body = encode_turnover_body(
        kind=kind,
        instance_id=instance_id,
        reference_date=reference_date,
        active_instances=active_instances,
    )
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


def decode_turnover_response(
    header_bytes: bytes,
    payload: bytes,
    *,
    package_id: int,
    instance_id: int,
    expected_date: date | None = None,
) -> CurveData:
    """严格读取完整曲线；首帧布局依据M8独立会话真实响应。"""
    header = decode_response_header(header_bytes)
    initial = (
        header.length == 26
        and header.frame_id == 0
        and header.extension == b"\x00\xff"
        and header.flags in (0x100, 0x1100)
        and package_id > 0
    )
    normal = (
        header.length == 32
        and header.frame_id == 2312
        and header.extension[:4] == b"\x00" * 4
        and header.flags == 0x120
    )
    normal_compressed = (
        header.length == 26
        and header.frame_id == 2312
        and header.extension == b"\x00\xff"
        and header.flags == 0x1100
    )
    if (
        len(header_bytes) != header.length
        or not (initial or normal or normal_compressed)
        or (header.package_id, header.instance_id) != (package_id, instance_id)
        or header.payload_length != len(payload)
        or len(payload) > MAX_CURVE_BYTES
    ):
        raise ThsProtocolError("market turnover: response mismatch")
    body = (
        decode_snappy(payload, max_output=MAX_CURVE_BYTES)
        if (initial and header.flags == 0x1100) or normal_compressed
        else payload
    )
    curve = parse_curve(body)
    _points(curve, expected_date=expected_date)
    return curve


def _source_day(curve: CurveData, *, expected_date: date | None = None) -> date:
    value = curve.extensions.get(32790)
    if value is not None:
        actual = _date(value)
        if expected_date is not None and actual != expected_date:
            raise ThsProtocolError("market turnover: reference date mismatch")
        return actual
    # The observed 1271 response omits 32790. Bind it to the explicit request
    # date only after every packed point confirms the recorded 2026 date bits.
    times = curve.fields.get(1)
    if expected_date is None or expected_date.year != 2026 or not times:
        raise ThsProtocolError("market turnover: missing source date")
    for stamp in times:
        if (
            type(stamp) is not int
            or ((stamp & 267386880) >> 20) != 126
            or ((stamp & 983040) >> 16) != expected_date.month
            or ((stamp & 63488) >> 11) != expected_date.day
        ):
            raise ThsProtocolError("market turnover: packed reference date mismatch")
    return expected_date


def _hhmm(value: CurveValue) -> int:
    """复现ns9.b的位拼接后取HHmm，单位先限于已观察分钟标签。"""
    if type(value) is not int or value < 0:
        raise ThsProtocolError("market turnover: invalid time point")
    if value & 1610612736 and value > 1400000000:
        decoded = value
    else:
        decoded = (
            (value & 63)
            + ((value & 1984) >> 6) * 100
            + ((value & 63488) >> 11) * 10000
            + ((value & 983040) >> 16) * 1000000
            + (((value & 267386880) >> 20) - 90) * 100000000
        )
    hhmm = decoded % 10000
    if hhmm // 100 > 23 or hhmm % 100 > 59:
        raise ThsProtocolError("market turnover: invalid minute label")
    return hhmm


def _native_double(value: CurveValue) -> float:
    if value is None or isinstance(value, bool):
        raise ThsProtocolError("market turnover: missing amount point")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ThsProtocolError("market turnover: invalid amount point") from None
    if not math.isfinite(number) or number < 0:
        raise ThsProtocolError("market turnover: invalid amount point")
    return number


def _points(
    curve: CurveData, *, expected_date: date | None = None
) -> tuple[tuple[int, float], ...]:
    if curve.first_index != 0:
        raise ThsProtocolError("market turnover: incremental curve not supported")
    if curve.extensions.get(4) != "883957" or curve.extensions.get(36103) != "48":
        raise ThsProtocolError("market turnover: source identity mismatch")
    _source_day(curve, expected_date=expected_date)
    amounts, times = curve.fields.get(19), curve.fields.get(1)
    if (
        not amounts
        or not times
        or len(amounts) != curve.row_count
        or len(times) != curve.row_count
    ):
        raise ThsProtocolError("market turnover: missing amount or time field")
    points = tuple(
        (_hhmm(stamp), _native_double(amount))
        for stamp, amount in zip(times, amounts, strict=True)
    )
    if any(right[0] < left[0] for left, right in pairwise(points)):
        raise ThsProtocolError("market turnover: reversed time points")
    return points


def _small_double_text(value: float) -> str:
    # Java Double.toString uses plain notation in [1e-3, 1e7), with a decimal
    # point for whole doubles. Python repr supplies the same observed ordinary
    # financial subset; unobserved extreme shortest-string cases stay out of
    # compatibility claims.
    text = repr(value)
    if value == 0:
        return "0.0"
    if 0.001 <= value < 10000000:
        return format(Decimal(text), "f")
    mantissa, _, exponent = format(Decimal(text), "E").partition("E")
    if "." not in mantissa:
        mantissa += ".0"
    return mantissa + "E" + str(int(exponent))


def format_amount(
    value: float, *, label: str, derivation: str | None = None, prefix: str = ""
) -> MarketMetric:
    """复现ns9.a→imv.a(double,0,true)的double缩放、加0.5及截断。"""
    if not math.isfinite(value):
        raise ThsProtocolError("market turnover: non-finite display amount")
    absolute = abs(value)
    unit: str | None = None
    if absolute >= 100000000:
        scaled = absolute / 100000000.0
        unit = "亿"
    elif absolute >= 100000:
        scaled = absolute / 10000.0
        unit = "万"
    else:
        scaled = absolute
    if unit is not None:
        # imv explicitly adds 0.5 in native double arithmetic, then casts long.
        rounded = min(math.trunc(scaled + 0.5), 9223372036854775807)
        text, display = str(rounded), Decimal(rounded)
    else:
        text = _small_double_text(scaled)
        display = Decimal(text)
    if value < 0:
        text = "-" + text
        display = -display
    return MarketMetric(
        label,
        prefix + text + (unit or ""),
        display,
        unit,
        "rounded",
        derivation=derivation,
    )


def combine_turnover(current: CurveData, reference: CurveData) -> MarketTurnover:
    """同刻优先，缺刻明确标记App末值回退；差额复现double运算。"""
    source_day = _source_day(current)
    previous = previous_trade_date(source_day)
    current_points, reference_points = (
        _points(current),
        _points(reference, expected_date=previous),
    )
    if _source_day(reference, expected_date=previous) != previous:
        raise ThsProtocolError("market turnover: reference date mismatch")
    current_minute, current_value = current_points[-1]
    full_day = current_minute == 1500 and current.row_count == 241
    by_minute = dict(reference_points)
    matched = current_minute in by_minute
    if matched:
        reference_minute, reference_value = current_minute, by_minute[current_minute]
        basis = (
            "上一交易日全日"
            if full_day and reference.row_count == 241
            else "上一交易日同刻"
        )
    else:
        reference_minute, reference_value = reference_points[-1]
        basis = "上一交易日末值（同刻缺失回退）"
    delta = current_value - reference_value
    return MarketTurnover(
        current=format_amount(
            current_value, label="今日成交额总计" if full_day else "今日实时成交额"
        ),
        reference=format_amount(reference_value, label=basis + "成交额"),
        comparison=format_amount(
            delta,
            label=("较上一日" if full_day else "较上一日此时")
            if matched
            else "较上一交易日末值",
            prefix="+" if delta > 0 else "",
            derivation="app_current_minus_reference",
        ),
        comparison_basis=basis,
        reference_time_label=f"{previous:%Y%m%d}/{reference_minute:04d}",
        source_time_label=f"{source_day:%Y%m%d}/{current_minute:04d}",
        current_source_value=Decimal.from_float(current_value),
        reference_source_value=Decimal.from_float(reference_value),
    )


def _query_curve(
    *,
    kind: TurnoverKind,
    reference_date: date | None,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int,
) -> tuple[CurveData, datetime]:
    for attempt in range(retries + 1):
        if time.monotonic() >= deadline:
            raise ThsNetworkError("market turnover: deadline exceeded")
        transport = TcpTransport(max_frame_size=MAX_CURVE_BYTES + 32)
        try:
            transport.connect(
                endpoint, deadline=deadline, connect_timeout=connect_timeout
            )
            init = encode_session_request(
                config=app_config, app_info=app_info, passport=b""
            )
            session = establish_session(transport, init, deadline=deadline)
            packet = encode_turnover_request(
                kind=kind,
                package_id=1,
                instance_id=1,
                app_info=app_info,
                session_id=session.session_id,
                reference_date=reference_date,
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
                    raise ThsProtocolError("market turnover: payload length mismatch")
                if header.flags in (11, 65547):
                    continue
                return (
                    decode_turnover_response(
                        frame[: header.length],
                        frame[header.length :],
                        package_id=1,
                        instance_id=1,
                        expected_date=reference_date,
                    ),
                    received_at,
                )
            raise ThsProtocolError("market turnover: response count limit")
        except ThsNetworkError:
            if attempt == retries:
                raise
        finally:
            transport.close()
    raise ThsNetworkError("market turnover: retry budget exhausted")


def query_turnover(
    *,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int = 0,
) -> tuple[MarketTurnover, datetime]:
    """依源日期先当前后历史，独立连接共享总截止时间；无隐式日期猜测。"""
    if type(retries) is not int or retries not in (0, 1):
        raise ValueError("retries must be 0 or 1")
    if (
        not math.isfinite(connect_timeout)
        or connect_timeout <= 0
        or not math.isfinite(deadline)
    ):
        raise ValueError("invalid market turnover deadline or timeout")
    if not app_config or not app_info:
        raise ValueError("explicit app_config and app_info required")
    current, _ = _query_curve(
        kind="current",
        reference_date=None,
        endpoint=endpoint,
        app_config=app_config,
        app_info=app_info,
        connect_timeout=connect_timeout,
        deadline=deadline,
        retries=retries,
    )
    previous = previous_trade_date(_source_day(current))
    reference, received = _query_curve(
        kind="reference",
        reference_date=previous,
        endpoint=endpoint,
        app_config=app_config,
        app_info=app_info,
        connect_timeout=connect_timeout,
        deadline=deadline,
        retries=retries,
    )
    return combine_turnover(current, reference), received
