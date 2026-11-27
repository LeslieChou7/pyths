"""已验证排行能力；新增映射须有独立协议证据。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RankingCapability:
    """请求排序、响应字段与游标范围的共同来源。"""

    sort_id: int
    order: int
    profile: str = "m7_baseline"
    window_minutes: int | None = None
    window_source: str | None = None
    definition_source: str | None = None
    definition_url: str | None = None


_CAPABILITIES = {
    ("change_rate", "desc"): RankingCapability(34818, 0),
    ("change_rate", "asc"): RankingCapability(34818, 1),
    ("turnover", "desc"): RankingCapability(19, 0),
    ("rapid_change_rate", "desc"): RankingCapability(
        48, 0, "m10_rapid", 5, "user_confirmed"
    ),
    ("large_order_net_volume", "desc"): RankingCapability(
        34370,
        0,
        "m10_large",
        definition_source="user_adopted_official",
        definition_url="https://www.10jqka.com.cn/ad_mar/help/dde.html",
    ),
    ("main_net_inflow", "desc"): RankingCapability(
        34391,
        0,
        "m10_main",
        definition_source="user_adopted_official",
        definition_url="https://news.10jqka.com.cn/20260827/c679348022.shtml",
    ),
}


def capability(sort: str, direction: str) -> RankingCapability:
    """未验证的排序组合在构造请求或映射响应前拒绝。"""
    try:
        return _CAPABILITIES[sort, direction]
    except (KeyError, TypeError):
        raise ValueError("unsupported ranking order") from None
