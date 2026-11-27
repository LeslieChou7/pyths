import json
from dataclasses import replace
from datetime import date

import pytest

from pyths._sector_models import SectorPeriod
from pyths._sector_query import SectorCursor, SectorQuery, SectorRef, encode_query


def query():
    return SectorQuery(
        "block",
        SectorPeriod.single_day(date(2026, 11, 13)),
        "change_rate",
        "desc",
        category="region",
    )


def test_same_query_cursor_encodes_only_one_next_page():
    owner = object()
    current = query()
    page, body = encode_query(owner, current, SectorCursor(owner, current, 2))
    assert page == 2 and json.loads(body)["page_info"] == {"page": 2, "page_size": 20}


@pytest.mark.parametrize(
    "change",
    [
        {"category": "industry"},
        {"sort": "turnover"},
        {"direction": "asc"},
        {"period": SectorPeriod.single_day(date(2026, 11, 12))},
    ],
)
def test_query_changes_reject_old_cursor(change):
    owner = object()
    original = query()
    with pytest.raises(ValueError):
        encode_query(
            owner, replace(original, **change), SectorCursor(owner, original, 2)
        )


def test_cross_client_and_invalid_page_rejected():
    owner = object()
    current = query()
    for cursor in (
        SectorCursor(object(), current, 2),
        SectorCursor(owner, current, True),
        SectorCursor(owner, current, 1),
    ):
        with pytest.raises(ValueError):
            encode_query(owner, current, cursor)


def test_constituent_identity_bound_to_client_source_and_query():
    owner = object()
    ref = SectorRef(owner, "882021", "48")
    current = SectorQuery("stock", query().period, "turnover", "desc", sector=ref)
    _, body = encode_query(owner, current)
    assert json.loads(body)["block_market"] == "48"
    for bad in (replace(ref, _owner=object()), replace(ref, source="other")):
        with pytest.raises(ValueError):
            encode_query(owner, replace(current, sector=bad))
    cursor = SectorCursor(owner, current, 2)
    with pytest.raises(ValueError):
        encode_query(
            owner, replace(current, sector=replace(ref, code="882019")), cursor
        )


def test_same_date_historical_mode_rejects_intraday_cursor():
    owner = object()
    original = query()
    changed = replace(
        original, period=SectorPeriod.historical_day(original.period.start_date)
    )
    with pytest.raises(ValueError):
        encode_query(owner, changed, SectorCursor(owner, original, 2))
