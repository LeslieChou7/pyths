"""错误关联应先于解压失败，避免将其他实例响应归入目标。"""

import struct

import pytest

from pyths._response import decode_1269_response
from pyths.errors import ThsProtocolError


@pytest.mark.parametrize("values", [(2, 3, 4), (1, 5, 4), (1, 3, 6)])
def test_association_before_payload(values: tuple[int, int, int]) -> None:
    header = struct.pack("<HiiHiii", 32, 1, 0x1100, 4, 1, 3, 0) + bytes(8)
    with pytest.raises(ThsProtocolError, match="correlation"):
        decode_1269_response(
            header,
            b"x",
            package_id=values[0],
            frame_id=values[1],
            instance_id=values[2],
        )


@pytest.mark.parametrize(
    ("flags", "length", "error"), [(0x3100, 1, "flags"), (0x1100, 2, "length")]
)
def test_flags_and_length(flags: int, length: int, error: str) -> None:
    header = struct.pack("<HiiHiii", 32, 1, flags, 4, length, 3, 0) + bytes(8)
    with pytest.raises(ThsProtocolError, match=error):
        decode_1269_response(header, b"x", package_id=1, frame_id=3, instance_id=4)


def test_zero_frame_is_not_accepted_in_long_header():
    header = struct.pack("<HiiHiii", 32, 1, 0x1100, 4, 1, 0, 0) + bytes(8)
    with pytest.raises(ThsProtocolError, match="correlation"):
        decode_1269_response(
            header,
            b"x",
            package_id=1,
            frame_id=3,
            instance_id=4,
        )


@pytest.mark.parametrize(
    ("header_length", "package", "instance", "allow", "accepted"),
    [
        (26, 1, 4, True, True),
        (26, 1, 4, False, False),
        (32, 1, 4, True, False),
        (26, 2, 4, True, False),
        (26, 1, 5, True, False),
        (26, -1, 4, True, False),
    ],
)
def test_initial_zero_is_explicit_and_scoped(
    header_length, package, instance, allow, accepted
):
    metadata = b"\x00" * 4 + struct.pack("<HHHi", 1, 0xE008, 1, 10)
    body = (
        b"tb1.0\x00"
        + struct.pack("<iIiHHHHBB", 1, 0, 0, 28 + len(metadata), 9, 1, 0, 8, 0)
        + metadata
        + "1.2\x00".encode("utf-16-le")
        + b"\x0a"
    )
    header = struct.pack(
        "<HiiHiii", header_length, package, 0x100, instance, len(body), 0, 0
    )
    header += bytes(header_length - 24)
    if accepted:
        table = decode_1269_response(
            header,
            body,
            package_id=1,
            frame_id=2267,
            instance_id=4,
            allow_initial_frame_zero=allow,
        )
        assert table.cells == ((10, "1.2", 10),)
    else:
        with pytest.raises(ThsProtocolError, match="correlation"):
            decode_1269_response(
                header,
                body,
                package_id=1,
                frame_id=2267,
                instance_id=4,
                allow_initial_frame_zero=allow,
            )
