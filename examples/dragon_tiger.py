"""显式只读龙虎榜示例；不自动遍历详情或轮询。"""

import argparse
from datetime import date

from pyths import ths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--first-detail", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("必须显式传入 --live 才请求服务")
    with ths() as client:
        page = client.get_dragon_tiger_list(trade_date=args.date)
        print(page.request_date, page.status, len(page.items), page.total)
        for entry in page.items:
            print(
                entry.ref.market,
                entry.ref.stock_code,
                entry.stock_name,
                entry.ref.range_days,
            )
        if args.first_detail and page.items:
            events = client.get_dragon_tiger_events(entry=page.items[0].ref)
            if events:
                detail = client.get_dragon_tiger_detail(event=events[0].ref)
                print(detail.ref.start_date, detail.ref.end_date, detail.reasons)
                print(
                    "原生金额（单位未知）",
                    detail.buy_value,
                    detail.sell_value,
                    detail.net_value,
                )


if __name__ == "__main__":
    main()
