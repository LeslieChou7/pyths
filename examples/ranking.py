"""显式获取一页排行；不默认连接或自动遍历全榜。"""

import argparse
import json
from pathlib import Path
from typing import Literal, cast

from pyths import ThsError, ths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--app-config", type=Path, required=True)
    parser.add_argument("--app-info", required=True)
    parser.add_argument(
        "--sort", choices=("change_rate", "turnover"), default="change_rate"
    )
    parser.add_argument("--direction", choices=("asc", "desc"), default="desc")
    args = parser.parse_args()
    if not args.live:
        parser.error("必须显式传入 --live 才会读取配置和连接行情服务")
    if args.sort == "turnover" and args.direction != "desc":
        parser.error("成交额仅支持降序")
    try:
        with ths(
            endpoint=(args.host, args.port),
            app_config=args.app_config.read_bytes().decode("utf-8"),
            app_info=args.app_info,
        ) as client:
            page = client.get_stock_ranking(
                sort=cast(Literal["change_rate", "turnover"], args.sort),
                direction=cast(Literal["asc", "desc"], args.direction),
            )
            print(
                json.dumps(
                    {
                        "total": page.total,
                        "has_more": page.has_more,
                        "received_at": page.received_at.isoformat(),
                        "items": [
                            {
                                "code": item.stock_code,
                                "market": item.market,
                                "name": item.name,
                                "latest": item.latest.display if item.latest else None,
                                "change_rate": item.change_rate.display
                                if item.change_rate
                                else None,
                                "turnover": item.turnover.display
                                if item.turnover
                                else None,
                            }
                            for item in page.items
                        ],
                    },
                    ensure_ascii=False,
                )
            )
    except ThsError as error:
        # 不输出可能包含诊断上下文的异常原文。
        raise SystemExit(type(error).__name__) from None


if __name__ == "__main__":
    main()
