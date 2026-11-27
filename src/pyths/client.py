"""同步客户端生命周期与实验性只读查询。"""

import math
import struct
import time
from collections.abc import Generator, Sequence
from datetime import UTC, date, datetime
from threading import Event
from types import TracebackType
from typing import Literal, Self

from ._auction import (
    AuctionRankingKind,
    AuctionRankingPage,
    AuctionSectorSide,
    AuctionSectorSnapshot,
    query_auction_ranking,
    query_auction_sectors,
)
from ._auction_watch import AuctionSectorObservation, observe_sectors
from ._auth import encode_session_request
from ._dragon import query_detail as query_dragon_detail
from ._dragon import query_events as query_dragon_events
from ._dragon import query_list as query_dragon_list
from ._dragon_models import (
    DragonTigerCursor,
    DragonTigerDetail,
    DragonTigerEntryRef,
    DragonTigerEvent,
    DragonTigerEventRef,
    DragonTigerPage,
)
from ._event_models import (
    StockAnomalyCursor,
    StockAnomalyKind,
    StockAnomalyPage,
    TradingStatusCursor,
    TradingStatusKind,
    TradingStatusPage,
)
from ._events import query_anomalies, query_status
from ._headers import decode_response_header
from ._hot import BOARDS, query_hot, validate_board
from ._hot_models import HotBoard, HotBoardId, HotRankingCursor, HotRankingPage
from ._limit import LimitCapabilities, make_query, query_pool, summarize, summary_query
from ._limit_models import LimitFocusSummary, LimitPoolCursor, LimitPoolPage
from ._limit_request import LimitFilters, LimitPoolKind
from ._market import COMPONENTS, query_overview, validate_selection
from ._market_models import MarketOverview
from ._quote import QUOTE_MARKETS, quote_from_table
from ._ranking_capabilities import capability
from ._ranking_query import query_page
from ._ranking_request import encode_ranking_body
from ._request import encode_quote_request, encode_stop_request
from ._response import decode_1269_response
from ._sector import query_sector_page
from ._sector_capabilities import SectorCapabilities, sector_capabilities
from ._sector_models import SectorPeriod
from ._sector_page import SectorPage
from ._sector_query import SectorCursor, SectorQuery, SectorRef
from ._sector_verified import validate_verified_query
from ._session import SessionContext, establish_session
from ._transform import decode_wire_body
from ._transport import TcpTransport
from .errors import ThsClientClosedError, ThsNetworkError, ThsProtocolError
from .models import QuoteSnapshot, RankingCursor, StockRankingPage


class ths:
    """同步只读客户端；线上能力验证中，不承诺线程安全。"""

    def __init__(
        self,
        *,
        endpoint: tuple[str, int] | None = None,
        app_config: str | None = None,
        app_info: str | None = None,
        connect_timeout: float = 5,
        request_timeout: float = 15,
        retries: int = 0,
    ) -> None:
        for timeout in (connect_timeout, request_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("timeouts must be positive and finite")
        if type(retries) is not int or retries not in (0, 1):
            raise ValueError("retries must be 0 or 1")
        self._closed = False
        self._auction_closed = Event()
        self._endpoint = endpoint
        self._app_config = app_config
        self._app_info = app_info
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._retries = retries
        self._transport = TcpTransport()
        self._session: SessionContext | None = None
        self._counter = 0
        self._completed: dict[int, tuple[str, str]] = {}

    def watch_auction_sector_changes(
        self,
        *,
        side: AuctionSectorSide,
        trade_date: date,
        interval: float,
        max_duration: float,
        max_requests: int,
    ) -> Generator[AuctionSectorObservation]:
        """同步轮询可见板块快照，首次返回基线，后续返回本地变化。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return observe_sectors(
            side,
            trade_date,
            interval=interval,
            max_duration=max_duration,
            max_requests=max_requests,
            timeout=self._request_timeout,
            connect_timeout=self._connect_timeout,
            closed=self._auction_closed,
        )

    def get_auction_sector_changes(
        self, *, side: AuctionSectorSide, trade_date: date
    ) -> AuctionSectorSnapshot:
        """读取指定日期、单侧的板块异动监控快照。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return query_auction_sectors(
            side,
            trade_date,
            deadline=time.monotonic() + self._request_timeout,
            connect_timeout=self._connect_timeout,
        )

    def get_auction_ranking(
        self, *, kind: AuctionRankingKind, trade_date: date
    ) -> AuctionRankingPage:
        """查询显式上海当日日期的集合竞价榜单默认首屏，保留来源顺序。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return query_auction_ranking(
            kind,
            trade_date,
            timeout=self._request_timeout,
            connect_timeout=self._connect_timeout,
        )

    def get_limit_capabilities(self) -> LimitCapabilities:
        """本地涨停能力证据目录，不联网，各选项不代表任意组合可用。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return LimitCapabilities()

    def get_limit_pool(
        self,
        *,
        pool: LimitPoolKind,
        trade_date: date | None = None,
        filters: LimitFilters | None = None,
        sort: str | None = None,
        direction: Literal["asc", "desc"] | None = None,
        page: LimitPoolCursor | None = None,
    ) -> LimitPoolPage:
        """显式日期的五池单页；仅已观察组合，不自动续页或重试。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        query = make_query(
            pool=pool,
            trade_date=trade_date,
            filters=filters,
            sort=sort,
            direction=direction,
        )
        return query_pool(
            owner=self,
            query=query,
            cursor=page,
            timeout=self._request_timeout,
            connect_timeout=self._connect_timeout,
        )

    def get_limit_focus_summary(
        self,
        *,
        trade_date: date | None = None,
        filters: LimitFilters | None = None,
        allow_partial: bool = False,
    ) -> LimitFocusSummary:
        """六统计来自一次已观察池响应，保留源比率，不估算或补昨日日期。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        if type(allow_partial) is not bool:
            raise ValueError("allow_partial must be boolean")
        query = summary_query(trade_date, filters)
        result = query_pool(
            owner=self,
            query=query,
            cursor=None,
            timeout=self._request_timeout,
            connect_timeout=self._connect_timeout,
        )
        return summarize(result, allow_partial=allow_partial)

    def get_stock_anomalies(
        self, *, kind: StockAnomalyKind, page: StockAnomalyCursor | None = None
    ) -> StockAnomalyPage:
        """查询当前/历史异动单页，日期与类型码保持来源原值。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return query_anomalies(
            owner=self,
            kind=kind,
            page=page,
            timeout=self._request_timeout,
            connect_timeout=self._connect_timeout,
        )

    def get_trading_status_events(
        self, *, kind: TradingStatusKind, page: TradingStatusCursor | None = None
    ) -> TradingStatusPage:
        """查询最新停牌/复牌单页，不推断实际状态或自动拉全量。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return query_status(
            owner=self,
            kind=kind,
            page=page,
            timeout=self._request_timeout,
            connect_timeout=self._connect_timeout,
        )

    def get_sector_capabilities(self) -> SectorCapabilities:
        """仅返回本地板块证据摘要；不联网，不代表网络查询已验收。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return sector_capabilities()

    def get_sector_ranking(
        self,
        *,
        category: str,
        period: SectorPeriod,
        sort: str = "change_rate",
        direction: Literal["asc", "desc"] = "desc",
        page: SectorCursor | None = None,
    ) -> SectorPage:
        """获取已验收范围的板块单页；范围外在发送前拒绝，不自动续页。"""
        return self._get_sector_page(
            SectorQuery("block", period, sort, direction, category=category), page
        )

    def get_sector_constituents(
        self,
        *,
        sector: SectorRef,
        period: SectorPeriod,
        sort: str = "change_rate",
        direction: Literal["asc", "desc"] = "desc",
        page: SectorCursor | None = None,
    ) -> SectorPage:
        """按同客户端排行引用获取已验收成分单页，不隐式展开全部成员。"""
        return self._get_sector_page(
            SectorQuery("stock", period, sort, direction, sector=sector), page
        )

    def _get_sector_page(
        self,
        query: SectorQuery,
        page: SectorCursor | None,
    ) -> SectorPage:
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        validate_verified_query(self, query, page)
        return query_sector_page(
            owner=self,
            query=query,
            cursor=page,
            deadline=time.monotonic() + self._request_timeout,
            connect_timeout=self._connect_timeout,
            retries=self._retries,
        )

    def get_dragon_tiger_list(
        self, *, trade_date: date, page: DragonTigerCursor | None = None
    ) -> DragonTigerPage:
        """实验性指定日期日榜；每次核对来源日期状态，不隐式展开详情。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return query_dragon_list(
            owner=self,
            trade_date=trade_date,
            page=page,
            deadline=time.monotonic() + self._request_timeout,
            connect_timeout=self._connect_timeout,
            retries=self._retries,
        )

    def get_dragon_tiger_events(
        self, *, entry: DragonTigerEntryRef
    ) -> tuple[DragonTigerEvent, ...]:
        """显式展开一个日榜候选条目的真实事件，返回完整事件引用。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return query_dragon_events(
            owner=self,
            entry=entry,
            deadline=time.monotonic() + self._request_timeout,
            connect_timeout=self._connect_timeout,
            retries=self._retries,
        )

    def get_dragon_tiger_detail(
        self, *, event: DragonTigerEventRef
    ) -> DragonTigerDetail:
        """按真实完整引用获取单事件详情；不自动合并区间、原因或席位。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return query_dragon_detail(
            owner=self,
            event=event,
            deadline=time.monotonic() + self._request_timeout,
            connect_timeout=self._connect_timeout,
            retries=self._retries,
        )

    def get_hot_boards(self) -> tuple[HotBoard, ...]:
        """返回本地已验证热榜能力目录，不联网或实时发现。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return BOARDS

    def get_hot_ranking(
        self, *, board: HotBoardId, page: HotRankingCursor | None = None
    ) -> HotRankingPage:
        """获取热股1小时或24小时单响应快照；无需TCP配置。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        selected = validate_board(board, page)
        return query_hot(
            board=selected,
            connect_timeout=self._connect_timeout,
            deadline=time.monotonic() + self._request_timeout,
            retries=self._retries,
        )

    def get_quote(self, stock_code: str, *, market: str) -> QuoteSnapshot:
        """查询单只 A 股的 1269 显示快照，市场标识为沪 17、深 33、北 151。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        if (
            not isinstance(stock_code, str)
            or len(stock_code) != 6
            or not stock_code.isascii()
            or not stock_code.isdigit()
            or market not in QUOTE_MARKETS
        ):
            raise ValueError(
                f"expected six ASCII digits and a market in {QUOTE_MARKETS}"
            )
        if self._endpoint is None or self._app_config is None or not self._app_info:
            raise ValueError("explicit endpoint, app_config and app_info required")
        deadline = time.monotonic() + self._request_timeout
        for attempt in range(self._retries + 1):
            try:
                if self._counter >= 32766:
                    self._transport.close()
                    self._session = None
                if self._session is None:
                    self._counter = 0
                    self._completed.clear()
                    self._transport.connect(
                        self._endpoint,
                        deadline=deadline,
                        connect_timeout=self._connect_timeout,
                    )
                    packet = encode_session_request(
                        config=self._app_config, app_info=self._app_info, passport=b""
                    )
                    self._session = establish_session(
                        self._transport, packet, deadline=deadline
                    )
                self._counter += 1
                identifier = self._counter
                # 已确认价格概况功能使用固定业务frame；包号/实例仍独立分配。
                quote_frame = 2267
                packet = encode_quote_request(
                    stock_code=stock_code,
                    market=market,
                    package_id=identifier,
                    frame_id=quote_frame,
                    instance_id=identifier,
                    app_info=self._app_info,
                    session_id=self._session.session_id,
                )
                self._transport.send(packet, deadline=deadline)
                for _ in range(20):
                    frame = self._transport.receive(deadline=deadline)
                    received_at = datetime.now(UTC)
                    header = decode_response_header(frame)
                    if header.payload_length != len(frame) - header.length:
                        raise ThsProtocolError("client: payload length mismatch")
                    if header.flags in (11, 65547):
                        continue
                    payload = frame[header.length :]
                    header_bytes = bytearray(frame[: header.length])
                    if (
                        int.from_bytes(header.extension[:2], "little", signed=True)
                        == -253
                    ):
                        payload = decode_wire_body(payload)
                        struct.pack_into("<i", header_bytes, 12, len(payload))
                    if header.package_id == -1:
                        previous = self._completed.get(header.instance_id)
                        if header.length != 26 or previous is None:
                            raise ThsProtocolError("client: unknown update instance")
                        old_table = decode_1269_response(
                            bytes(header_bytes),
                            payload,
                            package_id=-1,
                            frame_id=quote_frame,
                            instance_id=header.instance_id,
                        )
                        # 已完成实例的残留更新只校验并丢弃，不能完成当前查询。
                        quote_from_table(
                            old_table, stock_code=previous[0], market=previous[1]
                        )
                        continue
                    table = decode_1269_response(
                        bytes(header_bytes),
                        payload,
                        package_id=identifier,
                        frame_id=quote_frame,
                        instance_id=identifier,
                        allow_initial_frame_zero=True,
                    )
                    quote = quote_from_table(
                        table,
                        stock_code=stock_code,
                        market=market,
                        received_at=received_at,
                    )
                    self._counter += 1
                    stop = encode_stop_request(
                        package_id=self._counter,
                        frame_id=quote_frame,
                        app_info=self._app_info,
                        session_id=self._session.session_id,
                    )
                    self._transport.send(stop, deadline=deadline)
                    self._completed[identifier] = (stock_code, market)
                    return quote
                raise ThsProtocolError("client: response count limit")
            except ThsNetworkError:
                self._transport.close()
                self._session = None
                self._completed.clear()
                if attempt == self._retries:
                    raise
            except BaseException:
                self._transport.close()
                self._session = None
                self._completed.clear()
                raise
        raise ThsNetworkError("client: retry budget exhausted")

    def get_stock_ranking(
        self,
        *,
        sort: Literal[
            "change_rate",
            "turnover",
            "rapid_change_rate",
            "large_order_net_volume",
            "main_net_inflow",
        ] = "change_rate",
        direction: Literal["asc", "desc"] = "desc",
        page: RankingCursor | None = None,
    ) -> StockRankingPage:
        """实验性固定筛选排行，每页24条；独立连接获取一页后释放。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        start = 0
        selected = capability(sort, direction)
        if page is not None:
            if (
                not isinstance(page, RankingCursor)
                or page._owner is not self
                or page._sort != sort
                or page._direction != direction
                or page._profile != selected.profile
            ):
                raise ValueError("cursor does not belong to this query")
            start = page._start
        encode_ranking_body(instance_id=1, start=start, sort=sort, direction=direction)
        if self._endpoint is None or self._app_config is None or not self._app_info:
            raise ValueError("explicit endpoint, app_config and app_info required")
        return query_page(
            endpoint=self._endpoint,
            app_config=self._app_config,
            app_info=self._app_info,
            connect_timeout=self._connect_timeout,
            deadline=time.monotonic() + self._request_timeout,
            retries=self._retries,
            owner=self,
            start=start,
            sort=sort,
            direction=direction,
        )

    @property
    def closed(self) -> bool:
        """客户端是否已经关闭。"""
        return self._closed

    def get_market_overview(
        self,
        *,
        scope: str = "m8_baseline",
        components: Sequence[str] = COMPONENTS,
        allow_partial: bool = False,
    ) -> MarketOverview:
        """M8按需概览；组件独立计时，默认要求所选组件全部成功。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        selected = validate_selection(scope, components, allow_partial)
        if self._endpoint is None or self._app_config is None or not self._app_info:
            raise ValueError("explicit endpoint, app_config and app_info required")
        return query_overview(
            scope=scope,
            components=selected,
            allow_partial=allow_partial,
            endpoint=self._endpoint,
            app_config=self._app_config,
            app_info=self._app_info,
            connect_timeout=self._connect_timeout,
            deadline=time.monotonic() + self._request_timeout,
            retries=self._retries,
        )

    def close(self) -> None:
        """幂等关闭客户端。"""
        self._closed = True
        self._auction_closed.set()
        self._transport.close()
        self._session = None
        self._completed.clear()

    def __enter__(self) -> Self:
        """进入上下文；关闭后不可重入。"""
        if self.closed:
            raise ThsClientClosedError("客户端已经关闭")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """关闭客户端并传播异常。"""
        self.close()
