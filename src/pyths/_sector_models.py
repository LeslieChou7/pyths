"""板块查询的内部类型模型；查询可表达不代表服务端范围已验收。"""

from dataclasses import dataclass
from datetime import date, time
from typing import Literal


@dataclass(frozen=True)
class SectorPeriod:
    """显式来源日期与分钟区间；不猜测最新交易日、时区或交易日历。"""

    mode: Literal["intraday", "historical_day", "multi_day"]
    start_date: date
    end_date: date
    start_time: time | None = None
    end_time: time | None = None

    def __post_init__(self) -> None:
        if type(self.start_date) is not date or type(self.end_date) is not date:
            raise ValueError("sector dates must be date values")
        if self.start_date > self.end_date:
            raise ValueError("reversed sector dates")
        if self.mode in ("multi_day", "historical_day"):
            if self.start_time is not None or self.end_time is not None:
                raise ValueError("multi-day interval cannot include intraday times")
            if self.mode == "historical_day" and self.start_date != self.end_date:
                raise ValueError("historical day requires one source date")
        elif self.mode == "intraday":
            if self.start_date != self.end_date:
                raise ValueError("intraday interval requires one source date")
            for value in (self.start_time, self.end_time):
                if (
                    type(value) is not time
                    or value.tzinfo is not None
                    or value.second
                    or value.microsecond
                    or value.fold
                ):
                    raise ValueError("sector time must be a source-local minute")
            if (
                self.start_time is None
                or self.end_time is None
                or self.start_time > self.end_time
            ):
                raise ValueError("reversed or missing sector times")
        else:
            raise ValueError("unsupported sector interval mode")

    @classmethod
    def single_day(cls, trade_date: date) -> "SectorPeriod":
        """表达盘内整段09:30—15:00；不表示任意历史日期支持该模式。"""
        return cls("intraday", trade_date, trade_date, time(9, 30), time(15))

    @classmethod
    def historical_day(cls, trade_date: date) -> "SectorPeriod":
        """按X29表达历史整日；不自动选择交易日或推断来源最新日期。"""
        return cls("historical_day", trade_date, trade_date)

    @classmethod
    def intraday(cls, trade_date: date, *, start: time, end: time) -> "SectorPeriod":
        """显式盘内分钟区间；来源可用时间范围另由能力层限制。"""
        return cls("intraday", trade_date, trade_date, start, end)

    @classmethod
    def multi_day(cls, start: date, end: date) -> "SectorPeriod":
        """显式日期区间；不修正周末、节假日或来源历史覆盖。"""
        return cls("multi_day", start, end)

    def wire_values(self) -> tuple[Literal["0", "1"], str, str]:
        """生成已观察的14位来源文本，不转换本地时区或补来源时间。"""
        start = self.start_date.isoformat().replace("-", "")
        end = self.end_date.isoformat().replace("-", "")
        if self.mode in ("multi_day", "historical_day"):
            return "1", start + "000000", end + "000000"
        if self.start_time is None or self.end_time is None:
            raise ValueError("missing intraday times")
        return (
            "0",
            start + self.start_time.strftime("%H%M") + "00",
            end + self.end_time.strftime("%H%M") + "00",
        )
