"""显式获取一次实验性市场概览；使用前查看兼容性限制。"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pyths import ThsError, ths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--app-config", type=Path, required=True)
    parser.add_argument("--app-info", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument(
        "--components",
        nargs="+",
        choices=("breadth", "limit_counts", "turnover", "fund_flow", "size_comparison"),
        default=["breadth", "limit_counts", "turnover", "fund_flow", "size_comparison"],
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("必须显式传入 --live 才会读取配置和连接行情服务")
    if len(set(args.components)) != len(args.components):
        parser.error("组件不能重复")
    try:
        with ths(
            endpoint=(args.host, args.port),
            app_config=args.app_config.read_bytes().decode("utf-8"),
            app_info=args.app_info,
        ) as client:
            overview = client.get_market_overview(
                components=tuple(args.components), allow_partial=args.allow_partial
            )
            print(json.dumps(asdict(overview), ensure_ascii=False, default=str))
    except ThsError as error:
        raise SystemExit(type(error).__name__) from None


if __name__ == "__main__":
    main()
