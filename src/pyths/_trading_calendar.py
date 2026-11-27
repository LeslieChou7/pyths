"""冻结的上交所 2026 年交易日。来源与生成规则见第三方声明。"""

from datetime import date
from importlib.resources import files

from .errors import ThsBusinessError

SOURCE_ASSET_SHA256 = "0450145f89c503f7311ebdabfa75177b21cd01aa5ec2dcc54cfc5a23f118336a"
TRADE_DAYS_2026 = tuple(
    day[4:]
    for day in files("pyths")
    .joinpath("_trading_days_2026.txt")
    .read_text("ascii")
    .splitlines()
)


def previous_trade_date(source_day: date) -> date:
    """在已登记年份列表中选前一交易日；缺年、源日或前值明确失败。"""
    if type(source_day) is not date:
        raise ValueError("source_day must be a date")
    if source_day.year != 2026:
        raise ThsBusinessError("calendar: only verified year 2026 is supported")
    current = source_day.strftime("%m%d")
    if current not in TRADE_DAYS_2026:
        raise ThsBusinessError("calendar: source day absent from verified calendar")
    index = TRADE_DAYS_2026.index(current)
    if index == 0:
        raise ThsBusinessError("calendar: previous year is not verified")
    previous = TRADE_DAYS_2026[index - 1]
    return date(2026, int(previous[:2]), int(previous[2:]))
