import time
from datetime import date
from unittest.mock import patch

import pytest

from pyths._http import HttpResponse
from pyths._sector import query_sector_page
from pyths._sector_models import SectorPeriod
from pyths._sector_query import SectorQuery
from pyths.errors import (
    ThsAuthenticationError,
    ThsBusinessError,
    ThsNetworkError,
    ThsProtocolError,
    ThsRateLimitError,
)

EMPTY = HttpResponse(200, b'{"status_code":0,"data":{"total":0,"list":[]}}')


def config(**changes):
    return {
        "owner": object(),
        "query": SectorQuery(
            "block",
            SectorPeriod.single_day(date(2026, 11, 13)),
            "change_rate",
            "desc",
            category="all",
        ),
        "cursor": None,
        "deadline": time.monotonic() + 15,
        "connect_timeout": 5,
        "retries": 0,
        **changes,
    }


def test_fixed_post_no_extra_requests_or_credentials():
    with patch("pyths._sector.request", return_value=EMPTY) as send:
        page = query_sector_page(**config())
    assert page.returned_count == 0 and page.source_time is None
    assert send.call_count == 1
    assert send.call_args.kwargs["method"] == "POST"
    assert send.call_args.kwargs["expected_json"] is True
    assert send.call_args.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }


def test_network_retry_shares_deadline():
    args = config(retries=1)
    with patch(
        "pyths._sector.request", side_effect=[ThsNetworkError("safe"), EMPTY]
    ) as send:
        query_sector_page(**args)
    assert send.call_count == 2
    assert {call.kwargs["deadline"] for call in send.call_args_list} == {
        args["deadline"]
    }


@pytest.mark.parametrize(
    "error",
    [ThsAuthenticationError, ThsRateLimitError, ThsBusinessError, ThsProtocolError],
)
def test_rejections_never_retried(error):
    with (
        patch("pyths._sector.request", side_effect=error("safe")) as send,
        pytest.raises(error),
    ):
        query_sector_page(**config(retries=1))
    assert send.call_count == 1


def test_expired_deadline_and_invalid_query_send_nothing():
    with patch("pyths._sector.request") as send:
        with pytest.raises(ThsNetworkError):
            query_sector_page(**config(deadline=time.monotonic() - 1))
        with pytest.raises(ValueError):
            query_sector_page(**config(retries=2))
    send.assert_not_called()


def test_decode_failure_does_not_trigger_network_retry():
    with (
        patch("pyths._sector.request", return_value=HttpResponse(200, b"{")) as send,
        pytest.raises(ThsProtocolError),
    ):
        query_sector_page(**config(retries=1))
    assert send.call_count == 1
