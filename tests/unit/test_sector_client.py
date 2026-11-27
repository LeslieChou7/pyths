import json
from datetime import date, time
from unittest.mock import patch

import pytest

from pyths import SectorPeriod, SectorRef, ThsClientClosedError, ths
from pyths._http import HttpResponse

PERIOD = SectorPeriod.historical_day(date(2026, 11, 12))


def response(kind):
    prefix = "block" if kind == "block" else "stock"
    row = {
        prefix + "_code": "881146" if kind == "block" else "000001",
        prefix + "_market": "48" if kind == "block" else "17",
    }
    return HttpResponse(
        200,
        json.dumps({"status_code": 0, "data": {"total": 1, "list": [row]}}).encode(),
    )


def test_public_chain_passes_reference_and_preserves_stock_code():
    with (
        ths() as client,
        patch(
            "pyths._sector.request", side_effect=[response("block"), response("stock")]
        ) as send,
    ):
        ranking = client.get_sector_ranking(category="industry", period=PERIOD)
        ref = ranking.items[0].sector
        assert isinstance(ref, SectorRef)
        members = client.get_sector_constituents(sector=ref, period=PERIOD)
        assert members.items[0].values.code == "000001"
        assert send.call_count == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "all"},
        {"sort": "main_net_inflow", "direction": "desc"},
        {"sort": "turnover"},
        {"period": SectorPeriod.historical_day(date(2026, 11, 11))},
        {"page": object()},
    ],
)
def test_unverified_combinations_fail_before_network(changes):
    with ths() as client, patch("pyths._sector.request") as send:
        with pytest.raises(ValueError):
            client.get_sector_ranking(
                **{"category": "industry", "period": PERIOD, **changes}
            )
        send.assert_not_called()


def test_foreign_reference_and_closed_client_send_nothing():
    with ths() as client, ths() as other, patch("pyths._sector.request") as send:
        with pytest.raises(ValueError, match="client"):
            client.get_sector_constituents(
                sector=SectorRef(other, "881146", "48"), period=PERIOD
            )
        with pytest.raises(ValueError):
            client.get_sector_constituents(sector=object(), period=PERIOD)
        client.close()
        with pytest.raises(ThsClientClosedError):
            client.get_sector_ranking(category="industry", period=PERIOD)
        send.assert_not_called()


def test_gas_continuation_uses_actual_cursor_and_stops_at_seven():
    def members(count):
        return HttpResponse(
            200,
            json.dumps(
                {
                    "status_code": 0,
                    "data": {
                        "total": 27,
                        "list": [
                            {"stock_code": f"{i:06d}", "stock_market": "17"}
                            for i in range(count)
                        ],
                    },
                }
            ).encode(),
        )

    with (
        ths() as client,
        patch(
            "pyths._sector.request",
            side_effect=[response("block"), members(20), members(7)],
        ) as send,
    ):
        ref = (
            client.get_sector_ranking(category="industry", period=PERIOD)
            .items[0]
            .sector
        )
        first = client.get_sector_constituents(sector=ref, period=PERIOD)
        assert first.next_page is not None
        last = client.get_sector_constituents(
            sector=ref, period=PERIOD, page=first.next_page
        )
        assert last.page == 2 and last.returned_count == 7 and last.has_more is False
        assert last.next_page is None and send.call_count == 3


@pytest.mark.parametrize("sort", ["change_rate", "main_net_inflow", "turnover"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_historical_partial_intraday_differences_remain_blocked(sort, direction):
    period = SectorPeriod.intraday(date(2026, 11, 13), start=time(11, 5), end=time(15))
    with ths() as client, patch("pyths._sector.request") as send:
        with pytest.raises(ValueError, match="verified"):
            client.get_sector_constituents(
                sector=SectorRef(client, "882021", "48"),
                period=period,
                sort=sort,
                direction=direction,
            )
        with pytest.raises(ValueError, match="verified"):
            client.get_sector_ranking(category="region", period=period)
        send.assert_not_called()


@pytest.mark.parametrize(
    ("kind", "sort", "direction"),
    [
        ("block", "change_rate", "asc"),
        ("block", "change_rate", "desc"),
        ("stock", "main_net_inflow", "desc"),
        ("stock", "main_net_inflow", "asc"),
        ("stock", "turnover", "desc"),
    ],
)
def test_verified_partial_period_public_chain(kind, sort, direction):
    period = SectorPeriod.intraday(date(2026, 11, 16), start=time(11, 4), end=time(15))
    block = HttpResponse(
        200,
        json.dumps(
            {
                "status_code": 0,
                "data": {
                    "total": 1,
                    "list": [{"block_code": "882021", "block_market": "48"}],
                },
            }
        ).encode(),
    )
    with (
        ths() as client,
        patch("pyths._sector.request", side_effect=[block, response("stock")]) as send,
    ):
        ranking = client.get_sector_ranking(
            category="region",
            period=period,
            sort="change_rate",
            direction=direction if kind == "block" else "desc",
        )
        if kind == "stock":
            client.get_sector_constituents(
                sector=ranking.items[0].sector,
                period=period,
                sort=sort,
                direction=direction,
            )
        assert send.call_count == (1 if kind == "block" else 2)
        body = json.loads(send.call_args.kwargs["body"])
        assert body["history_info"] == {
            "history_type": "0",
            "start_date": "20261116110400",
            "end_date": "20261116150000",
        }
        if kind == "stock":
            assert body["block_code"] == "882021" and body["block_market"] == "48"
