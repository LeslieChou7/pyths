"""合成本地TCP/HTTP交错；不证明服务端兼容或真实指标口径。"""

import json
import socket
import threading

import pytest

from pyths import ThsClientClosedError, ThsProtocolError, ThsRateLimitError, _hot, ths
from pyths._framing import FrameDecoder, encode_frame
from pyths._http import request as http_request
from pyths._transform import decode_body
from tests.hot_fixture import payload
from tests.integration.test_http import server
from tests.integration.test_quote_tcp import quote_response, response
from tests.unit.test_dragon_client import DAY
from tests.unit.test_dragon_client import install as install_dragon
from tests.unit.test_ranking_client import install as install_ranking


@pytest.mark.parametrize("http_failure", [False, True])
def test_http_and_ranking_leave_quote_session_and_residuals_isolated(
    monkeypatch, http_failure
):
    listener = socket.socket()
    listener.settimeout(5)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    errors = []
    packets = []

    def serve_quotes():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                decoder = FrameDecoder()
                pending = []

                def receive():
                    while not pending:
                        chunk = connection.recv(65536)
                        assert chunk
                        pending.extend(decoder.feed(chunk))
                    return pending.pop(0)

                init = receive()
                assert int.from_bytes(init[6:10], "little") == 0x70000
                connection.sendall(
                    encode_frame(response(6, b"\x00" * 9, frame=2201))
                    + encode_frame(
                        response(11, json.dumps({"sessionId": "synthetic"}).encode())
                    )
                )
                for iteration in range(2):
                    packet = receive()
                    package = int.from_bytes(packet[2:6], "little")
                    size = int.from_bytes(packet[:2], "little")
                    body = decode_body(packet[size:]).decode("ascii")
                    instance = int(body.split("pageList=")[1].split("\r\n")[0])
                    packets.append(package)
                    connection.sendall(
                        encode_frame(
                            quote_response(
                                package=package,
                                instance=instance,
                                latest=f"11.{64 + iteration}",
                            )
                        )
                    )
                    stop = receive()
                    packets.append(int.from_bytes(stop[2:6], "little"))
                    if iteration == 0:
                        connection.sendall(
                            encode_frame(
                                quote_response(package=-1, instance=1, latest="99.99")
                            )
                        )
                assert connection.recv(1) == b""
        except (OSError, AssertionError, ThsProtocolError) as error:
            errors.append(error)

    worker = threading.Thread(target=serve_quotes, daemon=True)
    worker.start()
    ranking_calls = install_ranking(monkeypatch)
    dragon_calls = install_dragon(monkeypatch)
    try:
        with server(status=429 if http_failure else 200, body=payload()) as (url, seen):
            monkeypatch.setattr(
                _hot, "request", lambda target, **kwargs: http_request(url, **kwargs)
            )
            with ths(
                endpoint=listener.getsockname(),
                app_config="synthetic",
                app_info="synthetic",
                request_timeout=4,
            ) as client:
                assert client.get_quote("000001", market="33").latest.display == "11.64"
                session = client._session
                first = client.get_stock_ranking()
                if http_failure:
                    with pytest.raises(ThsRateLimitError):
                        client.get_hot_ranking(board="stock_hour")
                else:
                    assert client.get_hot_ranking(board="stock_hour").items
                page = client.get_dragon_tiger_list(trade_date=DAY)
                events = client.get_dragon_tiger_events(entry=page.items[0].ref)
                client.get_dragon_tiger_detail(event=events[0].ref)
                client.get_stock_ranking(page=first.next_page)
                assert client._session is session
                assert client.get_quote("000001", market="33").latest.display == "11.65"
            before = (len(seen), len(ranking_calls), len(dragon_calls))
            for query in (
                client.get_stock_ranking,
                lambda: client.get_hot_ranking(board="stock_hour"),
                lambda: client.get_dragon_tiger_list(trade_date=DAY),
            ):
                with pytest.raises(ThsClientClosedError):
                    query()
            assert before == (len(seen), len(ranking_calls), len(dragon_calls))
            assert len(seen) == 1
    finally:
        worker.join(6)
        listener.close()
    assert not worker.is_alive()
    assert not errors
    assert packets == [1, 2, 3, 4]
