from datetime import date
from unittest.mock import patch

import pytest

from pyths import ths
from pyths._http import HttpResponse
from pyths.errors import ThsProtocolError


def test_sector_snapshot() -> None:
    raw = b'{"status_code":0,"data":{"block_list":[{"code":"B1","market":"48","name":"A","bullish":0,"leader_stocks":[{"code":"002035","market":"33"}]}]}}'
    with (
        patch("pyths._http.request", return_value=HttpResponse(200, raw)) as send,
        ths() as client,
    ):
        value = client.get_auction_sector_changes(
            side="bearish", trade_date=date(2026, 11, 18)
        )
    assert send.call_args.args[0].endswith("/2?date=2026-11-18")
    assert (
        value.side,
        value.sectors[0].market,
        value.sectors[0].fields["bullish"],
    ) == ("bearish", "48", 0)
    assert value.sectors[0].leader_stocks == ({"code": "002035", "market": "33"},)


def test_missing_block_list_is_invalid() -> None:
    with (
        patch(
            "pyths._http.request",
            return_value=HttpResponse(200, b'{"status_code":0,"data":{}}'),
        ),
        ths() as client,
        pytest.raises(ThsProtocolError),
    ):
        client.get_auction_sector_changes(side="bullish", trade_date=date(2026, 11, 18))
