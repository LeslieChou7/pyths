"""板块能力的本地证据摘要；不探测网络、不推断授权状态。"""

from dataclasses import dataclass
from typing import Literal

from ._sector_verified_data import VERIFIED_SCOPES


@dataclass(frozen=True)
class SectorCapabilities:
    """App观察范围与SDK真实验收分开；各维度不构成组合白名单。"""

    source: str = "sector_statistics_v1"
    status: Literal["sdk_partially_verified"] = "sdk_partially_verified"
    sdk_network_verified: bool = False
    independent_http_probe_verified: bool = True
    independent_http_probe_scope: tuple[str, ...] = (
        "block/industry/historical_day/2026-11-12/change_rate/desc/page1/size20",
    )
    verified_business_scopes: tuple[str, ...] = tuple(
        "/".join(scope) + "/size20" for scope in VERIFIED_SCOPES
    )
    verified_platforms: tuple[str, ...] = ("windows", "linux")
    observed_categories: tuple[str, ...] = (
        "all",
        "industry",
        "concept",
        "style",
        "region",
    )
    observed_sorts: tuple[str, ...] = ("change_rate", "main_net_inflow", "turnover")
    observed_directions: tuple[str, ...] = ("asc", "desc")
    observed_period_modes: tuple[str, ...] = ("intraday", "historical_day", "multi_day")
    observed_page_size: int = 20
    limitations: tuple[str, ...] = (
        "App observations do not verify independent SDK access or all combinations.",
        "30 exact internal queries passed cross-platform and retained App-row checks where available.",
        "Five 2026-11-16 11:04-15:00 first-page scopes passed same-wheel Windows/Linux checks.",
        "Seven historical partial-intraday queries differed from App values and remain blocked.",
        "Eight exact public pages passed same-wheel live acceptance through OpenTHS on both platforms.",
        "The 30-scope registry includes internal evidence; not all public combinations were live tested.",
        "The probe used public Accept; its effect alone has not been established.",
        "Earliest historical date and interval boundary inclusion are unknown.",
        "Currency, turnover-rate display unit and source update time are unverified.",
        "Latest source date must not be inferred from the local calendar date.",
    )


def sector_capabilities() -> SectorCapabilities:
    """返回不可变的本地摘要；不检测服务端当前可用性。"""
    return SectorCapabilities()
