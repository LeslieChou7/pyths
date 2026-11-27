# pyths

用于同花顺只读行情查询的实验性 Python SDK，提供同步 API、类型化数据模型和离线报文编解码。Python >=3.13，零运行时依赖，可在无头环境中使用，运行时无需启动 App。

公开入口为 `from pyths import ths`。SDK 不提供账号登录、交易或后台自动刷新。

## 支持能力

| 能力 | 公开方法 | 当前范围 |
| --- | --- | --- |
| 证券快照 | `get_quote` | 九字段显示快照；已验证 `000001`、`000002`、`000063`，市场 `33` |
| 股票排行 | `get_stock_ranking` | 涨幅、跌幅、成交额、快速涨幅、大单净量、主力净流入；显式分页 |
| 市场概览 | `get_market_overview` | 涨跌家数、涨跌停、成交额比较、资金、大小盘；可选择组件 |
| 股票热榜 | `get_hot_boards` / `get_hot_ranking` | 本地榜单目录及“大家都在看”1 小时、24 小时榜 |
| 龙虎榜 | `get_dragon_tiger_list` / `get_dragon_tiger_events` / `get_dragon_tiger_detail` | 指定日期列表、候选行事件与单事件详情 |
| 板块统计 | `get_sector_capabilities` / `get_sector_ranking` / `get_sector_constituents` | 30个精确参数/页号组合，异常历史部分盘内组合拒绝；见兼容性矩阵 |
| 异动与停复牌 | `get_stock_anomalies` / `get_trading_status_events` | 当前异动首屏，历史异动及停复牌最多两页 |
| 涨停聚焦 | `get_limit_capabilities` / `get_limit_pool` / `get_limit_focus_summary` | 已验证的日期、筛选、排序和分页组合 |
| 集合竞价 | `get_auction_ranking` / `get_auction_sector_changes` / `watch_auction_sector_changes` | 当日榜、单侧快照、有界轮询 |

历史发布前验收覆盖 Android 11.50.04 样本及指定 Windows、Docker Linux 场景。日期、市场、样本和功能限制见[兼容性矩阵](docs/compatibility.md)。本次工程检查结果与历史实网证据分别记录。

## 安装

需要 Python 3.13 或更高版本。克隆或下载本项目的 GitHub 源码，在源码根目录创建环境。

```sh
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install .
```

POSIX shell：

```sh
.venv/bin/python -m pip install .
```

当前版本为 `0.1.0.dev0`，尚未发布。请使用本仓库源码或可信的本地构建 wheel，不要直接安装来源未经确认的 PyPI 同名包。以上为安装方式，已验证的运行环境以兼容性矩阵为准。

## 快速上手

以下示例只读取本地能力目录，不访问行情服务：

```python
from pyths import ths

with ths() as client:
    boards = client.get_hot_boards()
    print(boards)
```

显式调用查询方法才会联网。例如，获取小时热榜无需 TCP 配置：

```python
from pyths import ths

with ths(request_timeout=15, retries=0) as client:
    page = client.get_hot_ranking(board="stock_hour")
    for item in page.items:
        print(item.stock_code, item.market, item.heat)
```

快照、股票排行与市场概览需要显式提供 `endpoint`、`app_config` 和 `app_info`；SDK 不自动读取 App 文件或登录态。App 配置由调用者本地提供，成交额比较使用内置 2026 年日历。配置方式及完整示例见[使用说明](docs/usage.md)。仓库内的联网示例须传入 `--live`，例如：

```sh
python examples/hot_ranking.py --live --board stock_hour
```

## 数据与调用约定

- 股票代码保留字符串和前导零；数值保留来源文本、显示值、已确认单位及派生标记，未知值保持为空，不恢复隐藏精度或猜测币种。
- `received_at` 是本机 UTC 接收时间，不是来源行情时间。跨页、跨组件及多次调用不保证同时快照，热榜返回条数不代表全榜总数。
- 默认只获取一次响应或一页，不自动遍历、轮询或展开详情；分页游标仅用于生成它的客户端与对应查询。
- 导入、构造及进入上下文不联网；上下文退出释放连接，`close()` 可重复调用，关闭后查询抛出 `ThsClientClosedError`。不承诺线程安全。
- 默认连接超时 5 秒、单次公开调用总超时 15 秒、重试 0 次；可显式允许最多 1 次安全的只读网络失败重试。鉴权、协议及限流错误不自动绕过。

## 文档

- [API 参考](docs/api-reference.md)：公开类、方法、参数、返回类型与异常。
- [使用说明](docs/usage.md)：配置、各业务调用及数据语义。
- [兼容性矩阵](docs/compatibility.md)：真实验证范围、证据与未知项。
- [验证工具](docs/validation.md)：独立安装及容器验证流程。

## 开发与验证

在本仓库根目录安装开发依赖并执行离线工程检查：

```sh
python -m pip install -e ".[dev]"
python tools/check.py
```

请使用虚拟环境中的 Python。检查包含离线测试、本地网络替身、代码风格、类型、构建及独立安装验证，不请求生产服务。真实网络验证单独显式启用；合成样本通过不能扩大真实兼容范围。

## 许可证

Copyright 2026 lesliechou and contributors.

本项目有权授权的原创代码、文档与示例采用 [Apache License 2.0](LICENSE)，SPDX 标识为 `Apache-2.0`。允许按许可条款使用、修改和商业分发，软件按原样提供，不作担保。分发时须附许可证、保留相关声明，并对修改文件注明修改；一并保留 [NOTICE](NOTICE) 和 [第三方来源与发布核查](THIRD_PARTY_NOTICES.md)。第三方内容不因本声明而被重新授权。

本项目是非官方独立项目。交易日历来源、测试样本和分发范围见[第三方材料说明](THIRD_PARTY_NOTICES.md)。
