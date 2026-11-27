"""单侧快照的有界轮询。变化仅描述本地观察到的可见集合。"""

import math
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import date
from threading import Event

from ._auction import AuctionSectorSide, AuctionSectorSnapshot, query_auction_sectors
from ._auction_codec import AuctionSector
from .errors import ThsProtocolError


@dataclass(frozen=True)
class AuctionSectorObservation:
    snapshot: AuctionSectorSnapshot
    baseline: bool
    entered: tuple[AuctionSector, ...]
    updated: tuple[AuctionSector, ...]
    left: tuple[AuctionSector, ...]


def observe_sectors(
    side: AuctionSectorSide,
    trade_date: date,
    *,
    interval: float,
    max_duration: float,
    max_requests: int,
    timeout: float,
    connect_timeout: float,
    closed: Event,
) -> Generator[AuctionSectorObservation]:
    if type(trade_date) is not date or side not in ("bullish", "bearish"):
        raise ValueError("explicit auction side and date required")
    if any(
        type(v) not in (float, int) or not math.isfinite(v)
        for v in (interval, max_duration)
    ):
        raise ValueError("finite polling times required")
    if not 5 <= interval <= 600 or not 0 < max_duration <= 600:
        raise ValueError(
            "interval must be 5..600 seconds and duration at most 600 seconds"
        )
    if type(max_requests) is not int or not 1 <= max_requests <= 120:
        raise ValueError("request budget must be 1..120")

    def poll() -> Generator[AuctionSectorObservation]:
        deadline = time.monotonic() + max_duration
        previous: dict[tuple[str, str], AuctionSector] | None = None
        next_due = time.monotonic()
        for _ in range(max_requests):
            if next_due >= deadline or closed.is_set():
                return
            delay = next_due - time.monotonic()
            if delay > 0 and closed.wait(delay):
                return
            now = time.monotonic()
            if now >= deadline or closed.is_set():
                return
            snapshot = query_auction_sectors(
                side,
                trade_date,
                deadline=min(now + timeout, deadline),
                connect_timeout=connect_timeout,
            )
            next_due = time.monotonic() + interval
            if closed.is_set() or time.monotonic() >= deadline:
                return
            current = {(row.market, row.code): row for row in snapshot.sectors}
            if len(current) != len(snapshot.sectors):
                raise ThsProtocolError("auction: ambiguous sector identity")
            baseline = previous is None
            old = previous or {}
            entered = tuple(
                row for k, row in current.items() if not baseline and k not in old
            )
            updated = tuple(
                row for k, row in current.items() if k in old and row != old[k]
            )
            left = tuple(row for k, row in old.items() if k not in current)
            previous = current
            yield AuctionSectorObservation(snapshot, baseline, entered, updated, left)

    return poll()
