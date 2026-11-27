# 异动股票与停复牌（M14指定范围）

使用`from pyths import ths`，客户端上下文内调用：

```python
from pyths import ths

with ths() as client:
    current = client.get_stock_anomalies(kind="current")
    history = client.get_stock_anomalies(kind="history")
    suspended = client.get_trading_status_events(kind="suspension")
    resumed = client.get_trading_status_events(kind="resumption")
    if history.next_page is not None:
        second = client.get_stock_anomalies(kind="history", page=history.next_page)
```

上例会发送真实请求，普通安装、导入和默认测试不执行。来源固定、匿名只读，不需要TCP端点、App进程或账号。每次调用使用客户端总超时（默认15秒，连接默认5秒）；本功能固定零自动重试，不受旧功能retries参数影响。

每次只返回单页；已验收范围最多两页，不自动抓全量。游标只能用于生成它的客户端和功能种类，不可序列化持久使用。第二页仍有数据不代表已到末页；没有后续引用可能是当前验收范围限制。has_more=None表示未知，不能据此宣称无更多记录。

异动日期start_date_raw/end_date_raw和monitor_type_raw保留来源整数；单位、时区和类型含义未冻结时不要直接转换为业务日期或证券类别。市场字符串保留原值，不按代码猜测；stock_name可空。列表中的转债仍保留，不按接口名称过滤。重复证券和重复行都保留。

停复牌记录保留suspension_date_raw/resumption_date_raw和resumption_label，未公布不转换为默认日期；isFp来源字段是日期标签，不是布尔值。Days保留为days_raw，日历计数口径未知。price/change/index_change使用Decimal或None，同时保留对应raw字符串；百分数原值不额外除100。价格在两个来源中的口径分别确认，不能跨列表套用。

接收时间received_at为UTC带时区时间，不是来源更新时间。未提供源事件ID、精确发生时刻、计划/实际状态或市场时保留未知；不生成买卖建议，不按代码合并事件。公开兼容范围以最终兼容性记录及真实验收为准，内部或合成测试通过不扩大范围。
