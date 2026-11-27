"""本地socket替身；不请求生产服务。"""

import socket
import time

import pytest

from pyths._framing import encode_frame
from pyths._transport import TcpTransport
from pyths.errors import ThsNetworkError, ThsProtocolError


def local_pair():
    listener = socket.socket()
    listener.settimeout(2)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = None
    try:
        client = socket.create_connection(listener.getsockname(), timeout=2)
        server, _ = listener.accept()
        server.settimeout(2)
        return client, server
    except BaseException:
        if client is not None:
            client.close()
        raise
    finally:
        listener.close()


def test_stream_and_complete_send():
    local, peer = local_pair()
    transport = TcpTransport()
    transport._socket = local
    deadline = time.monotonic() + 2
    try:
        peer.sendall(encode_frame(b"first") + encode_frame(b"second"))
        assert transport.receive(deadline=deadline) == b"first"
        assert transport.receive(deadline=deadline) == b"second"
        transport.send(b"request", deadline=deadline)
        peer.settimeout(2)
        assert peer.recv(100) == encode_frame(b"request")
        transport.close()
        transport.close()
        assert peer.recv(1) == b""
    finally:
        transport.close()
        peer.close()


def test_partial_frame_eof_closes_connection():
    local, peer = local_pair()
    transport = TcpTransport()
    transport._socket = local
    peer.sendall(encode_frame(b"payload")[:-1])
    peer.close()
    with pytest.raises(ThsProtocolError):
        transport.receive(deadline=time.monotonic() + 2)
    assert transport._socket is None


def test_timeout_cannot_be_extended():
    local, peer = local_pair()
    transport = TcpTransport()
    transport._socket = local
    try:
        with pytest.raises(ThsNetworkError):
            transport.receive(deadline=time.monotonic() + 0.02)
        assert transport._socket is None
    finally:
        transport.close()
        peer.close()


def test_empty_envelopes_do_not_complete_receive_or_extend_deadline():
    local, peer = local_pair()
    transport = TcpTransport()
    transport._socket = local
    decoder = transport._decoder
    try:
        peer.sendall((b"\xfd" * 4 + b"00000000\x00") * 20)
        with pytest.raises(ThsNetworkError):
            transport.receive(deadline=time.monotonic() + 0.02)
        assert decoder.empty_frame_count == 20
        assert transport._socket is None
    finally:
        transport.close()
        peer.close()


def test_connect_resolves_localhost_and_exchanges_frames():
    listener = socket.socket()
    listener.settimeout(3)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    transport = TcpTransport()
    peer = None
    try:
        deadline = time.monotonic() + 3
        transport.connect(
            ("localhost", listener.getsockname()[1]),
            deadline=deadline,
            connect_timeout=3,
        )
        peer, _ = listener.accept()
        peer.settimeout(3)
        transport.send(b"local request", deadline=deadline)
        assert peer.recv(100) == encode_frame(b"local request")
        peer.sendall(encode_frame(b"local response"))
        assert transport.receive(deadline=deadline) == b"local response"
    finally:
        transport.close()
        if peer is not None:
            peer.close()
        listener.close()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_connect_budget(timeout):
    transport = TcpTransport()
    with pytest.raises(ValueError):
        transport.connect(
            ("127.0.0.1", 1), deadline=time.monotonic() + 1, connect_timeout=timeout
        )
    assert transport._socket is None
