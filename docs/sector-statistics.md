# 板块统计（分阶段开放）

公共方法属于实验性能力。完整M13交付仍包含五分类、区间、排序、分页及OpenTHS联动；当前限制是阶段性证据门槛，不是将原目标缩减为单一历史日期。

使用公共客户端，无需TCP配置或账号凭据。当前公共白名单为30个精确参数/页号组合：来自P29中23个与App保留行一致且跨平台整页一致的查询，另加燃气首页/末页链及P44五个部分盘内首页。公共入口参数核对和分页扩展已做离线测试；P29/P44真实矩阵来自内部协调器，不冒充全部公共组合验收。其他组合在发送前抛出`ValueError`，不能将分类、排序、日期维度作任意组合。

新增部分盘内范围仅为2026-11-16的11:04—15:00：地域板块涨幅升序、降序，以及SDK实际返回的宁夏882021/48成分的主力净流入升序、降序和成交额降序，均首页20条。五组在同wheel的Windows/Linux内部协调器整页公开字段一致，且与App每组保留3行、总数及条数一致。该日期是实测来源日，不是自动跟随当前日期；不推断其他分钟、日期或指标方向可用。

调用`get_sector_capabilities().verified_business_scopes`查看准确目录，每项顺序为`kind/category/code/market/history_type/start/end/sort/direction/page/size20`，空字段原样保留；不是将各维度作任意组合。目录覆盖已有五分类基础组合、历史整日/完整盘内/多日的若干确切组合，以及地域、辽宁成分和燃气成分的已验收第二页。2026-11-13的11:05—15:00历史部分盘内查询出现过值差异，全部继续拒绝；不能用完整盘内范围推断任意分钟区间支持。

以下是显式联网示例；导入SDK和读取能力摘要不联网，默认测试不运行此示例。

```python
from datetime import date
from pyths import SectorPeriod, ths

period = SectorPeriod.historical_day(date(2026, 11, 12))
with ths(request_timeout=15, retries=0) as client:
    ranking = client.get_sector_ranking(category="industry", period=period)
    gas = next(
        item
        for item in ranking.items
        if item.values.code == "881146" and item.values.market == "48"
    )
    if gas.sector is None:
        raise ValueError("缺少来源板块引用")
    members = client.get_sector_constituents(sector=gas.sector, period=period)
    print(members.total, members.returned_count)
```

结果为`SectorPage`，公开导出`SectorPeriod`、`SectorRef`、`SectorCursor`和`SectorItem`。板块引用绑定生成它的客户端，不能跨客户端使用；股票代码/市场保留字符串，金额和比例保留Decimal原值及空值，不转换单位。每次仅返回一页，`total`不代表本页条数。显式把`members.next_page`传回同查询的`page`才查询下一页；只有白名单中的第二页可以发送，跨客户端、日期、排序或其他上下文拒绝。燃气已验证20+7=27末页；辽宁只验证前两页，不代表取全85条。不得构造游标或把JSON中的引用跨进程复用。

`get_sector_capabilities()`列出精确已验收范围与App观察维度。金额币种、换手率显示单位、来源更新时间及历史边界仍未知，接收时间不是来源时间。2026-11-17新wheel在Windows/Linux经OpenTHS实际公共入口完成每端10次请求、8个不同页面：行业首页、燃气首页/真实游标第二页，以及上述5个部分盘内首页。两端公开字段、顺序、空值与分页一致，燃气20+7/27末页通过；与App仅按其实际保留行对照，不称App整页逐值验证。其他公共组合的真实证据仍来自内部协调器，不能称30项均走公共入口实测。`sdk_network_verified=False`保留整体未覆盖的边界，精确目录不等于全组合承诺。网络/鉴权/限流/业务/协议错误沿用SDK异常分类，分类名称不能证明服务端要求登录。
