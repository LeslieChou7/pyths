"""内部板块引用及分页上下文验证；不发送网络请求。"""

from dataclasses import dataclass, field
from typing import Literal

from ._sector_models import SectorPeriod
from ._sector_request import encode_period_request

SOURCE = "sector_statistics_v1"


@dataclass(frozen=True)
class SectorRef:
    """来源板块身份，与证券身份分开；引用绑定生成它的客户端。"""

    _owner: object = field(repr=False, compare=False)
    code: str
    market: str
    source: str = SOURCE


@dataclass(frozen=True)
class SectorQuery:
    """完整单页查询上下文；不是已验收服务端能力目录。"""

    kind: Literal["block", "stock"]
    period: SectorPeriod
    sort: str
    direction: Literal["asc", "desc"]
    category: str | None = None
    sector: SectorRef | None = None


@dataclass(frozen=True, repr=False)
class SectorCursor:
    """仅同一客户端及完整查询可使用；不提供序列化恢复。"""

    _owner: object = field(repr=False)
    _query: SectorQuery
    _page: int


def encode_query(
    owner: object, query: SectorQuery, cursor: SectorCursor | None = None
) -> tuple[int, bytes]:
    """校验来源与上下文后编码一页；无隐式续页、去重或拉全。"""
    if not isinstance(query, SectorQuery):
        raise ValueError("invalid sector query")  # noqa: TRY004
    ref = query.sector
    if query.kind == "stock":
        if (
            not isinstance(ref, SectorRef)
            or ref._owner is not owner
            or ref.source != SOURCE
        ):
            raise ValueError(
                "sector reference does not belong to this source and client"
            )
    elif ref is not None:
        raise ValueError("block ranking cannot include a constituent reference")
    page = 1
    if cursor is not None:
        if (
            not isinstance(cursor, SectorCursor)
            or cursor._owner is not owner
            or cursor._query != query
            or type(cursor._page) is not int
            or cursor._page < 2
        ):
            raise ValueError("cursor does not belong to this sector query")
        page = cursor._page
    body = encode_period_request(
        period=query.period,
        kind=query.kind,
        category=query.category,
        code=None if ref is None else ref.code,
        market=None if ref is None else ref.market,
        sort=query.sort,
        direction=query.direction,
        page=page,
    )
    return page, body
