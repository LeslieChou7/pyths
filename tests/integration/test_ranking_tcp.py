"""Real loopback TCP; synthetic payloads and no external services."""

import json
import socket
import threading

import pytest

from pyths import ThsProtocolError, ths
from pyths._framing import FrameDecoder, encode_frame
from pyths._transform import decode_body
from tests.ranking_fixture import reply, table


@pytest.mark.parametrize("wrong_instance", [False, True])
def test_ranking_over_local_tcp(wrong_instance):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(3)
    errors = []
    starts = []
    closed = []

    def serve():
        try:
            for _ in range(1 if wrong_instance else 2):
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(3)
                    decoder = FrameDecoder()
                    pending = []

                    def receive(
                        connection=connection, decoder=decoder, pending=pending
                    ):
                        while not pending:
                            chunk = connection.recv(65536)
                            assert chunk
                            pending.extend(decoder.feed(chunk))
                        return pending.pop(0)

                    init = receive()
                    assert int.from_bytes(init[6:10], "little") == 0x70000
                    handshake = encode_frame(
                        reply(6, b"\x00" * 9, frame=2201)
                    ) + encode_frame(
                        reply(11, json.dumps({"sessionId": "local"}).encode())
                    )
                    connection.sendall(handshake[:7])
                    connection.sendall(handshake[7:])
                    query = receive()
                    length = int.from_bytes(query[:2], "little")
                    body = decode_body(query[length:]).decode()
                    start = int(body.split("startrow=")[1].split("\r\n")[0])
                    starts.append(start)
                    packet = encode_frame(
                        reply(
                            0x1130,
                            table(start),
                            package=1,
                            instance=2 if wrong_instance else 1,
                        )
                    )
                    connection.sendall(packet[:19])
                    connection.sendall(packet[19:])
                    closed.append(connection.recv(1) == b"")
        except (OSError, AssertionError, ThsProtocolError) as error:
            errors.append(error)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with ths(
            endpoint=listener.getsockname(),
            app_config="synthetic",
            app_info="synthetic",
            request_timeout=3,
        ) as client:
            if wrong_instance:
                with pytest.raises(ThsProtocolError):
                    client.get_stock_ranking()
            else:
                first = client.get_stock_ranking()
                second = client.get_stock_ranking(page=first.next_page)
                assert first.items[0].stock_code == "000001"
                assert second.next_page is None
        thread.join(4)
        assert not thread.is_alive()
        assert not errors
        assert all(closed)
        assert starts == ([0] if wrong_instance else [0, 1])
    finally:
        listener.close()
