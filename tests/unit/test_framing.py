"""合成封装仅验证本地分帧，不证明真实线上兼容。"""

import pytest

from pyths._framing import FrameDecoder, encode_frame
from pyths.errors import ThsProtocolError


def test_split_and_merged_frames() -> None:
    wire = b"\xfd\xfd\xfd\xfd00000003\x00abc\xfd\xfd\xfd\xfd00000001\x00z"
    for split in range(len(wire) + 1):
        decoder = FrameDecoder()
        assert decoder.feed(wire[:split]) + decoder.feed(wire[split:]) == (b"abc", b"z")
        decoder.finish()
    decoder = FrameDecoder()
    result = ()
    for value in wire:
        result += decoder.feed(bytes([value]))
    assert result == (b"abc", b"z")
    decoder.finish()


@pytest.mark.parametrize(
    "header",
    [
        b"xxxx00000001\x00",
        b"\xfd" * 4 + b"0000000z\x00",
        b"\xfd" * 4 + b"00000001x",
        b"\xfd" * 4 + b"00000004\x00",
    ],
)
def test_bad_header_and_limit(header: bytes) -> None:
    decoder = FrameDecoder(max_frame_size=3)
    with pytest.raises(ThsProtocolError):
        decoder.feed(header)
    with pytest.raises(ThsProtocolError):
        decoder.feed(b"x")


def test_truncated_stream() -> None:
    wire = b"\xfd\xfd\xfd\xfd00000003\x00abc"
    for end in range(1, len(wire)):
        decoder = FrameDecoder()
        decoder.feed(wire[:end])
        with pytest.raises(ThsProtocolError):
            decoder.finish()


def test_encode_frame_expected_bytes() -> None:
    assert encode_frame(b"abc") == b"\xfd\xfd\xfd\xfd00000003\x00abc"
    for payload in (b"", b"abcd"):
        with pytest.raises(ThsProtocolError):
            encode_frame(payload, max_frame_size=3)


def test_empty_envelopes_are_consumed_across_every_split():
    empty = b"\xfd" * 4 + b"00000000\x00"
    wire = empty + encode_frame(b"abc") + empty + encode_frame(b"z")
    for split in range(len(wire) + 1):
        decoder = FrameDecoder()
        assert decoder.feed(wire[:split]) + decoder.feed(wire[split:]) == (b"abc", b"z")
        assert decoder.empty_frame_count == 2
        decoder.finish()
    decoder = FrameDecoder()
    assert decoder.feed(empty * 3) == ()
    assert decoder.empty_frame_count == 3
    decoder.finish()
