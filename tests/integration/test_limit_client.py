"""公共客户端配本地HTTP替身；报文合成，不访问生产服务。"""

import json
from datetime import date
from unittest.mock import Mock

import pytest

from pyths import (
    LimitFilters,
    ThsClientClosedError,
    ThsNetworkError,
    ThsProtocolError,
    ths,
)
from pyths._http import HttpResponse

DAY = date(2026, 11, 13)
ARGS = {"pool": "limit_down", "trade_date": DAY, "sort": "latest", "direction": "asc"}


def response(page=1, rows=15, total=33, source_date="20261113", rate=0.5):
    body = {
        "status_code": 0,
        "data": {
            "date": source_date,
            "page": {
                "page": page,
                "limit": 15,
                "total": total,
                "count": (total + 14) // 15,
            },
            "info": [
                {"code": "000001", "market_id": 33, "name": "synthetic", "latest": 1.25}
                for _ in range(rows)
            ],
            "limit_up_count": {
                "today": {"num": 1, "open_num": 1, "rate": rate},
                "yesterday": {"num": 0, "open_num": 0, "rate": 0},
            },
        },
    }
    return HttpResponse(200, json.dumps(body).encode())


def test_public_pagination_and_final_page(monkeypatch):
    send = Mock(side_effect=[response(), response(2), response(3, 3)])
    monkeypatch.setattr("pyths._limit.request", send)
    with ths() as client:
        first = client.get_limit_pool(**ARGS)
        second = client.get_limit_pool(**ARGS, page=first.next_page)
        final = client.get_limit_pool(**ARGS, page=second.next_page)
    assert len(first.items) == 15 and first.returned_count == 15
    assert first.items[0].code == "000001"
    assert final.has_more is False and final.next_page is None
    assert send.call_count == 3
    assert "page=2" in send.call_args_list[1].args[0]
    assert send.call_args.kwargs["headers"] == {"Accept": "application/json"}


def test_cursor_isolation_and_pre_send_rejection(monkeypatch):
    send = Mock(return_value=response())
    monkeypatch.setattr("pyths._limit.request", send)
    with ths() as client, ths() as other:
        first = client.get_limit_pool(**ARGS)
        with pytest.raises(ValueError):
            other.get_limit_pool(**ARGS, page=first.next_page)
        with pytest.raises(ValueError):
            client.get_limit_pool(
                **(ARGS | {"sort": "change_rate"}), page=first.next_page
            )
        with pytest.raises(ValueError):
            client.get_limit_pool(pool="limit_up")
        with pytest.raises(ValueError):
            client.get_limit_pool(pool="limit_down", trade_date=date(2025, 1, 1))
        with pytest.raises(ValueError):
            client.get_limit_pool(
                **(ARGS | {"filters": LimitFilters(markets=("HS",), include_st=True)})
            )
    assert send.call_count == 1


@pytest.mark.parametrize("wire", [response(source_date="20261116"), response(page=2)])
def test_response_context_mismatch(monkeypatch, wire):
    send = Mock(return_value=wire)
    monkeypatch.setattr("pyths._limit.request", send)
    with ths() as client, pytest.raises(ThsProtocolError):
        client.get_limit_pool(**ARGS)


def test_inconsistent_short_page_has_no_cursor(monkeypatch):
    monkeypatch.setattr("pyths._limit.request", Mock(return_value=response(rows=3)))
    with ths() as client:
        result = client.get_limit_pool(**ARGS)
    assert result.has_more is None and result.next_page is None
    assert "source_page_inconsistent" in result.warnings


def test_summary_and_explicit_partial(monkeypatch):
    send = Mock(return_value=response(rate=None))
    monkeypatch.setattr("pyths._limit.request", send)
    with ths() as client:
        with pytest.raises(ThsProtocolError):
            client.get_limit_focus_summary(trade_date=DAY)
        result = client.get_limit_focus_summary(trade_date=DAY, allow_partial=True)
        assert result.today.rate is None and result.yesterday.num == 0
        assert result.yesterday_date_raw is None and result.source_time is None
        assert "incomplete_summary" in result.warnings
    assert send.call_count == 2


def test_local_capabilities_closed_and_zero_retry(monkeypatch):
    send = Mock(side_effect=ThsNetworkError("synthetic"))
    monkeypatch.setattr("pyths._limit.request", send)
    with ths(retries=1) as client:
        capabilities = client.get_limit_capabilities()
        assert len(capabilities.public_verified_scopes) == 24
        assert set(capabilities.public_verified_scopes) <= set(
            capabilities.app_observed_scopes
        )
        assert send.call_count == 0
        with pytest.raises(ThsNetworkError):
            client.get_limit_pool(**ARGS)
    with pytest.raises(ThsClientClosedError):
        client.get_limit_pool(**ARGS)
    with pytest.raises(ThsClientClosedError):
        client.get_limit_capabilities()
    assert send.call_count == 1


def test_empty_source_page_zero_and_summary(monkeypatch):
    send = Mock(return_value=response(page=0, rows=0, total=0))
    monkeypatch.setattr("pyths._limit.request", send)
    filters = LimitFilters(markets=("GEM2STAR",))
    with ths() as client:
        page = client.get_limit_pool(**(ARGS | {"filters": filters}))
        assert page.page == 1 and page.source_page == 0
        assert page.has_more is False and page.next_page is None
        assert page.returned_count == 0
        summary = client.get_limit_focus_summary(trade_date=DAY, filters=filters)
        assert summary.today.num == 1 and summary.yesterday.num == 0
    assert send.call_count == 2
