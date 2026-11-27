"""P29/P44精确网络验收范围；不由可编码维度推导全组合兼容。"""

from ._sector_query import SectorCursor, SectorQuery, encode_query
from ._sector_verified_data import VERIFIED_SCOPES


def validate_verified_query(
    owner: object, query: SectorQuery, cursor: SectorCursor | None
) -> None:
    """先校验来源和游标归属，再核对完整参数与已验收页号。"""
    page, _ = encode_query(owner, query, cursor)
    mode, start, end = query.period.wire_values()
    ref = query.sector
    key = (
        query.kind,
        query.category or "",
        "" if ref is None else ref.code,
        "" if ref is None else ref.market,
        mode,
        start,
        end,
        query.sort,
        query.direction,
        str(page),
    )
    if key not in VERIFIED_SCOPES:
        raise ValueError("sector query is outside the verified SDK scope")
