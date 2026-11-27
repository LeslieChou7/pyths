"""显式联网示例；App配置由用户本地文件提供，不自动读取凭据。"""

import argparse
from pathlib import Path

from pyths import ths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--app-config", required=True, type=Path)
    parser.add_argument("--app-info", required=True)
    parser.add_argument("--stock-code", default="000001")
    parser.add_argument("--market", default="33")
    args = parser.parse_args()
    if not args.live:
        parser.error("explicit --live required")
    config = args.app_config.read_bytes().decode("utf-8")
    with ths(
        endpoint=(args.host, args.port), app_config=config, app_info=args.app_info
    ) as client:
        quote = client.get_quote(args.stock_code, market=args.market)
        print(quote)


if __name__ == "__main__":
    main()
