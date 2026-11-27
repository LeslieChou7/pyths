"""Cross-layer public calls with synthetic transport, never production traffic."""

import importlib
import json
import struct

import pytest

from pyths import RankingCursor, ThsClientClosedError, ThsNetworkError, ths
from pyths._transform import decode_body
from tests.ranking_fixture import reply, table


def install(monkeypatch, *, failures=0):
    calls = []
    module = importlib.import_module("pyths._ranking_query")

    class Transport:
        def __init__(self):
            self.closed = False
            self.responses = []
            self.start = 0

        def connect(self, endpoint, *, deadline, connect_timeout):
            calls.append(("connect", deadline))

        def send(self, packet, *, deadline):
            flags = int.from_bytes(packet[6:10], "little")
            calls.append(("send", flags, deadline))
            if flags == 0x70000:
                self.responses = [
                    reply(6, b"\x00" * 9, frame=2201),
                    reply(11, json.dumps({"sessionId": "synthetic"}).encode()),
                ]
            else:
                length = int.from_bytes(packet[:2], "little")
                body = decode_body(packet[length:]).decode()
                self.start = int(body.split("startrow=")[1].split("\r\n")[0])
                calls.append(("start", self.start))
                payload = table(self.start)
                selected_id = int(body.split("sortid=")[1].split("\r\n")[0])
                if selected_id in (48, 34370, 34391):
                    payload = payload.replace(
                        struct.pack("<HBB", 4096 | 34818, 4, 0),
                        struct.pack("<HBB", 4096 | selected_id, 4, 0),
                    )
                self.responses = [reply(0x1130, payload, package=1, instance=1)]

        def receive(self, *, deadline):
            nonlocal failures
            if failures:
                failures -= 1
                raise ThsNetworkError("synthetic")
            return self.responses.pop(0)

        def close(self):
            if not self.closed:
                calls.append(("close",))
                self.closed = True

    monkeypatch.setattr(module, "TcpTransport", Transport)
    return calls


def client(**kwargs):
    return ths(
        endpoint=("127.0.0.1", 1),
        app_info="synthetic",
        app_config="synthetic",
        **kwargs,
    )


def test_public_mapping_cursor_and_release(monkeypatch):
    calls = install(monkeypatch)
    with client() as c:
        first = c.get_stock_ranking()
        assert first.items[0].stock_code == "000001"
        assert first.items[0].name == "Test"
        assert first.items[0].change_rate.display == "0.01%"
        assert first.items[0].rank is None
        assert first.received_at.tzinfo is not None
        second = c.get_stock_ranking(page=first.next_page)
        assert second.has_more is False and second.next_page is None
        assert [v[1] for v in calls if v[0] == "start"] == [0, 1]
        for cursor in [
            RankingCursor(object(), "change_rate", "desc", 1),
            RankingCursor(c, "turnover", "desc", 1),
        ]:
            before = len(calls)
            with pytest.raises(ValueError):
                c.get_stock_ranking(page=cursor)
            assert len(calls) == before
    assert sum(v[0] == "close" for v in calls) == 2
    with pytest.raises(ThsClientClosedError):
        c.get_stock_ranking()


@pytest.mark.parametrize("retries", [0, 1])
def test_retry_shares_deadline_and_releases(monkeypatch, retries):
    calls = install(monkeypatch, failures=2)
    with client(retries=retries) as c, pytest.raises(ThsNetworkError):
        c.get_stock_ranking()
    assert len({v[1] for v in calls if v[0] == "connect"}) == 1
    assert sum(v[0] == "connect" for v in calls) == retries + 1
    assert sum(v[0] == "close" for v in calls) == retries + 1


def test_invalid_combo_never_connects(monkeypatch):
    calls = install(monkeypatch)
    with client() as c, pytest.raises(ValueError):
        c.get_stock_ranking(sort="turnover", direction="asc")
    assert calls == []


def test_rapid_public_paging_metadata_and_cursor_isolation(monkeypatch):
    calls = install(monkeypatch)
    with client() as c:
        first = c.get_stock_ranking(sort="rapid_change_rate")
        assert first.scope == "m10_rapid"
        assert first.window_minutes == 5
        assert first.window_source == "user_confirmed"
        assert first.source_time is None
        assert first.items[0].rapid_change_rate.display == "0.01%"
        assert first.items[0].rapid_change_rate.unit == "%"
        assert first.items[0].change_rate is None
        before = len(calls)
        with pytest.raises(ValueError, match="cursor"):
            c.get_stock_ranking(page=first.next_page)
        with pytest.raises(ValueError, match="unsupported"):
            c.get_stock_ranking(sort="rapid_change_rate", direction="asc")
        assert len(calls) == before
        last = c.get_stock_ranking(sort="rapid_change_rate", page=first.next_page)
        assert last.has_more is False and last.next_page is None
        assert [x[1] for x in calls if x[0] == "start"] == [0, 1]
    assert sum(x[0] == "close" for x in calls) == 2


@pytest.mark.parametrize(
    "sort,profile",
    [("large_order_net_volume", "m10_large"), ("main_net_inflow", "m10_main")],
)
def test_fund_public_cursor_release_and_provenance(monkeypatch, sort, profile):
    calls = install(monkeypatch)
    with client() as c:
        page = c.get_stock_ranking(sort=sort)
        assert page.scope == profile
        assert page.definition_source == "user_adopted_official"
        assert page.definition_url.startswith("https://")
        assert getattr(page.items[0], sort).raw == "0.01"
        assert page.window_minutes is None
        before = len(calls)
        with pytest.raises(ValueError, match="cursor"):
            c.get_stock_ranking(sort="rapid_change_rate", page=page.next_page)
        with pytest.raises(ValueError, match="unsupported"):
            c.get_stock_ranking(sort=sort, direction="asc")
        assert len(calls) == before
        last = c.get_stock_ranking(sort=sort, page=page.next_page)
        assert last.has_more is False
    assert sum(x[0] == "close" for x in calls) == 2
