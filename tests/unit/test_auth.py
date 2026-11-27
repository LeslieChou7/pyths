"""合成布局预期，不证明服务端接受启动请求。"""

import pytest

from pyths._auth import encode_session_body, make_session_trace
from pyths.errors import ThsProtocolError


def test_session_body_independent_bytes():
    assert encode_session_body(config="A", passport=b"xy", risk_parameters="中") == (
        b"\x01\x00A\x00\x02\x00xy\x02\x00\xd6\xd0"
    )


def test_java_utf16_length_and_absent_optional_field():
    assert encode_session_body(config="😀", passport=b"") == (
        b"\x02\x00\x3d\xd8\x00\xde\x00\x00"
    )
    assert encode_session_body(config="", passport=b"") == b"\x00" * 4


def test_unsupported_encoding_does_not_expose_material():
    with pytest.raises(ThsProtocolError, match="unsupported text encoding"):
        encode_session_body(config="", passport=b"", risk_parameters="😀")


def test_field_bounds():
    with pytest.raises(ThsProtocolError, match="field length"):
        encode_session_body(config="", passport=b"x" * 32768)


def test_trace_layout(monkeypatch):
    import uuid

    monkeypatch.setattr("pyths._auth.time.time_ns", lambda: 1_700_000_000_123_000_000)
    monkeypatch.setattr(
        "pyths._auth.uuid.uuid4",
        lambda: uuid.UUID("01234567-89ab-4def-8123-456789abcdef"),
    )
    assert make_session_trace() == "3002457817000000001230123456789a"


def test_complete_session_request_has_independent_layout(monkeypatch):
    from pyths._auth import encode_session_request
    from pyths._transform import decode_body

    monkeypatch.setattr("pyths._auth.make_session_trace", lambda: "0" * 32)
    packet = encode_session_request(config="A", app_info="synthetic", passport=b"")
    assert packet[:12] == b"\x4c\x00\x00\x00\x00\x00\x00\x00\x07\x00\x03\xff"
    assert packet[16:28] == b"\x00" * 12
    assert packet[34:36] == b"\x28\x00"
    assert packet[36:76] == b"traceid=" + b"0" * 32
    assert decode_body(packet[76:]) == b"\x01\x00A\x00\x00\x00"


def test_session_reply_prefix_and_private_repr():
    from pyths._auth import decode_session_reply

    data = b"\x80\x07\x00\x02\x00xy\x03\x00foo\x02\x00A\x00\x2d\x4etail"
    reply = decode_session_reply(data)
    assert reply.status == 128
    assert reply.random_value == 7
    assert reply.passport == b"xy"
    assert reply.user_info == "foo"
    assert reply.message == "A中"
    assert reply.tail == b"tail"
    assert "foo" not in repr(reply)
    assert "xy" not in repr(reply)
    for end in range(16):
        with pytest.raises(ThsProtocolError):
            decode_session_reply(data[:end])
