"""公共入口只沿验证过的榜单路由发送一次。"""

import json
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from pyths import AuctionRankingKind, ths
from pyths._http import HttpResponse
from pyths.errors import ThsClientClosedError


@pytest.mark.parametrize(
    ("kind", "route", "sort"),
    [
        ("one_price", "limit_board", "imbalance"),
        ("yesterday_limit_up", "yesterday_limit_up", ""),
        ("weak_to_strong", "weak_to_strong", "warnTimestamp"),
    ],
)
def test_current_first_page(kind: AuctionRankingKind, route: str, sort: str) -> None:
    today = datetime.now(timezone(timedelta(hours=8))).date()
    raw = b'{"status_code":0,"data":{"header_list":[],"data_list":[],"total":0,"current_page":0}}'
    with (
        patch("pyths._http.request", return_value=HttpResponse(200, raw)) as send,
        ths() as client,
    ):
        page = client.get_auction_ranking(kind=kind, trade_date=today)
    assert (page.kind, page.request_date, page.rows) == (kind, today, ())
    assert page.received_at.tzinfo is UTC
    send.assert_called_once()
    assert send.call_args.args[0].endswith("/real_time_list/" + route)
    assert send.call_args.kwargs["method"] == "POST"
    assert json.loads(send.call_args.kwargs["body"]) == {
        "date": today.isoformat(),
        "page_num": 1,
        "page_size": 20,
        "sort": 0,
        "sort_field": sort,
        "filter": None,
    }


def test_date_and_close_checked_before_send() -> None:
    with patch("pyths._http.request") as send:
        client = ths()
        with pytest.raises(ValueError):
            client.get_auction_ranking(kind="one_price", trade_date=date.min)
        client.close()
        with pytest.raises(ThsClientClosedError):
            client.get_auction_ranking(kind="one_price", trade_date=date.min)
        send.assert_not_called()
