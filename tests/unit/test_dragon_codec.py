"""龙虎榜合成边界测试，不联网、不读取研究仓库。"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from pyths._dragon_codec import (
    decode_dragon_calendar,
    decode_dragon_detail,
    decode_dragon_events,
    decode_dragon_list,
)
from pyths._dragon_models import DragonTigerEntryRef
from pyths.errors import ThsBusinessError, ThsProtocolError
from tests.dragon_fixture import (
    calendar_data,
    detail_data,
    encode,
    event_data,
    list_data,
)

NOW = datetime(2026, 11, 6, tzinfo=UTC)
DAY = date(2026, 11, 5)


@pytest.mark.parametrize("with_calendar", [False, True])
def test_empty_list_null_stock_count_preserved(with_calendar: bool) -> None:
    payload = list_data()
    payload.update(count=0, stock_count=None, items=[])
    calendar = (
        decode_dragon_calendar(encode(calendar_data()), received_at=NOW)
        if with_calendar
        else None
    )
    page = decode_dragon_list(
        encode(payload),
        owner=object(),
        request_date=date(2026, 11, 6),
        received_at=NOW,
        calendar=calendar,
    )
    assert page.stock_count is None
    assert page.total == 0 and not page.items and not page.has_more
    assert page.status == ("pending" if with_calendar else "unknown")


def entry(owner: object) -> DragonTigerEntryRef:
    return DragonTigerEntryRef(owner, "33", "000001", DAY, 1)


def test_list_keeps_duplicate_security_different_ranges() -> None:
    owner = object()
    page = decode_dragon_list(
        encode(list_data(duplicate_security=True)),
        owner=owner,
        request_date=DAY,
        received_at=NOW,
    )
    assert [item.ref.stock_code for item in page.items] == ["000001", "000001"]
    assert [item.ref.range_days for item in page.items] == [1, 3]
    assert page.total == 2 and page.stock_count == 1
    assert page.source_date is None and page.status == "unknown"
    assert page.items[0].buy_value == Decimal("12.5")
    assert page.items[0].change is None and page.items[0].amount_unit is None


def test_multi_reason_is_one_event_and_seats_keep_both_directions() -> None:
    owner = object()
    events = decode_dragon_events(
        encode(detail_data()), owner=owner, entry=entry(owner), received_at=NOW
    )
    assert len(events) == 1 and len(events[0].reasons) == 2
    assert events[0].buy_value == Decimal("12.5")
    detail = decode_dragon_detail(
        encode(detail_data()), owner=owner, event=events[0].ref, received_at=NOW
    )
    assert detail.buy_value == Decimal("12.5")
    assert detail.buy_seats[0].name == detail.sell_seats[0].name
    assert detail.buy_seats[0].direction == "buy"
    assert detail.sell_seats[0].direction == "sell"
    assert detail.buy_seats[0].sell_value is None


def test_decimal_exact_and_unknown_fields() -> None:
    owner = object()
    body = encode(list_data()).replace(b"12.5", b"12.500000000000000000001")
    page = decode_dragon_list(body, owner=owner, request_date=DAY, received_at=NOW)
    assert page.items[0].buy_value == Decimal("12.500000000000000000001")
    data = detail_data()
    data["future"] = {"new": "ignored"}
    assert (
        len(
            decode_dragon_events(
                encode(data), owner=owner, entry=entry(owner), received_at=NOW
            )
        )
        == 1
    )


def test_duplicate_complete_event_rejected() -> None:
    owner = object()
    data = detail_data()
    data["details"] = {
        "one": [event_data(), event_data()],
        "three": [],
        "ten": [],
        "thirty": [],
    }
    with pytest.raises(ThsProtocolError):
        decode_dragon_events(
            encode(data), owner=owner, entry=entry(owner), received_at=NOW
        )


def test_changed_reason_or_interval_does_not_match() -> None:
    owner = object()
    event = decode_dragon_events(
        encode(detail_data()), owner=owner, entry=entry(owner), received_at=NOW
    )[0]
    with pytest.raises(ThsProtocolError):
        decode_dragon_detail(
            encode(detail_data()),
            owner=owner,
            event=replace(event.ref, start_date=date(2026, 11, 4)),
            received_at=NOW,
        )


def test_owner_binding_before_response_parse() -> None:
    with pytest.raises(ValueError):
        decode_dragon_events(
            b"invalid", owner=object(), entry=entry(object()), received_at=NOW
        )


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"[]",
        b"\xff",
        b'{"status_code":0,"status_code":0,"data":{}}',
        b'{"status_code":0,"data":{"x":NaN}}',
    ],
)
def test_bad_json_rejected(body: bytes) -> None:
    with pytest.raises(ThsProtocolError):
        decode_dragon_calendar(body, received_at=NOW)


@pytest.mark.parametrize(
    "field", ["market_id", "stock_code", "range_days", "buy_value", "stock_name"]
)
def test_missing_list_identity_or_required_amount(field: str) -> None:
    data = list_data()
    rows = data["items"]
    assert isinstance(rows, list)
    del rows[0][field]
    with pytest.raises(ThsProtocolError):
        decode_dragon_list(
            encode(data), owner=object(), request_date=DAY, received_at=NOW
        )


@pytest.mark.parametrize(
    "field,value",
    [("count", 2), ("stock_count", 2), ("page", 2), ("size", 49), ("module", "other")],
)
def test_list_metadata_mismatch(field: str, value: object) -> None:
    data = list_data()
    data[field] = value
    with pytest.raises(ThsProtocolError):
        decode_dragon_list(
            encode(data), owner=object(), request_date=DAY, received_at=NOW
        )


def test_empty_without_calendar_unknown_not_pending() -> None:
    data = {
        "module": "all",
        "count": 0,
        "stock_count": 0,
        "page": 1,
        "size": 50,
        "items": [],
    }
    calendar = decode_dragon_calendar(encode(calendar_data()), received_at=NOW)
    page = decode_dragon_list(
        encode(data), owner=object(), request_date=DAY, received_at=NOW
    )
    assert page.status == "unknown"
    pending = decode_dragon_list(
        encode(data),
        owner=object(),
        request_date=date(2026, 11, 6),
        received_at=NOW,
        calendar=calendar,
    )
    assert pending.status == "pending"


def test_business_error_not_empty() -> None:
    with pytest.raises(ThsBusinessError):
        decode_dragon_calendar(encode({}, status=10001), received_at=NOW)


def test_detail_wrong_security_or_date() -> None:
    owner = object()
    data = deepcopy(detail_data())
    data["stock_code"] = "000002"
    with pytest.raises(ThsProtocolError):
        decode_dragon_events(
            encode(data), owner=owner, entry=entry(owner), received_at=NOW
        )
    with pytest.raises(ThsProtocolError):
        decode_dragon_events(
            encode(detail_data()),
            owner=owner,
            entry=replace(entry(owner), request_date=date(2026, 11, 4)),
            received_at=NOW,
        )


def test_all_truncations_fail_without_partial_result() -> None:
    owner = object()
    body = encode(detail_data())
    for cut in range(len(body)):
        with pytest.raises(ThsProtocolError):
            decode_dragon_events(
                body[:cut], owner=owner, entry=entry(owner), received_at=NOW
            )
