import importlib
import time

import pytest

from pyths import ThsNetworkError, ths
from pyths._session import SessionContext


@pytest.mark.parametrize("retries", [0, 1])
def test_network_retry_is_bounded_rebuilds_session_and_keeps_deadline(
    monkeypatch, retries
):
    module = importlib.import_module("pyths.client")
    connections = []
    handshakes = []
    sends = []
    closes = []

    class Transport:
        def connect(self, endpoint, *, deadline, connect_timeout):
            connections.append(deadline)

        def send(self, packet, *, deadline):
            sends.append((int.from_bytes(packet[2:6], "little"), deadline))

        def receive(self, *, deadline):
            raise ThsNetworkError("synthetic disconnect")

        def close(self):
            closes.append(True)

    def establish(transport, packet, *, deadline):
        handshakes.append(deadline)
        return SessionContext("synthetic")

    monkeypatch.setattr(module, "TcpTransport", Transport)
    monkeypatch.setattr(module, "establish_session", establish)
    with ths(
        endpoint=("127.0.0.1", 1),
        app_config="synthetic",
        app_info="synthetic",
        retries=retries,
    ) as client:
        with pytest.raises(ThsNetworkError):
            client.get_quote("000001", market="33")
        assert client._session is None
    assert len(connections) == len(handshakes) == len(sends) == retries + 1
    assert len(set(connections + handshakes + [item[1] for item in sends])) == 1
    assert [item[0] for item in sends] == [1] * (retries + 1)
    assert len(closes) >= retries + 1
    assert connections[0] > time.monotonic()
