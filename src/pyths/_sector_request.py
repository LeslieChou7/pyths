"""M13 内部请求编码；可编码不等于来源能力已验收。"""

import json
from datetime import datetime
from typing import Literal

from ._sector_models import SectorPeriod

CATEGORIES = {"all": 0, "industry": 1, "concept": 2, "style": 3, "region": 4}
SORTS = {"change_rate": "0", "main_net_inflow": "1", "turnover": "2"}


def encode_period_request(
    *,
    period: SectorPeriod,
    kind: Literal["block", "stock"],
    sort: str,
    direction: Literal["asc", "desc"],
    page: int = 1,
    category: str | None = None,
    code: str | None = None,
    market: str | None = None,
) -> bytes:
    """由显式来源区间编码请求，不选择日期、不读取凭据或访问网络。"""
    if not isinstance(period, SectorPeriod):
        raise ValueError("sector period must be explicit")  # noqa: TRY004 -- consistent query validation errors
    history_type, start, end = period.wire_values()
    return encode_sector_request(
        kind=kind,
        start=start,
        end=end,
        history_type=history_type,
        sort=sort,
        direction=direction,
        page=page,
        category=category,
        code=code,
        market=market,
    )


def encode_sector_request(
    *,
    kind: Literal["block", "stock"],
    start: str,
    end: str,
    history_type: Literal["0", "1"],
    sort: str,
    direction: Literal["asc", "desc"],
    page: int = 1,
    category: str | None = None,
    code: str | None = None,
    market: str | None = None,
) -> bytes:
    """按已观察JSON形状编码；没有隐式日期、默认市场或任意页长。"""
    if kind not in ("block", "stock") or history_type not in ("0", "1"):
        raise ValueError("unsupported sector mode")
    if sort not in SORTS or direction not in ("asc", "desc"):
        raise ValueError("unsupported sector sorting")
    if type(page) is not int or page < 1:
        raise ValueError("invalid sector page")
    for value in (start, end):
        if (
            not isinstance(value, str)
            or len(value) != 14
            or not value.isascii()
            or not value.isdigit()
        ):
            raise ValueError("invalid sector date encoding")
        try:
            datetime.strptime(value, "%Y%m%d%H%M%S")  # noqa: DTZ007 -- validates text only; source timezone unknown
        except ValueError:
            raise ValueError("invalid sector date encoding") from None
    if start > end:
        raise ValueError("reversed sector interval")
    if history_type == "1" and (start[8:] != "000000" or end[8:] != "000000"):
        raise ValueError("multi-day dates require observed date encoding")
    if history_type == "0" and (
        start[:8] != end[:8] or start[-2:] != "00" or end[-2:] != "00"
    ):
        raise ValueError("intraday interval requires one day and minute precision")
    result: dict[str, object] = {}
    if kind == "block":
        if category not in CATEGORIES or code is not None or market is not None:
            raise ValueError("invalid sector category")
        result["type"] = CATEGORIES[category]
    else:
        if category is not None:
            raise ValueError("constituents require a sector reference")
        for identity in (code, market):
            if (
                not isinstance(identity, str)
                or not 1 <= len(identity) <= 32
                or not identity.isascii()
                or not identity.isdigit()
            ):
                raise ValueError("invalid sector identity")
        result.update(block_code=code, block_market=market)
    result.update(
        history_info={
            "history_type": history_type,
            "start_date": start,
            "end_date": end,
        },
        page_info={"page": page, "page_size": 20},
        sort_info={"sort_field": SORTS[sort], "sort_type": direction},
    )
    return json.dumps(result, separators=(",", ":"), ensure_ascii=True).encode("ascii")
