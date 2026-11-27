"""显式请求一个股票热榜；普通运行不会联网，不轮询或附加行情查询。"""

import argparse
import json
from typing import cast

from pyths import HotBoardId, ThsError, ths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--board", choices=("stock_hour", "stock_24h"), required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("必须显式传入 --live 才会请求热榜服务")
    try:
        with ths() as client:
            page = client.get_hot_ranking(board=cast(HotBoardId, args.board))
        print(
            json.dumps(
                {
                    "board": page.board,
                    "returned_count": page.returned_count,
                    "total": page.total,
                    "has_more": page.has_more,
                    "received_at": page.received_at.isoformat(),
                    "source_time": None,
                    "unknowns": page.unknowns,
                    "items": [
                        {
                            "code": item.stock_code,
                            "market": item.market,
                            "name": item.name,
                            "rank": item.rank,
                            "heat_raw": item.heat.raw if item.heat else None,
                            "heat_display": item.heat.display if item.heat else None,
                            "rank_change": item.rank_change,
                        }
                        for item in page.items
                    ],
                },
                ensure_ascii=False,
            )
        )
    except ThsError as error:
        raise SystemExit(type(error).__name__) from None


if __name__ == "__main__":
    main()
