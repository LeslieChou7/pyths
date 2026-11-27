# API 参考

本文对应当前 `pyths 0.1.0.dev0` 源码（Python >=3.13），覆盖 `pyths.__all__` 的全部公开符号。所有公开符号均可从 `pyths` 导入；下划线模块属于内部实现，不在本参考的稳定接口范围内。支持范围以[兼容性矩阵](compatibility.md)为准，实测结论不会因为参数可编码而扩大。

## 导航与约定

- [客户端 ths](#客户端-ths)：构造、生命周期和全部查询方法。
- [异常](#异常)：分类与捕获方式。
- [数据模型与类型](#数据模型与类型)：按类列出完整字段、类型和默认值。
- [使用说明](usage.md)：业务语义和验证边界；[离线编解码](offline-codec.md)：内部研究工具。

签名中的 `*` 表示后续参数只能按关键字传入。`None` 表示缺失或未知，不等于零。证券代码使用字符串保留前导零；市场标识保留来源值。`received_at` 是本机 UTC 接收时间，不是行情时间。金额单位、币种、统计口径或来源时间未确认时，不自行换算或补齐。

下列联网示例仅展示显式调用，不由默认测试运行；执行时会访问真实服务。无需执行示例即可阅读文档。没有自动登录、交易、后台刷新或全榜遍历。

## 客户端 ths

同步客户端，不承诺线程安全。导入、构造及进入上下文均不联网，不自动读取配置或凭据。

### ths(...)

```python
ths(*, endpoint: tuple[str, int] | None = None,
    app_config: str | None = None, app_info: str | None = None,
    connect_timeout: float = 5, request_timeout: float = 15,
    retries: int = 0) -> ths
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| endpoint | None | TCP `(host, port)`，快照、股票排行、市场概览必需；热榜和龙虎榜不使用。 |
| app_config | None | 调用方提供的 App 配置正文，保留协议要求的 CRLF；TCP 查询必需。 |
| app_info | None | 调用方提供的 CRC 前缀配置值，TCP 查询必需且非空。 |
| connect_timeout | 5 | 正数、有限秒数，连接阶段超时。 |
| request_timeout | 15 | 正数、有限秒数，一次公开查询的总预算，包含解析、连接、握手、子请求及重试。 |
| retries | 0 | 严格整数 0 或 1；仅对可安全重试的网络失败重试，不重试协议、鉴权、业务或限流错误。 |

构造成功返回客户端实例；`__init__(...) -> None`。非法超时或重试值抛 `ValueError`。参数类型不符合签名时也可能产生 Python 原生 `TypeError`，SDK 不承诺将所有类型误用统一转换为 `ValueError`。TCP 配置完整性在查询时检查，不在构造时联网验证。

```python
from pyths import ths

with ths(request_timeout=15, retries=0) as client:
    print(client.closed)  # False；不联网
print(client.closed)  # True
```

### closed、close、上下文方法

| 属性/方法 | 参数 | 返回 | 异常及行为 |
| --- | --- | --- | --- |
| `closed` | 无，只读属性 | bool | 是否已关闭；不联网。 |
| `close()` | 无 | None | 幂等，释放连接并清除会话引用。 |
| `__enter__()` | 无 | Self | 返回当前客户端；关闭后抛 `ThsClientClosedError`。 |
| `__exit__(exc_type, exc, traceback)` | `type[BaseException]` 或 None、BaseException 或 None、TracebackType 或 None | None | 调用 close，不抑制上下文中的异常。推荐使用 with，不直接调用。 |

所有查询方法（包括本地 `get_hot_boards`）在关闭后均抛 `ThsClientClosedError`。

### 查询方法共同异常

联网查询可抛 `ThsNetworkError`（含超时）、`ThsProtocolError`、`ThsAuthenticationError`、`ThsRateLimitError`、`ThsBusinessError`；具体取决于传输和响应路径，并非每个来源都实测出现过全部类别。下面各方法另外列出参数校验异常。详见[异常](#异常)。

### get_quote

```python
get_quote(stock_code: str, *, market: str) -> QuoteSnapshot
```

| 参数 | 必填/默认 | 约束 |
| --- | --- | --- |
| stock_code | 必填，位置或关键字 | 六位 ASCII 数字字符串。 |
| market | 必填，关键字 | 字符串。上交所 A 股用 `"17"`，深交所 A 股用 `"33"`，北交所 A 股用 `"151"`。 |

每次查询一只证券，按请求的市场和代码核对响应身份后返回九字段显示快照。需 TCP 配置，连接和匿名会话可在同客户端内复用。每次返回前发送停止报文。六位代码仅校验格式，调用方须提供对应的市场。非法参数或缺失配置抛 `ValueError`，响应中的证券身份不符抛 `ThsProtocolError`。实测证券见[逐市场验证范围](compatibility.md#证券快照)。

```python
# endpoint、config、app_info 由调用方显式提供；执行会联网。
with ths(endpoint=endpoint, app_config=config, app_info=app_info) as client:
    quote = client.get_quote("000001", market="33")
    print(quote.latest.display if quote.latest is not None else None)
```

### get_stock_ranking

```python
get_stock_ranking(*,
    sort: Literal["change_rate", "turnover", "rapid_change_rate",
                  "large_order_net_volume", "main_net_inflow"] = "change_rate",
    direction: Literal["asc", "desc"] = "desc",
    page: RankingCursor | None = None) -> StockRankingPage
```

| 参数 | 默认 | 约束 |
| --- | --- | --- |
| sort | change_rate | 当日涨跌幅、成交额、快速涨幅、大单净量、主力净流入。 |
| direction | desc | change_rate 支持 asc/desc；其余仅 desc。 |
| page | None | 首屏为 None；续页传本客户端、相同排序产生的 next_page。 |

每页最多24条，固定筛选，不支持自定义市场/页长。每页独立连接并关闭，不影响快照会话。不支持的组合、游标或缺失 TCP 配置抛 `ValueError`，另有共同异常。快速涨幅五分钟窗口来自用户确认；资金定义来自用户指定依据，不代表内部算法已独立证明。

```python
with ths(endpoint=endpoint, app_config=config, app_info=app_info) as client:
    first = client.get_stock_ranking(sort="turnover")
    for row in first.items:
        print(row.stock_code, row.turnover)
    if first.next_page is not None:
        second = client.get_stock_ranking(sort="turnover", page=first.next_page)
```

### get_market_overview

```python
get_market_overview(*, scope: str = "m8_baseline",
    components: Sequence[str] = ("breadth", "limit_counts", "turnover",
                                 "fund_flow", "size_comparison"),
    allow_partial: bool = False) -> MarketOverview
```

| 参数 | 默认 | 约束 |
| --- | --- | --- |
| scope | m8_baseline | 仅支持此冻结范围，不表示已证明全 A 股统计集合。 |
| components | 五组件全部 | 当前运行时仅接受非空 list 或 tuple；元素须为上述名称且不重复。虽然类型标注为 Sequence[str]，不接受其他序列或单字符串。 |
| allow_partial | False | 必须为 bool。False 时组件失败即抛；True 时捕获组件 ThsError 为 error 结果。 |

返回按组件划分的结果；未选择为 not_requested。每来源独立连接，共享总截止时间；广度与涨跌停共同来源去重。不保证原子快照。非法选择或缺失 TCP 配置抛 `ValueError`；部分结果模式不吞掉参数错误或所有 Python 异常。统计范围、资金算法、币种仍有未知；成交额日历当前仅覆盖冻结的2026年。

```python
with ths(endpoint=endpoint, app_config=config, app_info=app_info) as client:
    overview = client.get_market_overview(
        components=("breadth", "limit_counts"), allow_partial=True
    )
    part = overview.breadth
    if part.status == "ok" and part.data is not None:
        print(part.data.rising)
    elif part.error is not None:
        print(part.error.category)
```

### get_hot_boards

```python
get_hot_boards() -> tuple[HotBoard, ...]
```

无参数，返回本地 stock_hour、stock_24h 能力目录；不联网、不做实时服务发现。异常仅关闭状态检查 `ThsClientClosedError`。

```python
with ths() as client:
    for board in client.get_hot_boards():
        print(board.id, board.time_window_label)
```

### get_hot_ranking

```python
get_hot_ranking(*, board: HotBoardId,
    page: HotRankingCursor | None = None) -> HotRankingPage
```

| 参数 | 必填/默认 | 约束 |
| --- | --- | --- |
| board | 必填 | stock_hour（1小时）或 stock_24h（24小时）。 |
| page | None | 当前必须为 None，不支持续页。 |

独立 HTTP 单响应，无需 TCP 配置。不承诺全榜或来源实时更新；latest/change_rate 当前为空。非法榜单或非空游标抛 `ValueError`，另有共同异常。

```python
with ths() as client:
    page = client.get_hot_ranking(board="stock_hour")
    print(page.returned_count)
    for row in page.items:
        print(row.rank, row.stock_code, row.heat)
```

### get_dragon_tiger_list

```python
get_dragon_tiger_list(*, trade_date: date,
    page: DragonTigerCursor | None = None) -> DragonTigerPage
```

| 参数 | 必填/默认 | 约束 |
| --- | --- | --- |
| trade_date | 必填 | 严格 datetime.date 类型，不接受字符串或 datetime 子类；必须在来源返回的日期覆盖内。 |
| page | None | 首屏为 None；续页只能使用本客户端同日期的 next_page。 |

无需 TCP 配置。每次包含日期状态和日榜页两个 HTTP 请求，共享总预算。固定全部榜、页长50，不自动展开详情。非法日期类型/游标抛 `ValueError`；日期超出来源日历也抛 `ValueError`，但此检查需要先联网。另有共同异常。空列表不自动推断非交易日或已披露。

```python
from datetime import date

with ths() as client:
    first = client.get_dragon_tiger_list(trade_date=date(2026, 11, 5))
    print(first.status, first.total)
    if first.next_page is not None:
        second = client.get_dragon_tiger_list(
            trade_date=first.request_date, page=first.next_page
        )
```

### get_dragon_tiger_events

```python
get_dragon_tiger_events(*, entry: DragonTigerEntryRef) -> tuple[DragonTigerEvent, ...]
```

entry 必填，必须来自本客户端日榜条目的 ref；一个 HTTP 请求，返回候选行关联的完整事件（可为空元组）。无需 TCP 配置。不把多原因拆成重复金额。类型不符、跨客户端或无效引用抛 `ValueError`，另有共同异常。

### get_dragon_tiger_detail

```python
get_dragon_tiger_detail(*, event: DragonTigerEventRef) -> DragonTigerDetail
```

event 必填，必须来自本客户端枚举事件的 ref；一个 HTTP 请求，匹配一个完整事件并保留买卖席位原序。无需 TCP 配置。不按席位重新计算汇总金额。类型不符、跨客户端或无效引用抛 `ValueError`，身份或响应结构不符可抛 `ThsProtocolError`，另有共同异常。

两个方法的调用示例：

```python
with ths() as client:
    page = client.get_dragon_tiger_list(trade_date=date(2026, 11, 5))
    if page.items:
        events = client.get_dragon_tiger_events(entry=page.items[0].ref)
        if events:
            detail = client.get_dragon_tiger_detail(event=events[0].ref)
            for seat in detail.buy_seats:
                print(seat.rank, seat.name, seat.buy_value)
```

## 异常

以下类均可从 pyths 导入，除基类继承 Exception 外，其余直接继承 ThsError，没有额外的公开属性或方法。构造参数沿用 Exception 的 `*args`，`str(error)` 返回消息文本。SDK 诊断不附原始报文或凭据。

| 类 | 含义 |
| --- | --- |
| ThsError | SDK 失败基类。 |
| ThsNetworkError | 网络、连接、解析域名失败或超时；受 retries 限制。 |
| ThsProtocolError | 帧、格式、响应关联、身份、解压或必要字段校验失败；不重试。 |
| ThsAuthenticationError | 来源鉴权拒绝；HTTP 401/403 属于此类；不自动登录或绕过。 |
| ThsRateLimitError | 来源限流拒绝，如 HTTP 429；不自动重试或无限重连。 |
| ThsBusinessError | 来源业务失败或其他非成功 HTTP 状态（重定向按协议错误处理）。 |
| ThsClientClosedError | 关闭后的查询或重新进入上下文。 |

`ValueError` 是参数/模型校验错误，不继承 ThsError。超时没有独立公开异常类；部分概览可将它标记为 `MarketComponentError(category="timeout")`。

```python
from pyths import ThsError, ThsNetworkError, ThsRateLimitError

try:
    with ths() as client:
        result = client.get_hot_ranking(board="stock_24h")
except ThsRateLimitError:
    print("来源限流，停止请求")
except ThsNetworkError:
    print("网络失败或超时")
except ThsError as error:
    print(type(error).__name__)
except ValueError:
    print("检查调用参数")
```

## 数据模型与类型

以下表格来自当前公开数据类字段；字段顺序即构造参数顺序，除注明 init=False 外都可按位置或关键字传入。默认“必填”表示构造时必须提供，即使该字段允许 None。数据类均为 frozen，不应赋值修改；修改抛 dataclasses.FrozenInstanceError。没有列出的业务方法；自动生成的比较、repr 等遵循 dataclass 规则。类型标注通常不进行运行时验证，不能把手工构造实例当作已验证来源数据。

模型一般由查询返回；构造模型不联网。游标和来源引用应只消费 SDK 返回实例，不手工构造、持久化或跨客户端使用，下划线字段不是公开契约。

```python
from pyths import QuoteField, MarketMetric, ComponentResult
from decimal import Decimal

field = QuoteField(raw="1.25", format_byte=0, display="1.25", unit=None)
metric = MarketMetric(label="合成示例", raw="3", value=Decimal("3"), precision="exact")
not_requested = ComponentResult()  # 合成示例；不证明任何真实协议数据
```

### 类型别名

| 名称 | 定义 |
| --- | --- |
| HotBoardId | Literal["stock_hour", "stock_24h"] |
| DragonTigerStatus | Literal["published", "pending", "non_trading_day", "unknown"] |

状态类型列出的可能值不等于全部分支已有真实验证；pending 表示来源末日尚未更新且列表为空，其他未确认空列表保持 unknown。

### RankingValue

排行原始显示值及格式字节，不恢复舍入前精度。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| raw | `str` | `必填` |
| display | `str` | `必填` |
| format_byte | `int` | `必填` |
| unit | `str | None` | `None` |

### RankingCursor

仅用于生成它的客户端及同一排序；内部结构不属于公开契约。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |

不透明游标或来源引用：包含内部客户端绑定状态，不提供公开构造签名；仅使用查询返回的实例。

### StockRankingItem

单行证券身份与已确认字段；排名未由服务端给出时为空。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| stock_code | `str` | `必填` |
| market | `str` | `必填` |
| name | `str` | `必填` |
| rank | `int | None` | `必填` |
| latest | `RankingValue | None` | `必填` |
| change_rate | `RankingValue | None` | `必填` |
| turnover | `RankingValue | None` | `必填` |
| rapid_change_rate | `RankingValue | None` | `None` |
| large_order_net_volume | `RankingValue | None` | `None` |
| main_net_inflow | `RankingValue | None` | `None` |

### StockRankingPage

固定筛选单页，不承诺跨页原子一致；接收时间不是行情时间。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| items | `tuple[StockRankingItem, ...]` | `必填` |
| scope | `str` | `必填` |
| sort | `str` | `必填` |
| direction | `str` | `必填` |
| total | `int | None` | `必填` |
| next_page | `RankingCursor | None` | `必填` |
| has_more | `bool | None` | `必填` |
| received_at | `datetime` | `必填` |
| source_time | `datetime | None` | `None` |
| window_minutes | `int | None` | `None` |
| window_source | `str | None` | `None` |
| definition_source | `str | None` | `None` |
| definition_url | `str | None` | `None` |

### QuoteField

原始显示文本、格式字节及应用后缀后的文本。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| raw | `str` | `必填` |
| format_byte | `int` | `必填` |
| display | `str` | `必填` |
| unit | `str | None` | `None` |

### QuoteSnapshot

单证券1269显示快照；币种和行情时间尚未确认。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| stock_code | `str` | `必填` |
| market | `str` | `必填` |
| latest | `QuoteField | None` | `必填` |
| change | `QuoteField | None` | `必填` |
| change_rate | `QuoteField | None` | `必填` |
| open | `QuoteField | None` | `必填` |
| high | `QuoteField | None` | `必填` |
| low | `QuoteField | None` | `必填` |
| previous_close | `QuoteField | None` | `必填` |
| volume | `QuoteField | None` | `必填` |
| turnover | `QuoteField | None` | `必填` |
| received_at | `datetime | None` | `None` |

### MarketMetric

保留原名原文；数值及精度性质仅由已确认来源提供。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| label | `str` | `必填` |
| raw | `str` | `必填` |
| value | `Decimal | None` | `None` |
| unit | `str | None` | `None` |
| precision | `Literal['exact', 'rounded', 'unknown']` | `'unknown'` |
| currency | `str | None` | `None` |
| derivation | `str | None` | `None` |

### MarketComponentMeta

单组件来源与时间；本机接收时间不能替代来源时间。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| source_id | `str` | `必填` |
| received_at | `datetime` | `必填` |
| source_time | `datetime | None` | `None` |
| scope_description | `str | None` | `None` |
| source_time_label | `str | None` | `None` |
| unknowns | `tuple[str, ...]` | `()` |

### MarketComponentError

安全失败分类；不保存URL、凭据、报文或原始异常消息。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| category | `Literal['network', 'protocol', 'authentication', 'rate_limit', 'business', 'timeout', 'unsupported']` | `必填` |

### ComponentResult

未请求、成功及失败互不混淆；失败时没有可冒充成功的数据。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| status | `Literal['ok', 'error', 'not_requested']` | `'not_requested'` |
| data | `T | None` | `None` |
| metadata | `MarketComponentMeta | None` | `None` |
| error | `MarketComponentError | None` | `None` |

### MarketBreadth

来源提供的涨跌分类；缺失不补零，不假定分类穷尽或互斥。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| rising | `MarketMetric | None` | `None` |
| falling | `MarketMetric | None` | `None` |
| unchanged | `MarketMetric | None` | `None` |
| total | `MarketMetric | None` | `None` |
| other | `tuple[MarketMetric, ...]` | `()` |

### MarketLimitCounts

来源的涨跌停指标；具体封板或触及口径保留在原始标签。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| limit_up | `MarketMetric | None` | `None` |
| limit_down | `MarketMetric | None` | `None` |
| other | `tuple[MarketMetric, ...]` | `()` |

### MarketTurnover

当前额与原生比较；不反推参考额或推算本地变化率。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| current | `MarketMetric | None` | `None` |
| comparison | `MarketMetric | None` | `None` |
| reference | `MarketMetric | None` | `None` |
| comparison_basis | `str | None` | `None` |
| reference_time | `datetime | None` | `None` |
| reference_time_label | `str | None` | `None` |
| source_time | `datetime | None` | `None` |
| source_time_label | `str | None` | `None` |
| current_source_value | `Decimal | None` | `None` |
| reference_source_value | `Decimal | None` | `None` |

### MarketFundFlowPart

资金合计的独立来源；两侧缺失不能当成真实零。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| stock_code | `str` | `必填` |
| market | `str` | `必填` |
| net | `MarketMetric` | `必填` |
| source_time | `datetime | None` | `None` |
| source_time_label | `str | None` | `None` |

### MarketFundFlow

来源资金名称与值；不将未知分类自行改称主力资金。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| net | `MarketMetric | None` | `None` |
| inflow | `MarketMetric | None` | `None` |
| outflow | `MarketMetric | None` | `None` |
| classification | `str | None` | `None` |
| sources | `tuple[MarketFundFlowPart, ...]` | `()` |

### MarketSizeSide

大小盘其中一侧；两侧时间可不同且均可未知。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| label | `str` | `必填` |
| value | `MarketMetric | None` | `None` |
| source_time | `datetime | None` | `None` |
| source_time_label | `str | None` | `None` |

### MarketSizeComparison

来源两侧的当前快照，不假定其对应某两个指数。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| large | `MarketSizeSide | None` | `None` |
| small | `MarketSizeSide | None` | `None` |

### MarketOverview

独立组件的组合结果，不承诺跨组件原子快照。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| breadth | `ComponentResult[MarketBreadth]` | `ComponentResult()（每实例独立）` |
| limit_counts | `ComponentResult[MarketLimitCounts]` | `ComponentResult()（每实例独立）` |
| turnover | `ComponentResult[MarketTurnover]` | `ComponentResult()（每实例独立）` |
| fund_flow | `ComponentResult[MarketFundFlow]` | `ComponentResult()（每实例独立）` |
| size_comparison | `ComponentResult[MarketSizeComparison]` | `ComponentResult()（每实例独立）` |
| scope | `Literal['m8_baseline']` | `"m8_baseline"（init=False，不接受构造参数）` |

### HotBoard

本地已验证能力配置，并非服务端实时发现。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| id | `HotBoardId` | `必填` |
| name | `str` | `必填` |
| time_window_label | `str` | `必填` |
| scope_description | `str` | `必填` |
| object_type | `Literal['stock']` | `'stock'` |
| pagination | `Literal['single_response']` | `'single_response'` |

### HotMetric

源文本、可确认Decimal及派生显示；unit未知不补造。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| raw | `str` | `必填` |
| value | `Decimal` | `必填` |
| display | `str | None` | `必填` |
| unit | `str | None` | `None` |
| derivation | `str | None` | `None` |

### HotRankingCursor

不透明续页类型；当前来源无续页，所有非空游标均被拒绝。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |

不透明游标或来源引用：包含内部客户端绑定状态，不提供公开构造签名；仅使用查询返回的实例。

### HotRankItem

源顺序条目；市场不猜测，排名不由行号生成。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| stock_code | `str` | `必填` |
| market | `str | None` | `必填` |
| name | `str | None` | `必填` |
| rank | `int | None` | `必填` |
| heat | `HotMetric | None` | `必填` |
| rank_change | `int | None` | `必填` |
| latest | `HotMetric | None` | `None` |
| change_rate | `HotMetric | None` | `None` |

### HotRankingPage

单响应快照；100条不代表全榜，接收时间不代表来源时间。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| board | `HotBoardId` | `必填` |
| items | `tuple[HotRankItem, ...]` | `必填` |
| received_at | `datetime` | `必填` |
| source | `str` | `必填` |
| unknowns | `tuple[str, ...]` | `必填` |
| total | `int | None` | `None` |
| next_page | `HotRankingCursor | None` | `None` |
| has_more | `bool | None` | `None` |
| source_time | `datetime | None` | `None` |
| source_time_label | `str | None` | `None` |
| pagination | `Literal['single_response']` | `'single_response'` |

只读属性 `returned_count: int` 返回 len(items)，无参数、不联网，不代表全榜总数。

### DragonTigerReason

保留来源原因ID和全文；多原因仍属于同一源事件。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| id | `str` | `必填` |
| content | `str` | `必填` |

### DragonTigerEntryRef

列表候选引用，尚不足以唯一标识事件；日期仅为请求上下文。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| market | `str` | `必填` |
| stock_code | `str` | `必填` |
| request_date | `date` | `必填` |
| range_days | `int` | `必填` |

不透明游标或来源引用：包含内部客户端绑定状态，不提供公开构造签名；仅使用查询返回的实例。

### DragonTigerEntry

保留列表原序、范围天数和来源金额，不猜上榜理由。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| ref | `DragonTigerEntryRef` | `必填` |
| stock_name | `str` | `必填` |
| buy_value | `Decimal | None` | `必填` |
| sell_value | `Decimal | None` | `必填` |
| net_value | `Decimal | None` | `必填` |
| change | `Decimal | None` | `必填` |
| net_rate | `Decimal | None` | `必填` |
| hot_rank | `int | None` | `必填` |
| limit_reason | `str | None` | `必填` |
| amount_unit | `None` | `None` |

### DragonTigerCursor

默认全部榜固定筛选的续页；绑定客户端、日期和页大小。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| request_date | `date` | `必填` |

不透明游标或来源引用：包含内部客户端绑定状态，不提供公开构造签名；仅使用查询返回的实例。

### DragonTigerCalendar

来源日期覆盖及最后日期更新状态；time单位保持未知。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| trade_days | `tuple[date, ...]` | `必填` |
| last_date | `date` | `必填` |
| last_update_status | `bool` | `必填` |
| source_time_raw | `int | None` | `必填` |
| received_at | `datetime` | `必填` |

### DragonTigerPage

请求日期不是服务端回显日期；空列表不推导披露状态。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| items | `tuple[DragonTigerEntry, ...]` | `必填` |
| total | `int` | `必填` |
| stock_count | `int | None` | `必填` |
| page | `int` | `必填` |
| size | `int` | `必填` |
| next_page | `DragonTigerCursor | None` | `必填` |
| has_more | `bool` | `必填` |
| status | `DragonTigerStatus` | `必填` |
| request_date | `date` | `必填` |
| received_at | `datetime` | `必填` |
| source_date | `date | None` | `None` |

### DragonTigerEventRef

完整复合身份；不是伪造的服务端事件ID。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| market | `str` | `必填` |
| stock_code | `str` | `必填` |
| request_date | `date` | `必填` |
| range_days | `int` | `必填` |
| range_type | `str` | `必填` |
| start_date | `date` | `必填` |
| end_date | `date` | `必填` |
| reasons | `tuple[DragonTigerReason, ...]` | `必填` |

不透明游标或来源引用：包含内部客户端绑定状态，不提供公开构造签名；仅使用查询返回的实例。

### DragonTigerEvent

事件描述符，多原因共享原生汇总，不重复拆分金额。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| ref | `DragonTigerEventRef` | `必填` |
| stock_name | `str` | `必填` |
| reasons | `tuple[DragonTigerReason, ...]` | `必填` |
| buy_value | `Decimal | None` | `必填` |
| sell_value | `Decimal | None` | `必填` |
| net_value | `Decimal | None` | `必填` |
| amount_unit | `None` | `None` |

### DragonTigerSeat

方向内源席位；id/name不用于跨方向合并。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| id | `str` | `必填` |
| org_id | `str | None` | `必填` |
| name | `str` | `必填` |
| short_name | `str | None` | `必填` |
| direction | `Literal['buy', 'sell']` | `必填` |
| rank | `int` | `必填` |
| buy_value | `Decimal | None` | `必填` |
| sell_value | `Decimal | None` | `必填` |
| net_value | `Decimal | None` | `必填` |
| amount_unit | `None` | `None` |

### DragonTigerDetail

恰好匹配一个完整事件的详情，不暗中合计席位。

| 字段 / 构造参数 | 类型 | 默认值 |
| --- | --- | --- |
| ref | `DragonTigerEventRef` | `必填` |
| stock_name | `str` | `必填` |
| reasons | `tuple[DragonTigerReason, ...]` | `必填` |
| buy_value | `Decimal | None` | `必填` |
| sell_value | `Decimal | None` | `必填` |
| net_value | `Decimal | None` | `必填` |
| buy_seats | `tuple[DragonTigerSeat, ...]` | `必填` |
| sell_seats | `tuple[DragonTigerSeat, ...]` | `必填` |
| received_at | `datetime` | `必填` |
| amount_unit | `None` | `None` |

### 模型校验异常与字段语义

以下自定义构造校验失败抛 ValueError，其余数据类没有额外业务校验方法；Python 构造参数缺失/重复等仍可能抛 TypeError。

| 类 | 构造校验 |
| --- | --- |
| MarketMetric | value 非空时必须是有限 Decimal；precision 只能是 exact/rounded/unknown。 |
| MarketComponentMeta | received_at、非空 source_time 必须包含时区。 |
| MarketComponentError | category 只能为 network/protocol/authentication/rate_limit/business/timeout/unsupported。 |
| ComponentResult[T] | ok 要求 data、metadata 非空且 error 为空；error 要求 data 为空且 error 非空；not_requested 要求 data、metadata、error 全为空。 |
| MarketTurnover | 非空时间须含时区；非空来源数值须为有限 Decimal。 |
| MarketFundFlowPart、MarketSizeSide | 非空 source_time 必须含时区。 |

QuoteField、RankingValue 的 raw 为来源文本，display 为按来源格式产生的显示值，format_byte 为来源格式字节；不反推舍入前金额。QuoteSnapshot 的 volume 单位为手、change_rate 为百分数；币种未知。排行行的 rank 当前为空；各可选指标未提供时保留 None。

StockRankingPage 的 window_minutes/window_source 用于记录快速涨幅用户确认的窗口；definition_source/definition_url 记录资金定义的用户指定来源，不等于服务端算法证明。游标仅用于同一客户端和查询，不保证跨页原子一致。

MarketMetric 的 label 保留来源名，precision 表示精度性质；derivation 标识本地派生规则。MarketComponentMeta 的 unknowns 保留已知未决问题。MarketOverview 五个属性类型中的 T 分别对应各组件数据类；scope 为只读固定范围。成交额 comparison/reference 不补造未知参考值，资金 sources 分别保存两路来源，大小盘当前仅对应已验证指数快照，不返回曲线。

HotMetric 的 value 为 Decimal，display 可以是派生值；热度算法、单位和排名变化比较基准未知。HotRankingPage 的 total/has_more/next_page、source_time 当前为空；保留源顺序和重复条目。

龙虎榜 request_date 仅为查询上下文，不代表来源回显日期；source_date 当前为空。Calendar.source_time_raw 单位未知且没有独立的公开日历查询方法。Entry.limit_reason 是涨跌停题材，不是龙虎榜事件原因；EventRef 的日期区间、range_type 与 reasons 共同组成事件身份，不是服务端事件 ID。Entry/Event/Seat/Detail 的金额保留原生 Decimal，amount_unit 当前固定 None，币种未知；多原因不拆分金额，买卖席位不跨方向合并。

## 维护与证据边界

本参考描述 SDK 代码契约，既不新增协议发现，也不替代真实兼容性验证。模型字段及客户端签名分别以 src/pyths/__init__.py、client.py、models.py、_market_models.py、_hot_models.py、_dragon_models.py 和 errors.py 为依据。接口扩展时应同步更新本文、使用说明及兼容性矩阵。

## M15涨停聚焦

M15新增`get_limit_capabilities`、`get_limit_pool`、`get_limit_focus_summary`及类型化筛选、结果和游标，详见[涨停聚焦](limit-focus.md)。24个精确组合有双平台公共入口证据，盘中自然开板/回封样本已补；同日盘后与列明未证分支仍待补齐，不将精确矩阵外推为任意组合兼容。

## M14公开入口

`ths.get_stock_anomalies(*, kind, page=None)`返回StockAnomalyPage；`ths.get_trading_status_events(*, kind, page=None)`返回TradingStatusPage。类型均从pyths导出，详见[事件查询](events.md)。游标绑定客户端与kind，不自动续页；本功能固定零重试。

## 集合竞价当日榜单

`ths.get_auction_ranking(*, kind, trade_date)` 返回 `AuctionRankingPage`。显式传入上海当日日期和榜单种类 `one_price`（竞价一字板）、`yesterday_limit_up`（昨日涨停）或 `weak_to_strong`（弱转强）。每次调用查询默认首屏一次，最多请求 20 行。返回来源列定义、原序行、来源 total 和 current_page，以及请求日期和 UTC 接收时间。来源行中的 date 原样保留。2026-11-19 已验证 Windows 与 Docker Linux 的形成中及最终首屏。业务成功且原始 data 为 null 时，source_data_null 为真，行列为空，total 和 current_page 为 None。历史与增页待验。

### 板块快照与有界轮询

`get_auction_sector_changes(side=..., trade_date=...)` 单次读取看多（bullish）或看空（bearish）的可见板块快照。每条保留板块市场、代码、名称、指标原值及来源提供的关联证券。

`watch_auction_sector_changes(side=..., trade_date=..., interval=..., max_duration=..., max_requests=...)` 返回同步迭代器。首次结果为基线，随后每轮报告进入、更新和离开可见集合的板块，同一快照仍返回当次接收时间。间隔 5–600 秒，总时长不超过 600 秒，最多 120 次单侧请求；这些是 SDK 资源限制。预算、截止或客户端关闭时迭代结束。调用方可在两次取值之间调用迭代器 close() 主动停止。来源限流或请求失败会终止迭代并抛出对应异常。轮询之间的变化可能漏掉；2026-11-19 跨 09:25 的连续采样观察到进入、更新及离开。
