"""使用本地替身验证M14调用，不访问生产服务。"""

import json
from unittest.mock import Mock

import pytest

from pyths import StockAnomalyCursor, TradingStatusCursor, ths
from pyths._http import HttpResponse
from pyths.errors import ThsClientClosedError, ThsNetworkError


def anomaly_body(count=2, total=2):
    row = {
        "stock_code": "000001",
        "stock_market": "33",
        "stock_name": "sample",
        "ths_code": "000001.SZ",
        "monitor_type": 1,
        "start_date": 1,
        "end_date": 2,
    }
    return json.dumps(
        {"status_code": 0, "data": {"total_num": total, "list": [row] * count}}
    ).encode()


def status_body(count=10):
    row = {
        "Code": "000001",
        "Name": "sample",
        "Reason": "reason",
        "Price": "1.00",
        "Change": "0.00",
        "indexChange": "0.00",
        "tpDate": "2026-01-01",
        "fpDate": "未公布",
    }
    return json.dumps([row] * count).encode()


def test_current_single_page_and_no_tcp(monkeypatch):
    send = Mock(return_value=HttpResponse(200, anomaly_body()))
    monkeypatch.setattr("pyths._events.request", send)
    with ths() as client:
        page = client.get_stock_anomalies(kind="current")
        assert len(page.items) == 2 and page.total == 2 and page.has_more is False
        assert page.next_page is None and page.items[0].stock_code == "000001"
        assert page.received_at.utcoffset() is not None
    assert send.call_count == 1
    assert "date_type=monitor&page_num=1" in send.call_args.args[0]
    assert send.call_args.kwargs["headers"] == {"Accept": "application/json"}


def test_current_full_page_reports_more_without_cursor(monkeypatch):
    send = Mock(return_value=HttpResponse(200, anomaly_body(20, 21)))
    monkeypatch.setattr("pyths._events.request", send)
    with ths() as client:
        page = client.get_stock_anomalies(kind="current")
        assert page.has_more is True and page.next_page is None
        with pytest.raises(ValueError, match="only support the first page"):
            client.get_stock_anomalies(
                kind="current", page=StockAnomalyCursor(client, "current", 2)
            )
    assert send.call_count == 1


def test_history_cursor_binding(monkeypatch):
    send = Mock(return_value=HttpResponse(200, anomaly_body(20, 747)))
    monkeypatch.setattr("pyths._events.request", send)
    with ths() as a, ths() as b:
        page = a.get_stock_anomalies(kind="history")
        assert page.next_page is not None and page.has_more is True
        for client, kind in ((b, "history"), (a, "current")):
            with pytest.raises(ValueError):
                client.get_stock_anomalies(kind=kind, page=page.next_page)
        assert send.call_count == 1
        second = a.get_stock_anomalies(kind="history", page=page.next_page)
        assert second.next_page is None and second.has_more is True
        assert "page_num=2" in send.call_args.args[0]


def test_status_unknown_end_and_cursor(monkeypatch):
    send = Mock(return_value=HttpResponse(200, status_body()))
    monkeypatch.setattr("pyths._events.request", send)
    with ths() as client:
        page = client.get_trading_status_events(kind="suspension")
        assert (
            page.has_more is None and page.total is None and page.next_page is not None
        )
        with pytest.raises(ValueError):
            client.get_trading_status_events(kind="resumption", page=page.next_page)
        send.return_value = HttpResponse(200, b"[]")
        final = client.get_trading_status_events(kind="suspension", page=page.next_page)
        assert final.has_more is False and final.next_page is None


def test_close_invalid_and_no_retry(monkeypatch):
    send = Mock(side_effect=ThsNetworkError("failed"))
    monkeypatch.setattr("pyths._events.request", send)
    client = ths(retries=1)
    with pytest.raises(ThsNetworkError):
        client.get_stock_anomalies(kind="current")
    assert send.call_count == 1
    for cursor in (
        StockAnomalyCursor(client, "history", 3),
        TradingStatusCursor(client, "resumption", 2),
    ):
        with pytest.raises(ValueError):
            client.get_stock_anomalies(kind="history", page=cursor)
    client.close()
    with pytest.raises(ThsClientClosedError):
        client.get_stock_anomalies(kind="current")
    with pytest.raises(ThsClientClosedError):
        client.get_trading_status_events(kind="suspension")
    assert send.call_count == 1
