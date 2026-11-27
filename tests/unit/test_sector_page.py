import json
from datetime import UTC, date, datetime, time
from pathlib import Path

from pyths._sector_models import SectorPeriod
from pyths._sector_page import assemble_page
from pyths._sector_query import SectorQuery, SectorRef, encode_query

NOW = datetime(2026, 11, 14, tzinfo=UTC)


def query():
    return SectorQuery(
        "block",
        SectorPeriod.single_day(date(2026, 11, 13)),
        "change_rate",
        "desc",
        category="region",
    )


def response(count, total):
    return json.dumps(
        {
            "status_code": 0,
            "data": {
                "total": total,
                "list": [
                    {"block_code": "882021", "block_market": "48"} for _ in range(count)
                ],
            },
        }
    ).encode()


def test_full_page_cursor_and_short_terminal_page():
    owner = object()
    current = query()
    first = assemble_page(response(20, 33), owner=owner, query=current, received_at=NOW)
    assert first.has_more is True and first.returned_count == 20
    assert len(first.items) == 20  # Source duplicates remain intact.
    second = assemble_page(
        response(13, 33),
        owner=owner,
        query=current,
        received_at=NOW,
        cursor=first.next_page,
    )
    assert second.page == 2 and second.has_more is False and second.next_page is None


def test_inconsistent_short_and_empty_pages_do_not_claim_terminal():
    for count in (0, 3):
        page = assemble_page(
            response(count, 33), owner=object(), query=query(), received_at=NOW
        )
        assert page.has_more is None and page.next_page is None and page.warnings


def test_list_to_constituent_reference_and_local_fixture():
    owner = object()
    first = assemble_page(response(1, 1), owner=owner, query=query(), received_at=NOW)
    ref = first.items[0].sector
    assert isinstance(ref, SectorRef)
    current = SectorQuery(
        "stock",
        SectorPeriod.intraday(date(2026, 11, 13), start=time(11, 5), end=time(15)),
        "main_net_inflow",
        "desc",
        sector=ref,
    )
    _, request = encode_query(owner, current)
    assert json.loads(request)["block_code"] == "882021"
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures/synthetic/sector-stock.json"
    )
    page = assemble_page(
        fixture.read_bytes(), owner=owner, query=current, received_at=NOW
    )
    assert page.total == 16 and page.returned_count == 16 and page.has_more is False
    assert page.source_time is None and all(item.sector is None for item in page.items)
