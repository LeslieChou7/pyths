"""固定移动页面的市场情绪图表离线解码。"""

import json
import math
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from typing import Literal, NoReturn

from ._http import MAX_BODY
from ._market_models import MarketMetric
from .errors import ThsBusinessError, ThsProtocolError

type SentimentChartKey = Literal[
    "ths_mood_index", "market_continue_board", "continue_limit_up_risk"
]

_METRICS: dict[SentimentChartKey, tuple[tuple[str, str | None], ...]] = {
    "ths_mood_index": (("今日", "%"),),
    "market_continue_board": (("最高板", "板"), ("次高板", "板")),
    "continue_limit_up_risk": (("风险", None), ("近一年中位数", None)),
}
_WIDTHS = {"ths_mood_index": 4, "market_continue_board": 3, "continue_limit_up_risk": 3}
_SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SentimentReading:
    """原生图例中的读数与源等级。"""

    metric: MarketMetric
    level: str | None


@dataclass(frozen=True)
class SentimentPoint:
    """来源时间、按图例排列的数值及未确认语义的附加读数。"""

    source_timestamp_ms: int
    trade_date: date
    values: tuple[Decimal | None, ...]
    auxiliary_values: tuple[Decimal | None, ...] = ()


@dataclass(frozen=True)
class SentimentChart:
    """独立图例及来源点序。最后一个点与图例分别保留。"""

    key: SentimentChartKey
    readings: tuple[SentimentReading, ...]
    points: tuple[SentimentPoint, ...]

    def mood_viewport_labels(
        self, visible_timestamps_ms: AbstractSet[int]
    ) -> tuple[MarketMetric, ...]:
        """按主图可见时间戳复现情绪冰点、沸点，保留来源数据原值。"""
        if self.key != "ths_mood_index":
            raise ValueError("viewport labels are only defined for market sentiment")
        values = []
        for point in self.points:
            value = point.values[0]
            if point.source_timestamp_ms not in visible_timestamps_ms or value is None:
                continue
            number = float(value)
            if math.isfinite(number):
                values.append(number)
        if not values:
            return ()

        limits = (("冰点", max(0.0, min(values))), ("沸点", min(100.0, max(values))))
        result = []
        for label, number in limits:
            # The App applies Number.toFixed(2) to the bounded binary64 value.
            rounded = Decimal.from_float(number).quantize(
                Decimal("0.01"), context=Context(prec=320, rounding=ROUND_HALF_UP)
            )
            result.append(
                MarketMetric(
                    label,
                    f"{rounded:.2f}%",
                    rounded,
                    "%",
                    precision="rounded",
                    derivation="app_derived",
                )
            )
        return tuple(result)


def _invalid() -> NoReturn:
    raise ThsProtocolError("sentiment chart: invalid response")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        _invalid()
    return result


def _numeric(value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and value in ("-", "--")):
        return None
    if isinstance(value, Decimal):
        number = value
    elif type(value) is int:
        number = Decimal(value)
    elif isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation:
            _invalid()
    else:
        _invalid()
    if not number.is_finite():
        _invalid()
    return number


def _readings(
    header: object, specs: tuple[tuple[str, str | None], ...]
) -> tuple[SentimentReading, ...]:
    if not isinstance(header, list):
        _invalid()
    by_label: dict[str, SentimentReading] = {}
    units = dict(specs)
    for entry in header:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            _invalid()
        label = entry["name"]
        if label not in units:
            continue
        if label in by_label or "val" not in entry:
            _invalid()
        raw, level = entry["val"], entry.get("tag")
        if (raw is not None and not isinstance(raw, str)) or (
            level is not None and not isinstance(level, str)
        ):
            _invalid()
        by_label[label] = SentimentReading(
            MarketMetric(
                label, raw if raw is not None else "null", _numeric(raw), units[label]
            ),
            level,
        )
    if by_label.keys() != units.keys():
        _invalid()
    return tuple(by_label[label] for label, _ in specs)


def _points(raw: object, width: int, metric_count: int) -> tuple[SentimentPoint, ...]:
    if not isinstance(raw, list):
        _invalid()
    result = []
    for row in raw:
        if not isinstance(row, list) or len(row) != width or type(row[0]) is not int:
            _invalid()
        timestamp = row[0]
        if not 1_000_000_000_000 <= timestamp < 10_000_000_000_000:
            _invalid()
        local_time = (_EPOCH + timedelta(milliseconds=timestamp)).astimezone(_SHANGHAI)
        if local_time.time() != datetime.min.time():
            _invalid()
        values = tuple(_numeric(item) for item in row[1:])
        result.append(
            SentimentPoint(
                timestamp,
                local_time.date(),
                values[:metric_count],
                values[metric_count:],
            )
        )
    return tuple(result)


def decode_sentiment_charts(body: bytes) -> dict[SentimentChartKey, SentimentChart]:
    """离线读取三项已观察指标，按系列键识别并保留源值与点序。"""
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BODY:
        _invalid()
    try:
        root = json.loads(
            body.decode("utf-8"),
            parse_float=Decimal,
            object_pairs_hook=_object,
            parse_constant=lambda _: _invalid(),
        )
    except (ValueError, RecursionError, ArithmeticError):
        _invalid()
    if not isinstance(root, dict) or type(root.get("status_code")) is not int:
        _invalid()
    if root["status_code"] != 0:
        raise ThsBusinessError("sentiment chart: source rejected request")
    data = root.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("charts"), list):
        _invalid()
    raw_charts = {}
    for chart in data["charts"]:
        if not isinstance(chart, dict) or not isinstance(chart.get("key"), str):
            _invalid()
        key = chart["key"]
        if key not in _METRICS:
            continue
        if key in raw_charts:
            _invalid()
        raw_charts[key] = chart
    return {
        key: SentimentChart(
            key,
            _readings(raw_charts[key].get("header"), specs),
            _points(raw_charts[key].get("point_list"), _WIDTHS[key], len(specs)),
        )
        for key, specs in _METRICS.items()
        if key in raw_charts
    }
