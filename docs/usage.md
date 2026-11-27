# 实验性只读接口

## 证券快照

`client.get_quote("920679", market="151")` 查询北交所前进科技。沪市 A 股使用 `market="17"`，深市 A 股使用 `market="33"`。代码和市场均传字符串，每次返回一只证券的快照。[2026-11-27 分市场验证](compatibility.md#证券快照)

## M11 历史验证范围（2026-11-10）

现有公开API已用同一wheel完成Windows与Docker Linux的盘中/盘后跨功能顺序调用、关闭和新客户端初始化；Linux六种排行的邻页及测试偏移末页也已验证。具体证券、榜单、日期、单位及证据边界见[兼容性矩阵](compatibility.md)，下列M7—M10段落仍适用各自的参数白名单。

本轮不新增参数或API：报价仅声明000001、000002、000063/33；排行仍固定已验证筛选，热榜仅stock_hour/stock_24h，龙虎榜真实日榜/详情本轮仅2026-11-05及002086事件。未验证的日期、市场、全榜完整性、来源行情时间及服务端限制不因M11完成而扩充。真实示例仍须显式`--live`，构造、导入和默认测试不联网。

## M9：股票热榜

固定样本的1小时/24小时榜已用同一wheel完成Windows盘中及盘后验证；兼容性与保留未知见`compatibility.md`。每次显式调用只取一个响应，不承诺全榜或来源实时更新。

```python
from pyths import ths

with ths(request_timeout=15, retries=0) as client:
    boards = client.get_hot_boards()  # 本地能力目录，不联网
    hour = client.get_hot_ranking(board="stock_hour")  # 此处显式联网
    day = client.get_hot_ranking(board="stock_24h")
```

两榜固定为App“热股→大家都在看”的1小时、24小时来源。榜单ID是SDK名称，目录不是实时服务发现。不需要TCP端点/App配置，不登录、不复用TCP会话、不依赖App进程。当前单响应返回全部已收到条目，不支持非空`page`或自定义排序。

`HotRankingPage.items`保留源顺序、重复记录和服务端排名；`returned_count`仅本响应数量，`total/has_more/next_page`为空，不能据此宣称全榜。来源未提供更新时间，`received_at`仅UTC接收时间。每次调用显式请求但不保证来源数据更新，无跨调用缓存或自动刷新。

条目`stock_code`保留前导零，`market`仅原始来源标识，不代表所有市场可调用`get_quote`。`heat.raw/value`分别是源文本和Decimal，`heat.display`按页面Number/floor/toFixed规则派生，`derivation`标明计算；热度算法及计量单位未知。`rank_change`保留有符号源值，正值对应页面向上、负值向下，比较基准未知。来源缺失字段保留None，不补0。

当前热榜JSON不含最新价和涨跌幅，因此`latest/change_rate`为None；App的涨跌幅使用独立原生行情通道，本接口不隐式追加逐证券查询。尚无概念、ETF、快速飙升、历史榜或后台轮询支持。

关闭后调用抛`ThsClientClosedError`，非法榜单和非空游标在发送前抛`ValueError`。HTTP网络、协议、鉴权、限流、业务错误沿用已有分类；默认不重试，仅`retries=1`允许一次安全网络失败重试，所有尝试共享总截止时间。默认测试和普通运行示例不请求生产服务。

## M8实验性市场概览（固定范围已验收）

`get_market_overview(*, scope="m8_baseline", components=("breadth", "limit_counts", "turnover", "fund_flow", "size_comparison"), allow_partial=False)` 按需获取五组件，支持选择非空、不重复的组件子集。仅冻结的 `m8_baseline` 可用，不等于已确认的全 A 股统计集合。

```python
from pyths import ths

with ths(endpoint=endpoint, app_config=config, app_info=app_info) as client:
    overview = client.get_market_overview(components=("breadth", "limit_counts"))
    if overview.breadth.data is not None:
        print(overview.breadth.data.rising)
```

每个组件含 `status`、`data`、`metadata` 和 `error`。未选择为 `not_requested`；默认被请求组件失败即抛出已有分类异常；显式 `allow_partial=True` 时失败组件为 `error`，错误仅保留安全类别。元数据分别记录来源、UTC 接收时间及未知项，不保证跨组件或两路资金的原子快照。来源没有完整时间时只保留 `source_time_label`，不把本机时间当行情时间。

完整调用通常需要六个业务子请求；同时选择涨跌家数和涨跌停仅请求一次共同来源。各来源独立连接并关闭，共用 `request_timeout` 总截止时间与重试预算，默认不重试；不跨调用缓存、不后台刷新。原快照及排行接口保持各自的会话策略。

`MarketMetric.raw/value/unit/precision/currency/derivation` 分别表示文本、可选 Decimal 数值、单位、精度性质、币种和派生规则。未知保持 `None` 或 `unknown`；显示值不能恢复精确金额。成交额差额复现 App 的未舍入值相减及显示规则，标为 `app_current_minus_reference`，并保留两个来源值、来源及参考日期/分钟。`comparison_basis` 区分上一交易日同刻、全日和同刻缺失后的末值回退。当前交易日历只覆盖样本的 2026 年，不能据此查询其他年度或首日跨年参考。

资金保留两路 DDE 原值、原始时间标签及按 App float32 规则生成的显示合计；正值超过 App 的 `0.01f` 阈值时显示 `+` 前缀，派生标记 `app_sum_float32_dde`。2026-11-03 盘后 App 与 SDK 的深市来源输入不同，同样输入的显示计算一致；不承诺不同来源的实时显示逐字一致。资金分类算法、币种、统计集合仍未知。大小盘只返回样本关联的沪深300/中证1000当前涨跌幅，不提供曲线或指数编制规则。

同一 wheel 的盘中及盘后完整五组件调用均已验收；盘中来源跨分钟差异分别保留，盘后五组件与 App 输入/显示对应。验收范围与保留未知见兼容性说明。显式运行示例：

```powershell
python examples/market_overview.py --live --host mobi2.123ths.com --port 9528 --app-config local/app-config.txt --app-info G037.09.127.1.32 --components breadth limit_counts
```

省略 `--components` 将请求五组件。该命令请求真实生产服务，普通测试不执行它。支持范围见[兼容性说明](compatibility.md)。

## M7实验性股票排行

`get_stock_ranking(*, sort="change_rate", direction="desc", page=None)`固定m7_baseline筛选、每页24条；支持change_rate/desc涨幅、change_rate/asc跌幅、turnover/desc成交额，以及rapid_change_rate/desc快速涨幅（m10_rapid筛选）。M7已验证的范围与剩余限制见兼容性说明。

```python
with ths(endpoint=endpoint, app_config=config, app_info=app_info) as client:
    first = client.get_stock_ranking()
    for item in first.items:
        print(item.stock_code, item.market, item.name, item.change_rate)
    if first.next_page is not None:
        second = client.get_stock_ranking(page=first.next_page)
```

游标仅用于产生它的客户端及相同排序，不持久化或手工构造。每页独立连接并匿名握手，完成/失败关闭；get_quote会话独立保留。单页与重试共用截止时间，不自动遍历全榜或去重。

StockRankingPage含服务端顺序条目、可选总数、续页及UTC接收时间；来源时间未知。条目rank当前为空，latest/change_rate/turnover为RankingValue或None，保留raw/display/format_byte及已确认单位，不恢复隐藏精度。其他市场出现在榜中不扩大get_quote支持。末页无续页；不一致页边界抛ThsProtocolError，不当作空榜。

M5容器和独立安装验证入口见[验证工具](validation.md)；实际支持范围以兼容性矩阵为准。

公开入口为`from pyths import ths`，查询方法为`get_quote(stock_code, *, market)`。
调用时指定六位 ASCII 证券代码字符串及市场字符串（沪 `17`、深 `33`、北 `151`），每次读取一只证券。保留代码前导零。各市场实测样本见[证券快照](compatibility.md#证券快照)。
返回不可变QuoteSnapshot，九项字段为QuoteField或None；保留raw、format_byte、display和已确认unit。成交数量unit为手、涨跌幅unit为%，价格和金额币种保留未知。
成交量额为舍入显示值，不是精确数值；币种和行情时间尚未确认。

## 显式配置与生命周期

构造器参数endpoint、app_config和app_info须由调用方显式提供，业务调用前检查是否齐全。
endpoint是(host, port)元组；app_config是已确认格式的配置正文，app_info是CRC前缀配置值。
SDK不提取App文件或登录态，不持久化服务端passport或sessionId。目前只尝试无凭据初始化，不支持账号登录。
指定样本的无凭据握手及000001/33查询已在M4完成真实验收；M5修复盘中关联和接收空封装后，三证券、双平台、30分钟观察及新的App页面对照均已验收。不推广其他市场、版本或更长会话。

M5新增盘中证据：26字节初始化行情头可能为frame0。SDK仅在当前正包号、当前实例和表内证券/市场均匹配时接受该已观察分支；其他错关联继续失败。
每次快照返回前使用独立包号发送App已有的空pageList停止报文，不等待未知ACK。
本连接已完成实例的package=-1/frame2267残留更新校验身份后丢弃，不能完成新查询。
这替代M4阶段统一要求frame2267回显的规则；真实矩阵与观察窗口见兼容性记录。

已验证配置在固定样本App字段基础上包含
`FunClientSupport=01111111111000111111111101111101001111101`。
该值来自目标App，研究SDK仅验证其中1269查询路径，不宣称实现全部能力位。
兼容性矩阵提供样本哈希、字段与会话限制。received_at为本机收到行情帧的UTC时间，非服务端行情时间。

导入、构造和进入上下文不联网，首次查询才解析域名、连接并握手。
close幂等关闭连接并清除会话引用，关闭后查询抛ThsClientClosedError。不承诺线程安全。

connect_timeout默认5秒；request_timeout默认15秒，覆盖解析、连接、握手、请求与可选重试。
域名解析在可终止并回收的子进程中执行，数字IP地址不启动解析子进程。
接收端消费App代码支持的合法13字节零长度空封装，不将其作为行情，不延长单次操作总预算；发送空业务帧仍拒绝。
retries默认为0，最多1，只对只读查询的网络错误重试，重新建立会话，所有尝试共用截止时间。
鉴权拒绝、协议错误及未知必要响应不重试；不会自动绕过限制或无限重新初始化。

## 检查范围

默认pytest包含unit及本地TCP integration，不连接生产服务，也不依赖Android、ADB或Frida。
本地替身覆盖完整公开调用链、错关联、鉴权拒绝及连接释放。
真实验证必须独立显式启用，SDK示例和普通检查不自动发出生产请求。

## 已验证配置示例

安装 SDK 后，准备本地配置文件，并用实际端点和 app-info 替换下例参数。

```powershell
python examples/quote.py --live --host mobi2.123ths.com --port 9528 --app-config local/app-config.txt --app-info G037.09.127.1.32
```

命令会请求生产服务；示例不会由普通测试自动执行。配置文件保留协议要求的CRLF行分隔。

## M10 龙虎榜（指定范围已实测）

已验证Windows独立安装、App停止后的2026-11-05两页列表与002086单事件，以及2026-11-06待更新空列表；前50条列表和单事件公共字段与固定样本App精确一致。Windows及禁网Docker Linux各536项与完整工程检查通过；Linux真实联网留M11。其他日期、真实已披露空榜、真实鉴权/限流及完整市场覆盖尚未验证。

```python
from datetime import date
from pyths import ths

with ths() as client:
    page = client.get_dragon_tiger_list(trade_date=date(2026, 11, 5))
    if page.items:
        events = client.get_dragon_tiger_events(entry=page.items[0].ref)
        if events:
            detail = client.get_dragon_tiger_detail(event=events[0].ref)
```

每次日榜调用包含来源日期状态和当前列表页两个请求；事件枚举与单事件详情各一个请求，各自共享公开调用的总截止时间。三者均无需TCP配置，不携带账号凭据，不跨调用缓存。默认页长50，仅支持固定全部榜及来源日期覆盖内的显式日期，续页使用page.next_page；不自动拉全榜或展开每条详情。

列表ref仅标识证券、请求日期和统计天数，不是完整事件；limit_reason为涨跌停题材，不是龙虎榜上榜原因。显式事件枚举后才生成含区间和完整原因集合的事件引用，多原因共享一个来源事件及金额，席位按买卖方向分别保留。引用和游标绑定生成它们的客户端。

buy_value/sell_value/net_value保留原生Decimal，金额单位和币种仍未知，不按席位重新求和。stock_count在来源返回null时保留None。request_date仅为查询上下文，列表不回显日期，source_date为空；received_at为本机UTC接收时间。空列表不自动推断已披露或非交易日；只有来源最后日未更新且返回空时标pending，其余未确认状态保留unknown。业务拒绝、身份不符和结构错误会抛异常。

显式示例：`python examples/dragon_tiger.py --live --date 2026-11-05`；增加`--first-detail`才展开第一条的第一个事件。运行会访问生产服务，普通测试不会执行。


### 快速涨幅（实验性，M10指定范围已验收）

`get_stock_ranking(sort="rapid_change_rate")`读取字段48的服务端原值，只有降序。行的`rapid_change_rate`为百分数显示值或None；普通`change_rate`仍为当日涨跌幅，不互相替代。页的`window_minutes=5`、`window_source="user_confirmed"`记录2026-11-06用户明确确认的时长，不宣称已由官方页面或协议独立证明。SDK不自行计算滚动窗口、基准价格或开盘不足五分钟的值。接收时间仍不是来源行情时间。

快速涨幅使用独立游标profile，不能与既有排序互换。每次显式获取一页，保留24条上限、超时、有限网络重试和连接释放；不自动全榜。该快速涨幅阶段尚未接入资金排序，后续开发状态见下节。对应M10冻结wheel的盘中/盘后真实验收已于2026-11-10完成，范围见下方完成记录；不同构建不直接复用结果。


### 资金排序（实验性，M10指定范围已验收）

支持`get_stock_ranking(sort="large_order_net_volume")`和`get_stock_ranking(sort="main_net_inflow")`，均只支持降序。行分别返回同名RankingValue；三个进阶排序的游标profile独立，不能混用。空值保留None，raw/display/format_byte保持实际响应，不自行重算资金指标。

页`definition_source="user_adopted_official"`、`definition_url`表示用户于2026-11-06指定采用对应官方定义。大单净量采用DDE当日主力净买入量相对于流通盘的比率；主力净流入采用大单及特大单主动、被动流入合计减相应流出合计。该关联属于用户指定设计依据，不宣称App内部算法已独立验证。

`RankingValue.unit`仅保存实际显示后缀：大单净量无后缀时为None，不自动乘除100或添加百分号；主力净流入可为万/亿等，不等于已证明币种或精确元金额。字段窗口元数据保持None，用户采用公式不自动证明所有来源时间和累计区间。对应M10最终冻结wheel已完成三排序同wheel盘中/盘后矩阵；其他wheel仍需自己的验收，旧快速涨幅单独wheel的实测不混用。


### M10验收版本与范围

2026-11-10完成用户确认范围：SDK运行实现提交bb7ab0976be7f2e7ea2d36c77b9811afd4c6368d，冻结wheel SHA256为e799da157e3f04e0dc4e1a5e4bdd12c5dd3411932df13bf530bf4d58b37f2c6e。Windows独立安装、App停止时，三种新增排序分别完成盘中/盘后首屏、邻页、末页；龙虎榜指定日期列表/事件/详情及旧接口回归通过。末页由验收工具设置测试偏移，不代表遍历全榜。

研究仓库完成审计提交0fd597f，文件docs/research/m10-completion-audit.md及m10-final-build-evidence-index.json，详细列出574项双平台离线检查、真实响应重放和未验证分支。真实已披露空榜、非交易日和Linux真实联网不在此完成声明内；M11另行验收。上述时长/公式来源及显示精度限制继续生效。

## M14异动股票与停复牌

两个公开只读入口及示例见[事件查询](events.md)。当前异动单页，历史异动与停复牌最多显式两页；日期raw、市场未知和计划/实际状态边界按文档保留。
