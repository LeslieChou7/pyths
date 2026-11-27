# 第三方来源与分发

本项目原创代码采用 Apache-2.0。保留 LICENSE、NOTICE 和本说明。

## 上交所交易日历

2026 年日期表由 exchange_calendars 的 XSHG 休市日期与平日规则独立生成。
上游版本 4.13.1，提交 d94d30644cad4014bd8f79d877388a4f0891dfa9，Apache-2.0。
输入源码 SHA-256 为 `0450145f89c503f7311ebdabfa75177b21cd01aa5ec2dcc54cfc5a23f118336a`。
生成方式为筛选 2026 年周一至周五并排除上游休市日期，以 ASCII YYYYMMDD 和 LF 写出。结果共 242 天，
SHA-256 为 `e0c3a3c8ce13dac9808ad5e47d71316b973df0d2e5a979d392c30b1276eaf2ec`。
校验依据为上交所《关于上海证券交易所2026年部分节假日休市安排的通知》。
日期表由项目生成，未捆绑上游代码或依赖。

- [固定上游输入](https://github.com/gerrymanoim/exchange_calendars/blob/d94d30644cad4014bd8f79d877388a4f0891dfa9/exchange_calendars/exchange_calendar_xshg.py)
- [上游许可证](https://github.com/gerrymanoim/exchange_calendars/blob/d94d30644cad4014bd8f79d877388a4f0891dfa9/LICENSE)
- [上交所公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)

## 协议与测试

Snappy 格式依据 [Google Snappy 格式说明](https://github.com/google/snappy/blob/main/format_description.txt)，使用项目自己的解码实现。
协议实现参考 Android 11.50.04（5202）的静态和运行证据，样本 SHA-256 为
`cb6c135637e8f67d50ce75ad009f7b430f8f69ff356a3eb58840b0a29cfb08a9`。
随仓离线测试使用合成数据。TCP 查询的 App 配置由调用者从本地提供。

SDK 的 `src/pyths/_trading_days_2026.txt` 随源代码、sdist 和 wheel 分发。
