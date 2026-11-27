import json
import struct
import time

import pytest

from pyths._session import establish_session
from pyths._transport import TcpTransport
from pyths.errors import ThsAuthenticationError, ThsProtocolError


def frame(flags, body, frame_id=0):
    return struct.pack("<HiiHiiiH", 26, 0, flags, 0, len(body), frame_id, 0, 0) + body


class MemoryTransport(TcpTransport):
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []
        self.was_closed = False

    def send(self, packet, *, deadline):
        self.sent.append(packet)

    def receive(self, *, deadline):
        return next(self.frames)

    def close(self):
        self.was_closed = True


@pytest.mark.parametrize("reverse", [False, True])
def test_session_requires_both_success_and_identifier(reverse):
    frames = [
        frame(6, b"\x00" * 9, 2201),
        frame(11, json.dumps({"sessionId": "private-sentinel"}).encode()),
    ]
    if reverse:
        frames.reverse()
    transport = MemoryTransport(frames)
    context = establish_session(
        transport, b"synthetic request", deadline=time.monotonic() + 1
    )
    assert context.session_id == "private-sentinel"
    assert "private-sentinel" not in repr(context)
    assert transport.sent == [b"synthetic request"]
    assert not transport.was_closed


def test_rejected_initialization_closes_without_retry():
    transport = MemoryTransport([frame(6, b"\x00" * 9, 999)])
    with pytest.raises(ThsAuthenticationError):
        establish_session(transport, b"request", deadline=time.monotonic() + 1)
    assert transport.was_closed
    assert len(transport.sent) == 1


def test_unrelated_frames_have_count_bound():
    transport = MemoryTransport([frame(11, b"{}") for _ in range(20)])
    with pytest.raises(ThsProtocolError, match="count limit"):
        establish_session(transport, b"request", deadline=time.monotonic() + 1)
    assert transport.was_closed
