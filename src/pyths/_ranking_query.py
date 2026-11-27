"""Bounded independent connection for a single ranking page."""

from datetime import UTC, datetime

from ._auth import encode_session_request
from ._headers import decode_response_header
from ._ranking import ranking_page
from ._ranking_request import encode_ranking_request
from ._ranking_response import decode_ranking_response
from ._session import establish_session
from ._transport import TcpTransport
from .errors import ThsNetworkError, ThsProtocolError
from .models import StockRankingPage


def query_page(
    *,
    endpoint: tuple[str, int],
    app_config: str,
    app_info: str,
    connect_timeout: float,
    deadline: float,
    retries: int,
    owner: object,
    start: int,
    sort: str,
    direction: str,
) -> StockRankingPage:
    for attempt in range(retries + 1):
        transport = TcpTransport()
        try:
            transport.connect(
                endpoint, deadline=deadline, connect_timeout=connect_timeout
            )
            init = encode_session_request(
                config=app_config, app_info=app_info, passport=b""
            )
            session = establish_session(transport, init, deadline=deadline)
            packet = encode_ranking_request(
                package_id=1,
                instance_id=1,
                start=start,
                sort=sort,
                direction=direction,
                app_info=app_info,
                session_id=session.session_id,
            )
            transport.send(packet, deadline=deadline)
            for _ in range(20):
                frame = transport.receive(deadline=deadline)
                received = datetime.now(UTC)
                header = decode_response_header(frame)
                if header.payload_length != len(frame) - header.length:
                    raise ThsProtocolError("ranking: payload length mismatch")
                if header.flags in (11, 65547):
                    continue
                rows, fields = decode_ranking_response(
                    frame[: header.length],
                    frame[header.length :],
                    package_id=1,
                    instance_id=1,
                    start=start,
                    allow_initial_frame_zero=True,
                )
                return ranking_page(
                    rows,
                    fields,
                    owner=owner,
                    start=start,
                    sort=sort,
                    direction=direction,
                    received_at=received,
                )
            raise ThsProtocolError("ranking: response count limit")
        except ThsNetworkError:
            if attempt == retries:
                raise
        finally:
            transport.close()
    raise ThsNetworkError("ranking: retry budget exhausted")
