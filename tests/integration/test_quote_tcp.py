"""明确合成的本地协议替身，不证明生产兼容。"""

import json
import socket
import struct
import threading

import pytest

from pyths import ThsAuthenticationError, ThsNetworkError, ThsProtocolError, ths
from pyths._framing import FrameDecoder, encode_frame
from pyths._transform import decode_body


def response(flags, body, *, package=0, frame=0, instance=0):
    return (
        struct.pack("<HiiHiiiH", 26, package, flags, instance, len(body), frame, 0, 0)
        + body
    )


def quote_response(
    *,
    wrong_id=False,
    plain=False,
    omitted_frame=False,
    wrong_frame=False,
    package=1,
    instance=1,
    stock_code="000001",
    market="33",
    latest="11.64",
):
    metadata = b"\x00" * 4 + struct.pack("<HHHiii", 1, 0xE008, 3, 4, 36103, 10)
    table = (
        b"tb1.0\x00"
        + struct.pack("<iIiHHHHBB", 3, 0, 0, 28 + len(metadata), 17, 1, 0, 16, 0)
        + metadata
    )
    for text in (stock_code, market, latest):
        table += text.encode("utf-16-le").ljust(16, b"\x00") + b"\x00"
    assert len(table) == 101
    # 独立构造Snappy长度varint和扩展literal tag，非SDK编码往返。
    compressed = b"\x65\xf0\x64" + table
    return response(
        0x100 if plain else 0x1100,
        table if plain else compressed,
        package=2 if wrong_id else package,
        frame=0 if omitted_frame else (7 if wrong_frame else 2267),
        instance=instance,
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "plain",
        "omitted_frame",
        "wrong_frame",
        "wrong_id",
        "auth_rejected",
        "wrong_instance",
        "wrong_security",
        "current_update",
    ],
)
def test_public_api_over_local_tcp(scenario):
    listener = socket.socket()
    listener.settimeout(3)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    errors = []
    observed = []

    def serve():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(3)
                decoder = FrameDecoder()
                pending = []

                def receive():
                    while not pending:
                        chunk = connection.recv(65536)
                        if not chunk:
                            raise AssertionError("unexpected client EOF")
                        pending.extend(decoder.feed(chunk))
                    return pending.pop(0)

                init = receive()
                assert int.from_bytes(init[6:10], "little") == 0x70000
                frame_id = 999 if scenario == "auth_rejected" else 2201
                connection.sendall(
                    encode_frame(response(6, b"\x00" * 9, frame=frame_id))
                )
                if scenario == "auth_rejected":
                    assert connection.recv(1) == b""
                    return
                connection.sendall(
                    encode_frame(
                        response(
                            11,
                            json.dumps(
                                {"sessionId": "synthetic-local-session"}
                            ).encode(),
                        )
                    )
                )
                request = receive()
                size = int.from_bytes(request[:2], "little")
                observed.append(decode_body(request[size:]))
                connection.sendall(
                    encode_frame(
                        quote_response(
                            wrong_id=scenario == "wrong_id",
                            plain=scenario == "plain",
                            omitted_frame=scenario
                            in (
                                "omitted_frame",
                                "wrong_security",
                                "wrong_id",
                                "wrong_instance",
                            ),
                            wrong_frame=scenario == "wrong_frame",
                            instance=2 if scenario == "wrong_instance" else 1,
                            stock_code="000002"
                            if scenario == "wrong_security"
                            else "000001",
                            package=-1 if scenario == "current_update" else 1,
                        )
                    )
                )
                if scenario in ("success", "plain", "omitted_frame"):
                    stop = receive()
                    assert int.from_bytes(stop[2:6], "little") == 2
                    assert int.from_bytes(stop[6:10], "little") == 0x1060000
                    size = int.from_bytes(stop[:2], "little")
                    assert (
                        decode_body(stop[size:])
                        == b"[frame]\r\nid=2267\r\npageList=\r\n"
                    )
                assert connection.recv(1) == b""
        except (OSError, AssertionError, ThsProtocolError) as error:
            errors.append(error)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        with ths(
            endpoint=listener.getsockname(),
            app_config="synthetic",
            app_info="synthetic",
            request_timeout=3,
        ) as client:
            if scenario in ("success", "plain", "omitted_frame"):
                quote = client.get_quote("000001", market="33")
                assert quote.stock_code == "000001"
                assert quote.latest.display == "11.64"
                assert quote.turnover is None
                assert quote.received_at.utcoffset().total_seconds() == 0
            else:
                error = (
                    ThsAuthenticationError
                    if scenario == "auth_rejected"
                    else ThsProtocolError
                )
                with pytest.raises(error):
                    client.get_quote("000001", market="33")
        if scenario != "auth_rejected":
            assert b"stockcode=000001\r\nmarketcode=33\r\n" in observed[0]
    finally:
        worker.join(4)
        listener.close()
    assert not worker.is_alive()
    assert not errors


@pytest.mark.parametrize(
    ("disconnect", "residual", "rollover"),
    [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (False, False, True),
    ],
)
def test_repeated_queries_and_idle_disconnect_recovery(disconnect, residual, rollover):
    """真实本地TCP：同会话递增关联；断连后的下一次显式调用重建会话。"""
    listener = socket.socket()
    listener.settimeout(3)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    peer_closed = threading.Event()
    errors, observed, sessions, stops = [], [], [], []

    def serve():
        try:
            for number in range(2 if disconnect or rollover else 1):
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(3)
                    decoder, pending = FrameDecoder(), []

                    def receive(
                        connection=connection, decoder=decoder, pending=pending
                    ):
                        while not pending:
                            chunk = connection.recv(65536)
                            assert chunk, "unexpected EOF"
                            pending.extend(decoder.feed(chunk))
                        return pending.pop(0)

                    init = receive()
                    assert int.from_bytes(init[6:10], "little") == 0x70000
                    sessions.append(number)
                    connection.sendall(
                        encode_frame(response(6, b"\x00" * 9, frame=2201))
                        + encode_frame(
                            response(
                                11,
                                json.dumps(
                                    {"sessionId": f"synthetic-session-{number}"}
                                ).encode(),
                            )
                        )
                    )
                    for iteration in range(1 if disconnect or rollover else 3):
                        request = receive()
                        package = int.from_bytes(request[2:6], "little", signed=True)
                        size = int.from_bytes(request[:2], "little")
                        body = decode_body(request[size:]).decode("ascii")
                        instance = int(
                            body.split("pageList=", 1)[1].split("\r\n", 1)[0]
                        )
                        observed.append((package, instance))
                        connection.sendall(
                            encode_frame(
                                quote_response(
                                    package=package,
                                    instance=instance,
                                    omitted_frame=True,
                                    latest=f"11.{64 + iteration}",
                                )
                            )
                        )
                        stop = receive()
                        stop_id = int.from_bytes(stop[2:6], "little")
                        assert stop_id == package + 1
                        assert int.from_bytes(stop[6:10], "little") == 0x1060000
                        size = int.from_bytes(stop[:2], "little")
                        assert (
                            decode_body(stop[size:])
                            == b"[frame]\r\nid=2267\r\npageList=\r\n"
                        )
                        stops.append(stop_id)
                        if residual and iteration == 0:
                            connection.sendall(
                                encode_frame(
                                    quote_response(
                                        package=-1, instance=1, latest="99.99"
                                    )
                                )
                            )
                    if disconnect and number == 0:
                        # 留下旧连接控制帧；EOF后不得污染下一连接。
                        connection.sendall(encode_frame(response(11, b"{}")))
                    else:
                        assert connection.recv(1) == b""
                peer_closed.set()
        except (OSError, AssertionError, ThsProtocolError) as error:
            errors.append(error)
            peer_closed.set()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        with ths(
            endpoint=listener.getsockname(),
            app_config="synthetic",
            app_info="synthetic",
            request_timeout=3,
        ) as client:
            assert client.get_quote("000001", market="33").latest.display == "11.64"
            original = client._session
            if disconnect:
                assert peer_closed.wait(3)
                with pytest.raises(ThsNetworkError):
                    client.get_quote("000001", market="33")
                assert client._session is None
                assert not client._transport._pending
                assert client.get_quote("000001", market="33").latest.display == "11.64"
                assert client._session is not original
                assert client._session.session_id == "synthetic-session-1"
            elif rollover:
                client._counter = 32766
                assert client.get_quote("000001", market="33").latest.display == "11.64"
                assert client._session is not original
                assert client._session.session_id == "synthetic-session-1"
                assert set(client._completed) == {1}
            else:
                for iteration in range(2):
                    assert (
                        client.get_quote("000001", market="33").latest.display
                        == f"11.{65 + iteration}"
                    )
                    assert client._session is original
    finally:
        worker.join(4)
        listener.close()
    assert not worker.is_alive()
    assert not errors
    assert sessions == ([0, 1] if disconnect or rollover else [0])
    assert observed == (
        [(1, 1), (1, 1)] if disconnect or rollover else [(1, 1), (3, 3), (5, 5)]
    )
    assert stops == ([2, 2] if disconnect or rollover else [2, 4, 6])
