"""公开概览跨真实本机TCP，所有行情及会话均为合成数据。"""

import json
import socket
import struct
import threading

import pytest

from pyths import ThsProtocolError, ths
from pyths._framing import FrameDecoder, encode_frame
from pyths._transform import decode_body
from tests.ranking_fixture import reply
from tests.unit.test_market_breadth import synthetic_response
from tests.unit.test_market_fund import curve as fund_curve
from tests.unit.test_market_initial import initial
from tests.unit.test_market_size import table
from tests.unit.test_market_turnover import curve as turnover_curve


@pytest.mark.parametrize("wrong_instance", [False, True])
def test_public_shared_statistics_tcp_and_release(wrong_instance):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3)
    seen = []
    errors = []

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
                        assert chunk
                        pending.extend(decoder.feed(chunk))
                    return pending.pop(0)

                init = receive()
                assert int.from_bytes(init[6:10], "little") == 0x70000
                handshake = encode_frame(
                    reply(6, b"\x00" * 9, frame=2201)
                ) + encode_frame(
                    reply(11, json.dumps({"sessionId": "synthetic-local"}).encode())
                )
                connection.sendall(handshake[:7])
                connection.sendall(handshake[7:])
                query = receive()
                length = int.from_bytes(query[:2], "little")
                assert int.from_bytes(query[6:10], "little") == 0x40000
                body = decode_body(query[length:]).decode("utf-16-le")
                assert "key=hs_datacenter_ztdt\r\n" in body
                seen.append("single shared request")
                head, payload = synthetic_response(instance=2 if wrong_instance else 1)
                packet = encode_frame(head + payload)
                connection.sendall(packet[:17])
                connection.sendall(packet[17:])
                assert connection.recv(1) == b""
                seen.append("released")
        except (OSError, AssertionError, ThsProtocolError) as error:
            errors.append(type(error).__name__)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        with ths(
            endpoint=listener.getsockname(),
            app_config="synthetic",
            app_info="synthetic",
            request_timeout=3,
        ) as client:
            if wrong_instance:
                with pytest.raises(ThsProtocolError):
                    client.get_market_overview(components=("breadth", "limit_counts"))
            else:
                result = client.get_market_overview(
                    components=("breadth", "limit_counts")
                )
                assert result.breadth.data.rising.raw == "10"
                assert result.limit_counts.data.limit_up.raw == "6"
        worker.join(4)
        assert not worker.is_alive()
        assert not errors
        assert seen == ["single shared request", "released"]
    finally:
        listener.close()


@pytest.mark.parametrize("invalid_size", [False, True])
@pytest.mark.parametrize("uncompressed", [False, True])
def test_full_overview_six_connections_and_partial_failure(invalid_size, uncompressed):
    """Run the public five-component call through handshakes and real loopback I/O."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(6)
    listener.settimeout(4)
    released = []
    errors = []

    def amount(day, values):
        body = bytearray(turnover_curve(day=day, amounts=values))
        start = int.from_bytes(body[18:20], "little")
        for index, hhmm in enumerate((930, 1339)):
            stamp = (
                (126 << 20)
                | (11 << 16)
                | ((day % 100) << 11)
                | ((hhmm // 100) << 6)
                | (hhmm % 100)
            )
            struct.pack_into("<I", body, start + index * 8, stamp)
        return bytes(body)

    def serve():
        try:
            for source in ("statistics", "current", "reference", "sh", "sz", "size"):
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(4)
                    decoder, pending = FrameDecoder(), []

                    def receive(connection, decoder, pending):
                        while not pending:
                            chunk = connection.recv(65536)
                            assert chunk
                            pending.extend(decoder.feed(chunk))
                        return pending.pop(0)

                    init = receive(connection, decoder, pending)
                    assert int.from_bytes(init[6:10], "little") == 0x70000
                    connection.sendall(
                        encode_frame(reply(6, b"\x00" * 9, frame=2201))
                        + encode_frame(
                            reply(11, b'{"sessionId":"synthetic-local-composite"}')
                        )
                    )
                    query = receive(connection, decoder, pending)
                    length = int.from_bytes(query[:2], "little")
                    flags = int.from_bytes(query[6:10], "little")
                    body = decode_body(query[length:]).decode(
                        "utf-16-le" if source == "statistics" else "ascii"
                    )
                    assert flags == (0x40000 if source == "statistics" else 0x01010000)
                    if source == "statistics":
                        assert "key=hs_datacenter_ztdt\r\n" in body
                        head, payload = synthetic_response()
                    elif source in ("current", "reference"):
                        assert "stockcode=883957\r\n" in body
                        if source == "current":
                            assert "id=1229\r\n" in body
                            head, payload = initial(
                                amount(20261103, (100000000, 1550000000)),
                                0x100 if uncompressed else 0x1100,
                                compressed=not uncompressed,
                            )
                        else:
                            assert "id=1271\r\n" in body
                            assert "endtime=20261102\r\n" in body
                            head, payload = initial(
                                amount(20261102, (100000000, 1450000000)),
                                0x1100,
                                frame=2312,
                            )
                    elif source in ("sh", "sz"):
                        assert "id=9001\r\n" in body and "tech=DDE\r\n" in body
                        code = "1A0001" if source == "sh" else "399001"
                        assert f"stockcode={code}\r\n" in body
                        head, payload = initial(
                            fund_curve(kind=source),
                            0x120 if uncompressed else 0x1120,
                            compressed=not uncompressed,
                        )
                    else:
                        assert "id=1264\r\n" in body and "rowcount=2\r\n" in body
                        head, payload = initial(
                            table(codes=("1B0852", "1B0300"))
                            if invalid_size
                            else table(),
                            0x1100,
                        )
                    packet = encode_frame(head + payload)
                    connection.sendall(packet[:19])
                    connection.sendall(packet[19:])
                    assert connection.recv(1) == b""
                    released.append(source)
        except (OSError, AssertionError, ThsProtocolError) as error:
            errors.append(type(error).__name__)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        with ths(
            endpoint=listener.getsockname(),
            app_config="synthetic",
            app_info="synthetic",
            request_timeout=4,
        ) as client:
            result = client.get_market_overview(allow_partial=invalid_size)
        worker.join(5)
        assert not worker.is_alive()
        assert not errors
        assert released == ["statistics", "current", "reference", "sh", "sz", "size"]
        assert result.breadth.data.rising.raw == "10"
        assert result.limit_counts.data.limit_up.raw == "6"
        assert result.turnover.data.comparison.raw == "+1亿"
        assert result.turnover.data.comparison_basis == "上一交易日同刻"
        assert result.fund_flow.data.net.raw == "-3.75亿"
        assert result.size_comparison.status == ("error" if invalid_size else "ok")
        if invalid_size:
            assert result.size_comparison.error.category == "protocol"
        else:
            assert result.size_comparison.data.large.label == "Large"
    finally:
        listener.close()
