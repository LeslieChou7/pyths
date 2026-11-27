"""M13业务协调；公共客户端另按精确验收范围限制查询。"""

import math
import time
from datetime import UTC, datetime

from ._http import request
from ._sector_page import SectorPage, assemble_page
from ._sector_query import SectorCursor, SectorQuery, encode_query
from .errors import ThsNetworkError

_PATHS = {
    "block": "/interval_calculation/block_info/v1/get_block_list",
    "stock": "/interval_calculation/stock_info/v1/get_stock_list_by_block",
}


def query_sector_page(
    *,
    owner: object,
    query: SectorQuery,
    cursor: SectorCursor | None,
    deadline: float,
    connect_timeout: float,
    retries: int,
) -> SectorPage:
    """单次只读POST；可选一次网络重试共用截止时间，无跨来源凭据。"""
    if type(retries) is not int or retries not in (0, 1):
        raise ValueError("sector retries must be 0 or 1")
    if (
        not math.isfinite(deadline)
        or not math.isfinite(connect_timeout)
        or connect_timeout <= 0
    ):
        raise ValueError("invalid sector deadline or timeout")
    _, body = encode_query(owner, query, cursor)
    url = "https://dq.10jqka.com.cn" + _PATHS[query.kind]
    for attempt in range(retries + 1):
        if time.monotonic() >= deadline:
            raise ThsNetworkError("sector statistics: deadline exceeded")
        try:
            response = request(
                url,
                method="POST",
                body=body,
                expected_json=True,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/plain, */*",
                },
                deadline=deadline,
                connect_timeout=connect_timeout,
            )
        except ThsNetworkError:
            if attempt == retries:
                raise
            continue
        if time.monotonic() >= deadline:
            raise ThsNetworkError("sector statistics: deadline exceeded")
        return assemble_page(
            response.body,
            owner=owner,
            query=query,
            cursor=cursor,
            received_at=datetime.now(UTC),
        )
    raise ThsNetworkError("sector statistics: retry budget exhausted")
