# 涨停聚焦（M15开发中）

三项公共方法与离线测试已接入，public_verified_scopes已根据双平台既有审计同步24个精确组合：17日矩阵18项、18日盘中新6项。它记录既有验收范围，不把后补目录称为新增网络实测。真实回执见研究仓库docs/research/m15-public-audit.json及m15-intraday-audit.json。选项不是任意可组合；同一AA0受测包的同日盘后双平台对照已补齐，规则与单位未知项仍保留。

## 调用契约

- `get_limit_capabilities()`仅返回本地LimitCapabilities，不联网。
- `get_limit_pool(*, pool, trade_date=None, filters=None, sort=None, direction=None, page=None)`返回LimitPoolPage。当前须显式传date；省略日期在发送前拒绝，不按本机日期猜最新来源日。
- pool：limit_up、approaching_limit_up、consecutive_limit_up、broken_limit_up、limit_down。sort为change_rate/latest或省略采用来源默认；direction为asc/desc或省略采用来源默认。
- `LimitFilters(markets=("HS", "GEM2STAR"), include_st=False, include_unopened=False)`表达市场及原生显示选项。实际可用组合由精确目录控制，可构造不等于已支持。
- `get_limit_focus_summary(*, trade_date=None, filters=None, allow_partial=False)`从一次已观察池响应取得六统计。默认缺少指标时失败，显式allow_partial才返回缺失值及警告。

## 返回值与引用

LimitPoolPage保留query、source_date_raw、items、page/page_size、total/page_count、received_at、has_more、next_page、summary_raw及warnings。LimitPoolRow保留字符串code/market、name和不可变fields。Decimal不改单位，时间戳原文不擅自解释时区，N天M板不转换为连续板数。未知字段递归保留为只读映射或元组，源顺序与重复项保持原样。

来源合法空池可能回显page0/total0/page_count0；仅首页空结果接受此组合，公共page仍为请求页1、source_page保留源0，has_more=False且不生成游标。空池中的有效六统计仍保留，不解释为非交易日。

LimitFocusSummary的today/yesterday保留num、open_num、rate；rate为源比例，不乘100。统计口径仍有未知项，不能用池列表重算。未回显的昨日日期和来源时间为None；received_at是本机接收时间。

today/yesterday是所选源交易日下的页面标签，不是宿主日历今日/昨日。18日近时点对照中，yesterday三项与17日历史today三项完全一致。盘中自然样本显示卡片open_num区别于行open_num：前者与当次未封回证券集合计数相符，后者在已观察证券再次开板时递增，回封本身未递增。SDK仍读取卡片源值，不由池条数、行次数或本地公式重算；源不回显的昨日日期保持None。000410回封标记为1时次数曾为null，不能补零。

移动页显示链已补证：卡片rate乘100后按Math.round显示整数百分数；行change_rate直接显示百分数，limit_up_suc_rate则乘100显示两位，二者不可混用。首次/最后涨停或跌停时间分别保留对应原字符串；App将其作为Unix秒并按设备本地时区显示，本次设备Asia/Shanghai。SDK不按显示位数改写价格或比例，不把设备时区补成服务端统计时区。封单量/金额等字段单位仍有未确认项，详情见研究规格。

游标绑定客户端与完整日期/池/筛选/排序，不跨进程恢复。未知组合、跨上下文游标、关闭客户端均发送前拒绝。不自动续页或拉全；源总数与returned_count分开。响应日期/页号/页长不符为协议错误；总数与页长度不一致时has_more为None且无游标。未验证续页可has_more=True但next_page为空，并带next_page_not_verified警告。

调用沿用客户端总截止时间，新功能零自动重试，不初始化TCP会话、不提取账户配置。默认测试与能力查询离线；真实调用由调用者显式发起。

## 当前证据

当前24个App精确组合均有双平台公共入口证据。旧包c294025c0fcaa67d15c4c875ab33f967cfff69d38591bf0bdd54b7ac247bcfc5两端各35次、各331条完整池记录；盘中包aa0fb1d3d2bed9894e2853ecbe9bf7fd007c074b72f81506a47f5920477b80c9两端各16次、176/179条完整池记录均与各自响应独立核对一致，源trade_status明确为morning_trade/交易中。收录盘中真实投影及目录同步后，新包9cddc08581a20821238351b7ce470666d92a8fe41a80cd189678dfee7710fbc2两端完整732项离线检查通过（42项为本功能相关测试）；所有包之间57个业务运行文件逐字节相同，仅静态目录演进，不把后补目录包称为新增网络实测。首次/最后封板与回封自然样本已取得，更多证券/时段分支及源未公开规则仍不外推；同日盘后对照已补齐，完整业务规则/单位仍待取证。

相同wheel在两端的35步合成验收演练通过，未发送生产请求；这些演练不证明真实服务兼容。生产限流、完整统计口径、所有市场/筛选交叉及未来日期仍未完成验证；盘中开板/回封仅有列明自然样本。

来源：研究仓库docs/research/limit-focus.md及docs/protocol/limit-focus.md；固定Android样本11.50.04（5202），APK SHA-256 cb6c135637e8f67d50ce75ad009f7b430f8f69ff356a3eb58840b0a29cfb08a9。公开仓库默认使用合成测试样本。

2026-11-18盘后增量：同一AA0 wheel在Windows/Docker Linux各16次公共SDK/OpenTHS调用通过，各188条完整池记录与各自原始响应独立核对，32份状态均closed/已收盘。对应App五池同日闭市证据已通过；今日40/24/0.625，昨日36/20/0.6428571428571429，不由池条数重算。研究提交0621ef654a3b4007a37afa40975db6beea623987的docs/research/m15-afterclose-app.json、m15-afterclose-audit.json可追溯。不同请求不当原子快照；冲刺阈值、特殊证券条件及部分封单单位仍未知，不宣称M15业务规则整体完成。
