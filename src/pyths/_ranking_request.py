"""Observed 1282 text body; wire/session setup is validated separately."""

from ._headers import encode_request_header
from ._ranking_capabilities import RankingCapability, capability
from ._transform import checksum_context, transform_request
from .errors import ThsProtocolError


def encode_ranking_request(
    *,
    package_id: int,
    instance_id: int,
    start: int,
    sort: str,
    direction: str,
    app_info: str,
    session_id: str,
    state_word: int = 0,
    trace_id: str | None = None,
) -> bytes:
    """Compose observed common framing; standalone server acceptance is separate."""
    body = encode_ranking_body(
        instance_id=instance_id, start=start, sort=sort, direction=direction
    )
    return _encode_ranking_packet(
        body=body,
        package_id=package_id,
        app_info=app_info,
        session_id=session_id,
        state_word=state_word,
        trace_id=trace_id,
    )


def _encode_ranking_packet(
    *,
    body: bytes,
    package_id: int,
    app_info: str,
    session_id: str,
    state_word: int = 0,
    trace_id: str | None = None,
) -> bytes:
    """共同应用头与映射；业务调用方仅传入各自已校验的正文。"""
    header = encode_request_header(
        package_id=package_id,
        flags=0x01010000,
        instance_marker=-253,
        data_length=0,
        frame_id=2312,
        text_length=len(body),
        state_word=state_word,
        extension_word=0,
        extension_short=0,
        trace_id=trace_id,
    )
    prefix, suffix = checksum_context(app_info=app_info, session=session_id)
    return transform_request(
        header + body, checksum_prefix=prefix, session_suffix=suffix
    )


def encode_ranking_body(
    *,
    instance_id: int,
    start: int,
    sort: str,
    direction: str,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """Encode the fixed marketId0/24-row profile without raw parameter input."""
    selected = capability(sort, direction)
    return _encode_ranking_body(
        selected=selected,
        instance_id=instance_id,
        start=start,
        active_instances=active_instances,
    )


def _encode_ranking_body(
    *,
    selected: RankingCapability,
    instance_id: int,
    start: int,
    active_instances: tuple[int, ...] | None = None,
) -> bytes:
    """共享已观察正文布局；调用层负责能力及语义门槛。"""
    if type(start) is not int or not 0 <= start <= 9999999:
        raise ValueError("invalid ranking offset")
    instances = (instance_id,) if active_instances is None else active_instances
    if (
        not instances
        or len(instances) > 32
        or instance_id not in instances
        or len(set(instances)) != len(instances)
    ):
        raise ThsProtocolError("ranking: invalid active instances")
    for value in (*instances, instance_id):
        if type(value) is not int or not 1 <= value <= 65535:
            raise ThsProtocolError("ranking: invalid instance")
    sort_id, order = selected.sort_id, selected.order
    pages = ",".join(str(value) for value in instances)
    return (
        f"[frame]\r\nid=2312\r\npageList={pages}\r\n"
        f"reqPage={instance_id}\r\nreqPageCount=1\r\n[{instance_id}]\r\n"
        f"id=1282\r\nstartrow={start}\r\nrowcount=24\r\nmarketId=0\r\n"
        f"sortorder={order}\r\nsortid={sort_id}\r\n"
    ).encode("ascii")
