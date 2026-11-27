"""固定热榜能力与独立HTTP查询，不携带TCP配置或跨调用缓存。"""

import time
from datetime import UTC, datetime
from typing import cast

from ._hot_codec import decode_hot_response
from ._hot_models import HotBoard, HotBoardId, HotRankingCursor, HotRankingPage
from ._http import request
from .errors import ThsNetworkError

BOARDS = (
    HotBoard(
        "stock_hour", "大家都在看", "1小时", "App热股/a固定来源；完整证券集合未知"
    ),
    HotBoard(
        "stock_24h", "大家都在看", "24小时", "App热股/a固定来源；完整证券集合未知"
    ),
)
PATHS = {
    "stock_hour": "/open/api/hot_list/v1/hot_stock/a/hour/data.txt",
    "stock_24h": "/open/api/hot_list/v1/hot_stock/a/day/data.txt",
}
UNKNOWN = (
    "热度算法及原始rate计量单位未知；显示为App派生值",
    "排名变化比较基准未知",
    "证券集合、服务端总数、列表完整性和来源更新时间未知",
    "最新价与涨跌幅未包含于本热榜来源；不隐式追加行情请求",
    "服务端缓存与真实限流规则未知；显式请求不保证数据更新",
)


def validate_board(board: str, page: HotRankingCursor | None) -> HotBoardId:
    """仅支持两榜单响应，无真实续页可用。"""
    if not isinstance(board, str) or board not in PATHS or page is not None:
        raise ValueError("unsupported hot board or pagination")
    return cast(HotBoardId, board)


def query_hot(
    *,
    board: HotBoardId,
    connect_timeout: float,
    deadline: float,
    retries: int,
) -> HotRankingPage:
    """最多一次可选网络重试，所有尝试共享截止时间。"""
    path = PATHS[board]
    for attempt in range(retries + 1):
        try:
            if time.monotonic() >= deadline:
                raise ThsNetworkError("hot ranking: deadline exceeded")
            response = request(
                "https://eq.10jqka.com.cn" + path,
                deadline=deadline,
                connect_timeout=connect_timeout,
            )
            received = datetime.now(UTC)
            items = decode_hot_response(response.body)
            return HotRankingPage(board, items, received, path, UNKNOWN)
        except ThsNetworkError:
            if attempt == retries:
                raise
    raise ThsNetworkError("hot ranking: retry budget exhausted")
