"""M15查询协调：一页一次请求、显式日期、零自动重试。"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from ._http import request
from ._limit_codec import decode_limit_pool
from ._limit_models import (
    LimitFocusSummary,
    LimitPoolCursor,
    LimitPoolPage,
    LimitSummarySide,
)
from ._limit_request import (
    POOL_DEFAULTS,
    LimitFilters,
    LimitPoolKind,
    LimitPoolQuery,
    encode_limit_query,
)
from ._limit_scopes import APP_SCOPES, INDEPENDENT_SCOPES, PUBLIC_SCOPES
from .errors import ThsProtocolError


@dataclass(frozen=True)
class LimitCapabilities:
    """本地证据目录；不联网，各维度不构成笛卡尔积。"""

    app_observed_scopes: tuple[tuple[str, ...], ...] = APP_SCOPES
    independent_probe_scopes: tuple[tuple[str, ...], ...] = INDEPENDENT_SCOPES
    public_verified_scopes: tuple[tuple[str, ...], ...] = PUBLIC_SCOPES
    limitations: tuple[str, ...] = (
        "Explicit dates only; latest date discovery is unverified.",
        "No atomic snapshot or full-market coverage is implied.",
        "Previous trading date, metric definitions and state transitions remain partially unknown.",
    )


def scope(query: LimitPoolQuery, page: int) -> tuple[str, ...]:
    encode_limit_query(query, page=page)
    return (
        query.pool,
        query.trade_date.strftime("%Y%m%d"),
        query.filters.to_wire(),
        query.sort_field or POOL_DEFAULTS[query.pool][2],
        query.order_type,
        str(page),
    )


def make_query(
    *,
    pool: LimitPoolKind,
    trade_date: date | None,
    filters: LimitFilters | None,
    sort: str | None,
    direction: Literal["asc", "desc"] | None,
) -> LimitPoolQuery:
    if type(trade_date) is not date:
        raise ValueError(
            "explicit source date required; latest discovery is unverified"
        )
    if direction not in (None, "asc", "desc") or sort not in (
        None,
        "change_rate",
        "latest",
    ):
        raise ValueError("unsupported limit sort selection")
    query = LimitPoolQuery(
        pool,
        trade_date,
        LimitFilters() if filters is None else filters,
        {"change_rate": "199112", "latest": "10"}.get(sort)
        if sort is not None
        else None,
        "1" if direction == "asc" else "0",
    )
    encode_limit_query(query)
    return query


def summary_query(
    trade_date: date | None, filters: LimitFilters | None
) -> LimitPoolQuery:
    for pool in ("limit_up", "limit_down"):
        query = make_query(
            pool=pool, trade_date=trade_date, filters=filters, sort=None, direction=None
        )
        if scope(query, 1) in APP_SCOPES:
            return query
        for observed in APP_SCOPES:
            if (
                observed[0] == pool
                and observed[1] == query.trade_date.strftime("%Y%m%d")
                and observed[2] == query.filters.to_wire()
                and observed[5] == "1"
            ):
                return LimitPoolQuery(
                    query.pool,
                    query.trade_date,
                    query.filters,
                    observed[3],
                    "1" if observed[4] == "1" else "0",
                )
    raise ValueError("summary is outside observed date/filter combinations")


def query_pool(
    *,
    owner: object,
    query: LimitPoolQuery,
    cursor: LimitPoolCursor | None,
    timeout: float,
    connect_timeout: float,
) -> LimitPoolPage:
    page = 1
    if cursor is not None:
        if (
            not isinstance(cursor, LimitPoolCursor)
            or cursor._owner is not owner
            or cursor._query != query
            or type(cursor._page) is not int
        ):
            raise ValueError("limit cursor belongs to a different client or query")
        page = cursor._page
    if scope(query, page) not in APP_SCOPES:
        raise ValueError("limit query is outside observed combinations")
    response = request(
        encode_limit_query(query, page=page),
        deadline=time.monotonic() + timeout,
        connect_timeout=connect_timeout,
        headers={"Accept": "application/json"},
        expected_json=True,
    )
    wire = decode_limit_pool(response.body)
    empty_zero = (
        page == 1
        and wire.page == 0
        and wire.total == 0
        and wire.page_count == 0
        and not wire.rows
    )
    if (wire.page != page and not empty_zero) or wire.page_size != 15:
        raise ThsProtocolError("limit focus: response page mismatch")
    if wire.date_raw is not None and wire.date_raw != query.trade_date.strftime(
        "%Y%m%d"
    ):
        raise ThsProtocolError("limit focus: response date mismatch")
    count = len(wire.rows)
    end = (page - 1) * wire.page_size + count
    warnings: tuple[str, ...] = ("source_empty_page_zero",) if empty_zero else ()
    continuation = None
    if (
        end > wire.total
        or wire.page_count != (wire.total + 14) // 15
        or (count < 15 and end < wire.total)
    ):
        more = None
        warnings = ("source_page_inconsistent",)
    else:
        more = end < wire.total
        if more:
            if scope(query, page + 1) in APP_SCOPES:
                continuation = LimitPoolCursor(owner, query, page + 1)
            else:
                warnings = ("next_page_not_verified",)
    return LimitPoolPage(
        query,
        wire.rows,
        wire.date_raw,
        page,
        wire.page_size,
        wire.total,
        wire.page_count,
        datetime.now(UTC),
        more,
        continuation,
        wire.summary,
        warnings,
        source_page=wire.page,
    )


def summarize(page: LimitPoolPage, *, allow_partial: bool) -> LimitFocusSummary:
    if type(allow_partial) is not bool:
        raise ValueError("allow_partial must be boolean")
    missing = False
    sides = []
    for name in ("today", "yesterday"):
        raw = page.summary_raw[name]
        if not isinstance(raw, Mapping):
            raise ThsProtocolError("limit focus: invalid summary")
        num, opened, rate = raw.get("num"), raw.get("open_num"), raw.get("rate")
        if num is None or opened is None or rate is None:
            missing = True
        if (num is not None and type(num) is not int) or (
            opened is not None and type(opened) is not int
        ):
            raise ThsProtocolError("limit focus: invalid counts")
        numeric_rate = Decimal(rate) if type(rate) is int else rate
        if numeric_rate is not None and not isinstance(numeric_rate, Decimal):
            raise ThsProtocolError("limit focus: invalid ratio")
        sides.append(LimitSummarySide(num, opened, numeric_rate))
    if missing and not allow_partial:
        raise ThsProtocolError("limit focus: incomplete summary")
    return LimitFocusSummary(
        page.query,
        page.source_date_raw,
        sides[0],
        sides[1],
        page.received_at,
        ("incomplete_summary",) if missing else (),
    )
