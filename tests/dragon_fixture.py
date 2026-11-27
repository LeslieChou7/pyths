"""合成龙虎榜结构；不含生产响应，不证明真实兼容。"""

import json


def encode(data: object, *, status: int = 0) -> bytes:
    return json.dumps(
        {"status_code": status, "data": data, "succeed": status == 0}
    ).encode()


def calendar_data() -> dict[str, object]:
    return {
        "trade_day_list": ["2026-11-05", "2026-11-06"],
        "last_date": "2026-11-06",
        "last_update_status": False,
        "time": 1234567890123,
    }


def entry_data(*, span: int = 1) -> dict[str, object]:
    return {
        "market_id": "33",
        "stock_code": "000001",
        "stock_name": "合成证券",
        "range_days": span,
        "buy_value": 12.5,
        "sell_value": 2,
        "net_value": 10.5,
        "change": None,
        "net_rate": 0,
        "hot_rank": None,
        "limit_reason": None,
    }


def list_data(*, duplicate_security: bool = False) -> dict[str, object]:
    rows = [entry_data()]
    if duplicate_security:
        rows.append(entry_data(span=3))
    return {
        "module": "all",
        "count": len(rows),
        "stock_count": 1,
        "page": 1,
        "size": 50,
        "items": rows,
    }


def seat_data() -> dict[str, object]:
    return {
        "id": "synthetic-seat",
        "org_id": None,
        "name": "同名合成席位",
        "short_name": None,
        "rank_value": 1,
        "buy_value": 12.5,
        "sell_value": None,
        "net_value": None,
    }


def event_data() -> dict[str, object]:
    return {
        "range_type": "1",
        "start_date": "2026-11-05",
        "end_date": "2026-11-05",
        "reason": [
            {"id": "synthetic-a", "content": "合成原因甲"},
            {"id": "synthetic-b", "content": "合成原因乙"},
        ],
        "buy_value": 12.5,
        "sell_value": 2,
        "net_value": 10.5,
        "buy_items": [seat_data()],
        "sell_items": [seat_data()],
    }


def detail_data() -> dict[str, object]:
    return {
        "market_id": "33",
        "stock_code": "000001",
        "stock_name": "合成证券",
        "details": {"one": [event_data()], "three": [], "ten": [], "thirty": []},
    }
