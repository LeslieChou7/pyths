"""Strict wire response path observed for frame2312/page1282."""

from ._compression import decode_snappy
from ._headers import decode_response_header
from ._tb3 import Cell, metadata, parse
from .errors import ThsProtocolError


def decode_ranking_response(
    header_bytes: bytes,
    payload: bytes,
    *,
    package_id: int,
    instance_id: int,
    start: int,
    allow_initial_frame_zero: bool = False,
) -> tuple[tuple[dict[int, Cell], ...], dict[int, str | int]]:
    """Validate independent header and page origin before returning row cells."""
    header = decode_response_header(header_bytes)
    initial = (
        allow_initial_frame_zero
        and package_id > 0
        and header.length == 26
        and header.frame_id == 0
        and header.extension == b"\x00\xff"
    )
    normal = (header.length == 32 and header.extension[:4] == b"\x00" * 4) or (
        header.length == 26
        and header.extension == b"\x00\xff"
        and header.frame_id == 2312
    )
    if len(header_bytes) != header.length or not (initial or normal):
        raise ThsProtocolError("ranking: unsupported header layout")
    if (header.package_id, header.instance_id) != (package_id, instance_id) or (
        header.frame_id != 2312 and not initial
    ):
        raise ThsProtocolError("ranking: correlation mismatch")
    if header.flags != 0x1130 or header.payload_length != len(payload):
        raise ThsProtocolError("ranking: invalid flags or payload length")
    body = decode_snappy(payload, max_output=8 * 1024 * 1024)
    fields = metadata(body)
    if fields.get(34055) != start:
        raise ThsProtocolError("ranking: page origin mismatch")
    total = fields.get(34056)
    if total is not None and (type(total) is not int or total < 0):
        raise ThsProtocolError("ranking: invalid total")
    rows = parse(body)
    if len(rows) > 24 or (isinstance(total, int) and start + len(rows) > total):
        raise ThsProtocolError("ranking: invalid page bounds")
    return rows, fields
