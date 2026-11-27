"""Synthetic hot-list structure only; no production response or compatibility claim."""

import json


def payload(rows=None):
    if rows is None:
        rows = [
            {
                "order": 2,
                "code": "000001",
                "market": 33,
                "name": "合成甲",
                "rate": "635459.0",
                "hot_rank_chg": -3,
            },
            {
                "order": 1,
                "code": "600001",
                "market": 17,
                "name": "合成乙",
                "rate": "6489718",
                "hot_rank_chg": 5,
            },
        ]
    return json.dumps(
        {"status_code": 0, "status_msg": "success", "data": {"stock_list": rows}},
        ensure_ascii=True,
    ).encode("utf-8")
