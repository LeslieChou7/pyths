import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pyths import ThsBusinessError, ThsProtocolError
from pyths._sentiment_codec import decode_sentiment_charts

_FIXTURE = Path(__file__).parents[1] / "fixtures/synthetic/sentiment-charts.json"


def test_synthetic_chart_maps_three_native_readings() -> None:
    charts = decode_sentiment_charts(_FIXTURE.read_bytes())
    mood = charts["ths_mood_index"]
    height = charts["market_continue_board"]
    risk = charts["continue_limit_up_risk"]
    assert mood.readings[0].metric.raw == "26.50"
    assert mood.readings[0].metric.value == Decimal("26.50")
    assert mood.readings[0].metric.unit == "%"
    assert mood.readings[0].level == "低"
    assert [point.values[0] for point in mood.points[1:]] == [62, 35, 26.5]
    assert mood.points[-1].auxiliary_values == (
        Decimal("70.125"),
        Decimal(42),
    )
    assert mood.points[-1].source_timestamp_ms == 1709740800000
    assert [point.trade_date for point in mood.points[1:]] == [
        date(2024, 3, 5),
        date(2024, 3, 6),
        date(2024, 3, 7),
    ]
    assert [value.metric.label for value in height.readings] == ["最高板", "次高板"]
    assert [point.values for point in height.points[1:]] == [(7, 4), (5, 3), (5, 2)]
    assert risk.readings[0].level == "高"
    assert risk.readings[0].metric.unit is None
    assert (
        risk.readings[0].metric.value == risk.readings[1].metric.value == Decimal("0.6")
    )
    assert [point.values for point in risk.points[1:]] == [
        (0, Decimal("0.6")),
        (0, Decimal("0.48")),
        (Decimal("0.6"), Decimal("0.6")),
    ]


def test_header_reordering_and_unknown_series_leave_point_identity_intact() -> None:
    source = json.loads(_FIXTURE.read_bytes())
    charts = source["data"]["charts"]
    charts[1]["header"].reverse()
    charts.reverse()
    charts.insert(0, {"key": "unknown_series"})
    result = decode_sentiment_charts(json.dumps(source).encode())
    height = result["market_continue_board"]
    assert len(result) == 3
    assert [item.metric.value for item in height.readings] == [Decimal(5), Decimal(2)]
    assert height.points[-1].values == (Decimal(5), Decimal(2))


def test_mood_viewport_labels_match_app_and_exclude_offscreen_points() -> None:
    body = _FIXTURE.with_name("sentiment-viewport.json").read_bytes()
    mood = decode_sentiment_charts(body)["ths_mood_index"]
    visible = {point.source_timestamp_ms for point in mood.points[2:]}

    ice, boil = mood.mood_viewport_labels(visible)
    assert (ice.label, ice.raw, ice.value) == ("冰点", "8.00%", Decimal("8.00"))
    assert (boil.label, boil.raw, boil.value) == ("沸点", "84.00%", Decimal("84.00"))
    assert ice.derivation == boil.derivation == "app_derived"
    assert ice.precision == boil.precision == "rounded"
    assert mood.readings[0].metric.derivation is None

    offscreen = {point.source_timestamp_ms for point in mood.points[:2]}
    assert [
        metric.value for metric in mood.mood_viewport_labels(visible | offscreen)
    ] == [
        2,
        91,
    ]
    assert mood.mood_viewport_labels({0}) == ()


def test_mood_viewport_labels_apply_app_limits_and_rounding() -> None:
    source = json.loads(_FIXTURE.read_bytes())
    mood_source = source["data"]["charts"][0]
    for row, value in zip(
        mood_source["point_list"], (-1, None, 100.5, 25.125), strict=True
    ):
        row[1] = value
    charts = decode_sentiment_charts(json.dumps(source).encode())
    mood = charts["ths_mood_index"]
    visible = {point.source_timestamp_ms for point in mood.points}
    assert [metric.raw for metric in mood.mood_viewport_labels(visible)] == [
        "0.00%",
        "100.00%",
    ]
    assert mood.mood_viewport_labels({mood.points[1].source_timestamp_ms}) == ()
    assert [
        metric.raw
        for metric in mood.mood_viewport_labels({mood.points[-1].source_timestamp_ms})
    ] == ["25.13%", "25.13%"]
    with pytest.raises(ValueError, match="only defined for market sentiment"):
        charts["market_continue_board"].mood_viewport_labels(visible)


def test_empty_null_zero_and_missing_series_have_distinct_results() -> None:
    source = json.loads(_FIXTURE.read_bytes())
    charts = source["data"]["charts"]
    charts[0]["point_list"] = []
    charts[1]["point_list"][0][1:] = [0, None]
    charts.pop()
    result = decode_sentiment_charts(json.dumps(source).encode())
    assert result["ths_mood_index"].points == ()
    assert result["market_continue_board"].points[0].values == (Decimal(0), None)
    assert "continue_limit_up_risk" not in result


@pytest.mark.parametrize(
    "body",
    [
        b'{"status_code":0,"data":',
        b'{"status_code":0,"status_code":0,"data":{"charts":[]}}',
        b'{"status_code":false,"data":{"charts":[]}}',
        b'{"status_code":0,"data":{}}',
        b'{"status_code":0,"data":{"charts":[{"key":"ths_mood_index"}]}}',
        b'{"status_code":0,"data":{"charts":[{"key":"ths_mood_index"},{"key":"ths_mood_index"}]}}',
    ],
)
def test_rejects_truncated_and_malformed_responses(body: bytes) -> None:
    with pytest.raises(ThsProtocolError, match="invalid response"):
        decode_sentiment_charts(body)


def test_rejects_shifted_point_columns_and_unconfirmed_time_unit() -> None:
    source = json.loads(_FIXTURE.read_bytes())
    point = source["data"]["charts"][0]["point_list"][0]
    source_time = point.pop(0)
    with pytest.raises(ThsProtocolError):
        decode_sentiment_charts(json.dumps(source).encode())
    point.insert(0, source_time // 1000)
    with pytest.raises(ThsProtocolError):
        decode_sentiment_charts(json.dumps(source).encode())


def test_business_failure_does_not_expose_source_message() -> None:
    with pytest.raises(
        ThsBusinessError, match="^sentiment chart: source rejected request$"
    ):
        decode_sentiment_charts(b'{"status_code":1,"message":"opaque server status"}')
