import time
from datetime import UTC

import pytest

from pyths import (
    HotRankingCursor,
    ThsAuthenticationError,
    ThsBusinessError,
    ThsClientClosedError,
    ThsNetworkError,
    ThsProtocolError,
    ThsRateLimitError,
    _hot,
    ths,
)
from pyths._http import HttpResponse
from tests.hot_fixture import payload


def test_directory_is_local_and_queries_do_not_need_tcp(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return HttpResponse(200, payload())

    monkeypatch.setattr(_hot, "request", request)
    with ths() as client:
        assert [b.id for b in client.get_hot_boards()] == ["stock_hour", "stock_24h"]
        assert not calls
        for board, period in [("stock_hour", "hour"), ("stock_24h", "day")]:
            result = client.get_hot_ranking(board=board)
            assert result.source.endswith(f"/a/{period}/data.txt")
            assert result.returned_count == 2 and result.board == board
            assert result.total is result.next_page is result.has_more is None
            assert result.source_time is result.source_time_label is None
            assert result.received_at.tzinfo is UTC
            assert result.pagination == "single_response"
        client.get_hot_ranking(board="stock_hour")
    assert len(calls) == 3  # No cross-call cache, automatic enrichment or discovery.
    assert all(set(kwargs) == {"deadline", "connect_timeout"} for _, kwargs in calls)
    with pytest.raises(ThsClientClosedError):
        client.get_hot_ranking(board="stock_hour")
    with pytest.raises(ThsClientClosedError):
        client.get_hot_boards()


@pytest.mark.parametrize("board", ["", "day", "stock_skyrocket", None, [], 1])
def test_invalid_board_before_network(monkeypatch, board):
    monkeypatch.setattr(_hot, "request", lambda *a, **kw: pytest.fail("network"))
    with pytest.raises(ValueError):
        ths().get_hot_ranking(board=board)


def test_all_nonempty_cursors_rejected_before_network(monkeypatch):
    monkeypatch.setattr(_hot, "request", lambda *a, **kw: pytest.fail("network"))
    client = ths()
    for page in [object(), HotRankingCursor(client, "stock_hour")]:
        with pytest.raises(ValueError):
            client.get_hot_ranking(board="stock_hour", page=page)


@pytest.mark.parametrize(
    "error",
    [ThsAuthenticationError, ThsRateLimitError, ThsBusinessError, ThsProtocolError],
)
def test_non_network_failure_never_retried(monkeypatch, error):
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        raise error("safe")

    monkeypatch.setattr(_hot, "request", request)
    with pytest.raises(error):
        ths(retries=1).get_hot_ranking(board="stock_hour")
    assert len(calls) == 1


def test_network_retry_is_bounded_and_shares_deadline(monkeypatch):
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ThsNetworkError("failed")
        return HttpResponse(200, payload([]))

    monkeypatch.setattr(_hot, "request", request)
    assert ths(retries=1).get_hot_ranking(board="stock_24h").returned_count == 0
    assert len(calls) == 2 and calls[0]["deadline"] == calls[1]["deadline"]
    calls.clear()
    with pytest.raises(ThsNetworkError):
        ths().get_hot_ranking(board="stock_hour")
    assert len(calls) == 1


def test_expired_deadline_prevents_request(monkeypatch):
    monkeypatch.setattr(_hot, "request", lambda *a, **kw: pytest.fail("network"))
    with pytest.raises(ThsNetworkError):
        _hot.query_hot(
            board="stock_hour",
            connect_timeout=1,
            deadline=time.monotonic() - 1,
            retries=1,
        )


@pytest.mark.parametrize("failure", [False, True])
def test_hot_does_not_touch_existing_quote_session(monkeypatch, failure):
    client = ths(endpoint=("127.0.0.1", 12345), app_config="public", app_info="public")
    session = object()
    client._session = session
    client._counter = 123
    client._completed = {122: ("000001", "33")}
    monkeypatch.setattr(client._transport, "close", lambda: pytest.fail("TCP close"))
    monkeypatch.setattr(
        client._transport, "connect", lambda *a, **kw: pytest.fail("TCP connect")
    )

    def request(*args, **kwargs):
        if failure:
            raise ThsAuthenticationError("rejected")
        return HttpResponse(200, payload())

    monkeypatch.setattr(_hot, "request", request)
    if failure:
        with pytest.raises(ThsAuthenticationError):
            client.get_hot_ranking(board="stock_hour")
    else:
        client.get_hot_ranking(board="stock_hour")
    assert client._session is session and client._counter == 123
    assert client._completed == {122: ("000001", "33")}
