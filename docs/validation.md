# M5 验证工具与容器

## M11完成验证（2026-11-10）

同一冻结wheel已通过Windows/Linux盘中及盘后四轮真实矩阵（40/40/40/64发送），以及Linux六榜邻页/测试末页、关闭/重建检查。184/200次累计预扣，无失败或重试，余16次未使用；M10账本独立保持151/160。80成功公开结果与各自业务响应重放一致，完成模式审计核验132核心文件哈希，完整索引167文件。

SDK两端各576项离线测试及Ruff、格式、mypy、构建、独立安装通过。新增等待进程和验收工具属于研究仓库，不作为SDK依赖；工具最终Windows46项、禁网Linux45项及1项本地历史材料跳过。真实结果、冻结包哈希、语义限制见[兼容性矩阵](compatibility.md)，研究复现步骤见`ths_re/docs/m11-implementation.md`与`docs/research/m11-completion-audit.md`。默认检查仍不访问生产服务。以下是历史阶段记录。

## M11盘中阶段历史记录（2026-11-10 11:02）

Windows与Linux盘中两轮已通过，各40次发送；两端各17个公开结果已独立离线重放。App前后停止、连接关闭、关闭后8种公开调用无发送，新客户端可查询。冻结wheel和41个运行包文件保持不变，详见兼容性矩阵。此结果不替代盘后矩阵或Linux六榜分页；M11仍未完成。

研究仓库使用单一200次M11账本，当前累计80次；盘后40+64次通过本任务本地等待进程在15:01后重新核对时段/App/预算执行，失败不自动重试。SDK不包含等待进程或自动刷新。以下离线日志及历史工具说明保留原范围。

## M11离线工程检查点（2026-11-07）

新增合成本地TCP/HTTP交错回归：热榜成功或限流错误后，报价会话和旧包残留保持隔离；排行及龙虎榜调用不污染报价会话，关闭后拒绝调用。Windows与禁网Docker Linux各576项及完整工程检查通过。运行代码不变，构建wheel仍与M10最终文件相同（SHA-256 `e799da157e3f04e0dc4e1a5e4bdd12c5dd3411932df13bf530bf4d58b37f2c6e`）。

研究仓库的`tools/m11/`提供独立验收协调、共享预算、安装核验、时段门禁及离线完成审计；这些工具不是SDK运行依赖。真实矩阵要求先有M10盘中报告，双平台各做盘中/盘后并使用同一wheel。当前未执行M11真实请求，不能据禁网检查声明Linux生产兼容。实施与命令见研究仓库`docs/m11-implementation.md`；真实结论以兼容性矩阵为准。

## M8验收与默认检查

默认`python tools/check.py`覆盖434项合成/本机替身测试、Ruff、格式、mypy、构建及独立安装，不请求生产服务，不要求Android、ADB、Frida或研究仓库。Windows CPython3.13.14和禁网Docker Linux CPython3.13.18均已通过。

真实M8验证与默认检查分开：同一wheel在独立环境以`-I`导入，逐个核对33个包文件，App停止后分别完成盘中、盘后六请求五组件调用及关闭/重建。真实结果及已验证范围见[兼容性矩阵](compatibility.md)，显式调用示例见[使用说明](usage.md)及`examples/market_overview.py`；示例必须传`--live`，普通测试不自动运行它。

本页描述验证工具的使用，不代表新增证券或会话有效期已通过真实验收。实际结果见compatibility.md。
工具不属于公开SDK API，运行时仅需已安装的pyths及Python标准库。

## 工程检查

Windows执行`python tools/check.py`，需事先准备pyproject中的开发依赖。
Linux基础镜像固定为
`python@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb`，
首次拉取时对应python:3.13-slim、CPython3.13.18/Linux amd64。

在SDK根目录执行：

```powershell
docker build --target check --build-arg PYTHON_IMAGE=python@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb -t pyths-m5-check .
docker run --rm --network none pyths-m5-check
```

镜像准备阶段下载固定版本开发依赖；验收运行禁用网络，仅使用本地TCP替身。
Dockerfile在镜像内恢复普通Python文件0644权限，避免Windows上下文可执行位影响ruff。

## 安装包验证

先执行工程检查生成dist中的sdist和wheel，再构建runtime目标：

```powershell
docker build --target runtime --build-arg PYTHON_IMAGE=python@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb -t pyths-m5-runtime .
```

runtime仅安装wheel并复制独立验证脚本，不含SDK源码、测试、研究材料或设备工具。
默认入口为`python -I /validation/validate_live.py`。不挂载Docker socket或设备，不需要特权和入站端口。
两端须安装同一wheel并分别核对SHA-256；摘要中的哈希由执行者提供，不能代替外部文件核验。

Windows另建项目内虚拟环境，以`pip install --no-index --no-deps <wheel>`安装；
在源码目录外使用该环境的`python -I <验证脚本路径>`运行。脚本拒绝源码导入和非隔离执行。

## 显式真实运行

验证器必填：`--live`、`--scenario quotes|lifecycle`、`--host`、`--port`、
`--app-config`、`--app-info`、`--sdk-revision`、`--wheel-sha256`、`--report`及`--budget`。
Docker运行另记录`--image-ref`。`quotes` 场景每次处理同一市场的证券，例如 `--codes 688518 --market 17`。`--market` 可选沪 `17`、深 `33`、北 `151`，默认 `33`。使用显式联网 pytest 入口时可通过 `PYTHS_LIVE_MARKET` 指定同一市场。
配置文件以只读方式挂载，报告和预算账本使用专用可写目录。配置文件由调用者本地提供。

只有明确启用时才访问生产服务，普通安装、导入、默认pytest和容器工程检查均不会执行此入口。
每个平台所有场景复用同一预算文件；上限12次业务调用，失败也预扣，不得删除账本后重跑绕过预算。
预算统计公开get_quote调用；每次最多发送一个查询及一个必要stop，初始化另计结构次数。M5默认零重试。
报告文件必须使用新名称，按操作逐次写入；同一平台不得在生命周期验证期间另开App对照。

lifecycle在0、10、20、300、900、1800秒查询000001/33，再关闭后用新客户端查询。
最多允许一次网络失败后的显式恢复调用；协议/鉴权/限流错误立即结束，不自动保活。
摘要只含公开行情、环境、次数和关联头，不输出原始会话或正文；错误仅记录异常类型。
初始化按线上flags0x70000计数，查询和停止更新分别统计，不能用App入口参数100当初始化头frame。
另统计合法接收空封装；接收错误只保存预定义安全分类，不输出未知异常原文。
若用户明确追加调用额度，可显式设置`--max-calls`（最大20），沿用原账本累计，不得通过删除账本或新目录重置次数；默认仍为12。
`complete=true`只表示该次工具场景执行完毕，不能代替App对照或整个M5验收。

研究基线：ths_re提交b1067174a5489bfc3dbeeb7fdc0a97574b9b36b7，
docs/m5-implementation.md与docs/research/m5-validation.md。
上述为工具准备基线；完整实测证据提交2650922d2b3c47d545f4052ab278e56190bc2c14，代码版本与哈希见compatibility.md。
