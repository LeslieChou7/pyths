from datetime import UTC, date, datetime, time

import pytest

from pyths._sector_models import SectorPeriod
from pyths._sector_request import encode_period_request, encode_sector_request


def test_observed_interval_encodings():
    day = date(2026, 11, 13)
    assert SectorPeriod.single_day(day).wire_values() == (
        "0",
        "20261113093000",
        "20261113150000",
    )
    assert SectorPeriod.intraday(
        day, start=time(11, 5), end=time(15)
    ).wire_values() == ("0", "20261113110500", "20261113150000")
    assert SectorPeriod.multi_day(date(2026, 11, 2), day).wire_values() == (
        "1",
        "20261102000000",
        "20261113000000",
    )


@pytest.mark.parametrize(
    "start",
    [
        time(10, 0, 1),
        time(10, microsecond=1),
        time(10, tzinfo=UTC),
        time(10, fold=1),
        None,
    ],
)
def test_rejects_unobserved_time_precision(start):
    with pytest.raises(ValueError):
        SectorPeriod.intraday(date(2026, 11, 13), start=start, end=time(15))


def test_no_date_coercion_or_silent_calendar_adjustment():
    with pytest.raises(ValueError):
        SectorPeriod.single_day(datetime(2026, 11, 13, tzinfo=UTC))
    with pytest.raises(ValueError):
        SectorPeriod.multi_day(date(2026, 11, 13), date(2026, 11, 2))
    assert SectorPeriod.single_day(date(2026, 11, 14)).start_date == date(2026, 11, 14)


@pytest.mark.parametrize(
    "period,mode,start,end",
    [
        (
            SectorPeriod.single_day(date(2026, 11, 13)),
            "0",
            "20261113093000",
            "20261113150000",
        ),
        (
            SectorPeriod.intraday(date(2026, 11, 13), start=time(11, 5), end=time(15)),
            "0",
            "20261113110500",
            "20261113150000",
        ),
        (
            SectorPeriod.multi_day(date(2026, 11, 2), date(2026, 11, 13)),
            "1",
            "20261102000000",
            "20261113000000",
        ),
    ],
)
def test_typed_period_matches_wire_encoding(period, mode, start, end):
    common = {
        "kind": "stock",
        "code": "882021",
        "market": "48",
        "sort": "turnover",
        "direction": "desc",
    }
    assert encode_period_request(period=period, **common) == encode_sector_request(
        start=start, end=end, history_type=mode, **common
    )


def test_missing_period_is_not_implicit_latest():
    with pytest.raises(ValueError):
        encode_period_request(
            period=None,
            kind="block",
            category="all",
            sort="change_rate",
            direction="desc",
        )


def test_historical_day_observed_encoding():
    period = SectorPeriod.historical_day(date(2026, 11, 12))
    assert period.wire_values() == ("1", "20261112000000", "20261112000000")
    assert period != SectorPeriod.single_day(date(2026, 11, 12))
    with pytest.raises(ValueError):
        SectorPeriod("historical_day", date(2026, 11, 12), date(2026, 11, 13))
    with pytest.raises(ValueError):
        SectorPeriod(
            "historical_day",
            date(2026, 11, 12),
            date(2026, 11, 12),
            time(9, 30),
            time(15),
        )
