# 离线编解码使用边界

本页描述协议研究的内部离线入口，不作稳定公开API承诺。`from pyths import ths`仍是公开生命周期入口；已有真实能力及范围以compatibility.md为准，导入不会自动联网或读取凭据。

## M13板块统计内部离线流程

板块已有按精确证据目录开放的公共方法，见[板块统计](sector-statistics.md)。以下内部编解码流程可独立离线使用，不读取研究仓库或App材料：

- `_sector_models.SectorPeriod`：显式整日、分钟盘内或多日区间，不推断最新交易日、来源时区或交易日历。

  `single_day`表达盘内模式的09:30—15:00整段，不能推广为所有历史日期的默认编码。`historical_day`按实际历史整日证据生成模式1、相同起止日期与000000后缀；`intraday`和`multi_day`分别显式表达盘内和多日。调用方必须依据来源能力选择，不从本机日期判断来源最新日。
- `_sector_request.encode_period_request`：把区间、分类/板块、排序和页号编码为已观察JSON形状；可编码不表示该组合已通过真实验收。
- `_sector_codec.decode_sector_response`：输入原始JSON字节，返回独立身份和Decimal指标；缺失不补零、未知市场不改写。
- `_sector_query`：板块引用和游标绑定客户端、来源及完整查询上下文。引用不提供跨进程序列化恢复。
- `_sector_page.assemble_page`：组装查询、来源总数、本页条数和显式接收时间；保留源顺序及重复项，不把接收时间当源时间。异常短页或总数矛盾保留分页未知。

`_sector.query_sector_page`包含HTTP协调，会访问网络，不能当作离线解码入口。已有同wheel双平台的精确参数矩阵验收，公共客户端在其前面额外校验白名单；内部可编码值不代表任意组合可用。默认测试不会执行生产请求。

独立 SDK 随附板块合成样本用于离线解码。

在已安装当前SDK的环境中，从SDK仓库根目录运行离线示例：

```text
python examples/sector_offline.py --kind stock --fixture tests/fixtures/synthetic/sector-stock.json
```

必须显式选择本地文件和行类型，示例不接受URL或联网开关。输出保留Decimal十进制字符串和空值；`source_total`来自样本，`returned_count`是样本中的实际行数，`network_verified=false`不是来源返回字段。安装包独立使用时可指定自己的安全本地JSON文件，不读取研究仓库。

已实现的纯离线入口：

- `_codec.encode_1269_body`：显式传入证券、市场、frame和实例，生成UTF-8单页正文。
- `_headers.encode_request_header`：显式传入全部状态和ASCII trace扩展参数，生成新请求应用头。
- `_transform.transform_request`：显式注入完整校验前缀及会话后缀，映射正文并更新长度和CRC；未知值不得用空值代替。
- `_transform.checksum_context`：按显式App配置和会话参数构造前后缀；不自行读取设备或凭据。
- `_framing.encode_frame`及`FrameDecoder.feed/finish`：处理外层边界，默认单帧上限1MiB；结束时必须调用finish检查残帧。
- `_response.decode_1269_response`：输入响应应用头、压缩负载及独立关联预期，验证后读取本次Snappy/tb1.0路径。

```python
from pyths._codec import encode_1269_body

# 合成关联编号，仅展示离线编码；不发送请求。
body = encode_1269_body(stock_code="000001", market="33", frame_id=2, instance_id=3)
```

解析结果保留显示字符串、格式字节、表头、扩展原字节和单元格偏移。通过`format_table_string`应用后缀；不把缩写量额还原为精确值，不推断币种或行情时间。缺失或未知字段不填零。

畸形数据、未知必要标志或关联冲突抛出`ThsProtocolError`，诊断不包含原报文。解压默认上限8MiB，外层默认1MiB，均为SDK资源策略。导入及所有默认测试完全离线；真实服务器接受请求、鉴权及会话生命周期未验证，详细范围见compatibility.md。
## M8新增离线格式

`_curve.py`提供有界cv1数值与已确认cv3转置/RLE布局解析，供成交额与DDE专用适配器使用。输入及解压分别限4MiB，最多10000行、256列和256个扩展，拒绝截断、无效偏移、必要字段缺失及未知结构；不把解析成功等同于真实服务端兼容。

广度JSON、大小盘表及曲线的业务身份、响应关联和显示转换由专用模块验证，不在通用解析器中猜测币种、日期或集合。入库测试均为合成/最小生成材料，不读取研究仓库的App或抓包。具体使用与当前验收限制见[使用说明](usage.md)和[兼容性说明](compatibility.md)。

## 板块能力摘要（本地）

`from pyths import ths` 后，在客户端上下文中调用 `client.get_sector_capabilities()`，返回公开的不可变 `SectorCapabilities`。此方法只读取随SDK发布的证据摘要，不连接服务端，不读取本地凭据，也不检测当前授权状态。关闭客户端后调用与其他接口一致抛出 `ThsClientClosedError`。

`status`为`sdk_partially_verified`，`sdk_network_verified=False`表示整个原定矩阵尚未全部通过；不否定已经成功的精确用例。`independent_http_probe_verified=True`及`independent_http_probe_scope`保留首次匿名HTTP候选的历史证据，不能据此认定Accept单独解决旧403。

`verified_business_scopes`列出30个精确参数/页号组合，目录格式及用法见[板块统计](sector-statistics.md)。这些范围来自Windows/Linux内部业务矩阵与可取得的App公开行对照，未将只留前三行的App投影扩张为整页逐值验证。原两个行业/燃气首页还完成了公共方法同wheel真实验收；扩展后的新构建物不能沿用这条证据宣称全部公共组合已测。燃气20+7/27末页链已在内部矩阵通过。

`observed_categories`、`observed_sorts`、`observed_directions`、`observed_period_modes`仅列App观察维度，不能取笛卡尔积。7个2026-11-13的11:05—15:00部分盘内组合出现数值差异，继续拒绝；null与0不得合并。最新来源日、任意分钟区间、金额币种、换手率单位、源时间和历史边界均不得推断。能力摘要不实时探测服务，不加载账号或凭据。

2026-11-17，新wheel经OpenTHS实际入口在Windows/Linux各完成10次请求（8个不同公共页面），包含燃气第二页和5个明确部分盘内首页。未宣称全部30项公共组合实测。真实验收之后仅更新能力限制文案和文档，没有修改请求、解析、引用或分页逻辑；构建物及源码差异须按交付记录核验。
