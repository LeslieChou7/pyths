from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from pyths import AuctionSector, AuctionSectorSnapshot, ths
from pyths.errors import ThsProtocolError, ThsRateLimitError

DAY = date(2026, 11, 18)


def snapshot(*items: tuple[str, int]) -> AuctionSectorSnapshot:
    return AuctionSectorSnapshot(
        "bullish",
        DAY,
        datetime.now(UTC),
        tuple(
            AuctionSector("48", code, code, {"value": value}, None)
            for code, value in items
        ),
    )


def test_budget_and_changes() -> None:
    a = snapshot(("A", 1), ("B", 2))
    b = snapshot(("B", 3), ("C", 0))
    with (
        ths() as client,
        patch(
            "pyths._auction_watch.query_auction_sectors", side_effect=[a, a, b, a]
        ) as send,
        patch.object(client._auction_closed, "wait", return_value=False),
    ):
        it = client.watch_auction_sector_changes(
            side="bullish", trade_date=DAY, interval=5, max_duration=60, max_requests=4
        )
        first, unchanged, changed, returned = list(it)
        assert first.baseline and not first.entered
        assert not unchanged.baseline and not (
            unchanged.entered or unchanged.updated or unchanged.left
        )
        assert (changed.entered, changed.updated, changed.left) == (
            (b.sectors[1],),
            (b.sectors[0],),
            (a.sectors[0],),
        )
        assert returned.entered == (a.sectors[0],)
        assert send.call_count == 4


@pytest.mark.parametrize("stop", ["client", "iterator", "duration"])
def test_no_more_sends(stop: str) -> None:
    with (
        ths() as client,
        patch(
            "pyths._auction_watch.query_auction_sectors", return_value=snapshot()
        ) as send,
    ):
        it = client.watch_auction_sector_changes(
            side="bearish", trade_date=DAY, interval=5, max_duration=2, max_requests=10
        )
        assert next(it).baseline
        if stop == "client":
            client.close()
        if stop == "iterator":
            it.close()
        assert list(it) == [] and send.call_count == 1


def test_limit_and_ambiguous_identity_stop_iteration() -> None:
    for result, exc in [
        (ThsRateLimitError(), ThsRateLimitError),
        (snapshot(("A", 1), ("A", 2)), ThsProtocolError),
    ]:
        with (
            ths() as client,
            patch(
                "pyths._auction_watch.query_auction_sectors", side_effect=[result]
            ) as send,
        ):
            it = client.watch_auction_sector_changes(
                side="bullish",
                trade_date=DAY,
                interval=5,
                max_duration=60,
                max_requests=2,
            )
            with pytest.raises(exc):
                next(it)
            assert list(it) == [] and send.call_count == 1
