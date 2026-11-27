"""合成HTTP替身核对显式事件流程与总超时；默认不访问生产。"""

import importlib
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from pyths import (
    DragonTigerCursor,
    DragonTigerEntryRef,
    ThsBusinessError,
    ThsClientClosedError,
    ThsNetworkError,
    ths,
)
from pyths._http import HttpResponse
from tests.dragon_fixture import calendar_data, detail_data, encode, list_data

DAY = date(2026, 11, 5)


def install(monkeypatch, *, error=None):
    calls = []
    module = importlib.import_module("pyths._dragon")

    def request(url, *, deadline, connect_timeout):
        calls.append((url, deadline, connect_timeout))
        if error is not None:
            raise error("synthetic")
        path = urlsplit(url).path
        if path.endswith("trade_day"):
            data = calendar_data()
        elif path.endswith("/list"):
            data = list_data()
        else:
            assert path.endswith("/info")
            data = detail_data()
        return HttpResponse(200, encode(data))

    monkeypatch.setattr(module, "request", request)
    return calls


def test_explicit_workflow_and_no_n_plus_one(monkeypatch):
    calls = install(monkeypatch)
    with ths() as client:
        page = client.get_dragon_tiger_list(trade_date=DAY)
        assert len(calls) == 2
        assert calls[0][1] == calls[1][1]
        params = parse_qs(urlsplit(calls[1][0]).query, keep_blank_values=True)
        assert params["date"] == ["2026-11-05"]
        assert params["module"] == ["all"]
        events = client.get_dragon_tiger_events(entry=page.items[0].ref)
        assert len(calls) == 3
        detail = client.get_dragon_tiger_detail(event=events[0].ref)
        assert len(calls) == 4
        assert detail.ref == events[0].ref
        assert len(detail.reasons) == 2
        assert detail.amount_unit is None
    with pytest.raises(ThsClientClosedError):
        client.get_dragon_tiger_list(trade_date=DAY)
    with pytest.raises(ThsClientClosedError):
        client.get_dragon_tiger_events(entry=page.items[0].ref)
    with pytest.raises(ThsClientClosedError):
        client.get_dragon_tiger_detail(event=events[0].ref)
    assert len(calls) == 4


def test_invalid_references_and_cursor_rejected_before_http(monkeypatch):
    calls = install(monkeypatch)
    client = ths()
    with pytest.raises(ValueError):
        client.get_dragon_tiger_list(
            trade_date=DAY, page=DragonTigerCursor(object(), DAY, 2)
        )
    for ref in (
        DragonTigerEntryRef(object(), "33", "000001", DAY, 1),
        DragonTigerEntryRef(client, "33", "000001&foo", DAY, 1),
        DragonTigerEntryRef(client, "33", "000001", DAY, 2),
    ):
        with pytest.raises(ValueError):
            client.get_dragon_tiger_events(entry=ref)
    assert not calls


@pytest.mark.parametrize(
    "error, attempts", [(ThsNetworkError, 2), (ThsBusinessError, 1)]
)
def test_only_network_error_retries_with_same_deadline(monkeypatch, error, attempts):
    calls = install(monkeypatch, error=error)
    with ths(retries=1) as client, pytest.raises(error):
        client.get_dragon_tiger_list(trade_date=DAY)
    assert len(calls) == attempts
    assert len({call[1] for call in calls}) == 1


def test_calendar_coverage_does_not_infer_nontrading_day(monkeypatch):
    calls = install(monkeypatch)
    with ths() as client, pytest.raises(ValueError, match="calendar"):
        client.get_dragon_tiger_list(trade_date=date(2000, 1, 1))
    assert len(calls) == 1
