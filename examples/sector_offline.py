"""仅解码显式指定的本地板块JSON；内部研究接口，不访问网络。"""

import argparse
import json
from pathlib import Path

from pyths._sector_codec import decode_sector_response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--kind", choices=("block", "stock"), required=True)
    args = parser.parse_args()
    with args.fixture.open("rb") as source:
        body = source.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024:
        parser.error("local fixture exceeds decoder size limit")
    page = decode_sector_response(body, kind=args.kind)
    print(
        json.dumps(
            {
                "source": "explicit_local_file",
                "network_verified": False,
                "source_total": page.total,
                "returned_count": len(page.rows),
                "items": [
                    {
                        "code": row.code,
                        "market": row.market,
                        "name": row.name,
                        "change_rate": None
                        if row.change_rate is None
                        else str(row.change_rate),
                        "main_net_inflow": None
                        if row.main_net_inflow is None
                        else str(row.main_net_inflow),
                        "turnover": None if row.turnover is None else str(row.turnover),
                        "turnover_rate": None
                        if row.turnover_rate is None
                        else str(row.turnover_rate),
                    }
                    for row in page.rows
                ],
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
