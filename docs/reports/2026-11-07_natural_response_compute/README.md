# 自然回答、过程分离与隔离计算复验

更新时间：2026-11-07。**主应用 `agent-20261107-8f0622c4d835` 已正式部署healthy；公网版本、原Logo、GitHub入口与匿名401边界已验证。受保护生产会话canary因登录态不可用而未执行，模型调用0，不宣称生产默认180秒已通过。** 真实8项核心交付、生产worker同输入重放及其预算/旁支限制分开记录；本次定向清理已完成且没有处理数据卷。

## 版本与状态

| 项目 | 当前事实 | 仍需确认 |
| --- | --- | --- |
| 主应用当前发布 | 后端与前端均为 `agent-20261107-8f0622c4d835`，deployed_healthy | 发布快照不代表所有业务路径或长期SLO通过 |
| 生产公开验证 | 新版build_id、版本化原Logo、GitHub入口，pageErrors=0；RAG2228 ready/pending0 | 完整本人OAuth未测；受保护会话另列 |
| 后端代码回归 | 最后比较统计根投影/中文展示等176项相关测试通过；此前广泛回归和交叉/两期等边界另有证据 | 范围重叠不相加，不替代生产默认预算验收 |
| 数据库与冻结边界 | 22 项真实 PG 通过；7 个预测冻结文件与 `a5103511` 一致 | 不替代新发布的生产观察或全部外部调用验收 |
| 独立 compute | `python-20261107-a0b8e1d70e82` 已 healthy 部署；原失败代码和原 SEC 数据不变的两段生产作业均成功 | 已证明相同输入修复，仍不代表任意代码容量或主模型答案全部正确 |
| Python 定向回归 | companyfacts/列别名/编码兼容修复后，61 项聚焦及 71 项真实 Docker 组合通过 | 与先前 76/70 等范围不相加；不能替代生产容量及用户任务验收 |
| 前端过程/正文/图标 | 全量489项、图标3个fixture视口与真实artifact数值复验，当前主应用已部署 | fixture不冒充生产认证后会话 |
| 图表来源与时间小修 | 17 项聚焦与真实 case6 单项渲染复验通过；5 个原始引用去重为 1 个 Twelve Data 来源，日期显示 2026-11-06，数值与 SHA 不变 | 计算方法保留在 method，不计独立来源；原始 source_refs 不重写 |
| 真实核心问题 | 最终每题采纳一个完整run，8/8核心交付通过，31次模型调用、188829 reported tokens | 不等同每句话自动证明；harness250秒与生产默认180秒不同 |
| Fresh AAPL 图形 | [真实渲染复验](../2026-11-07_chat_design_alignment/REAL_CHARTS.md)：24×2、65行源预热、逐点与原两位精度一致；图末 MA20=343.38 | 未舍入均值约343.3844995，图表验收不代替整个对话语义 |
| 冻结 before | 四会话八问题：42 次模型调用、254410 reported tokens、完整通过 1/8 | 见[独立 before](BEFORE.md)，不与本次 after 混算 |

## 已实现的边界

- 文本 block 标注 `content_phase=progress/answer`；过程仍按首次 seq 保存和展示，最终 `response`、普通复制与后续回答历史只取正式答案。
- 答案检查发现问题时，主研究员最多再做一次不提供工具 schema 的修正；仍受原 run 的时间、token 与服务配额限制。修正轮即使返回工具调用也不会执行，不进入无限纠错。
- 不可靠的候选段落通过 `content.revised` 删除/替换，空内容可以保留原 block 身份；新流程不逐段生成“已撤回”占位。正式答案仍有问题时保留部分结果、质量原因和一条限制说明。
- UI 使用“思考/思考过程”“参数/结果”“参考来源”等短文案，真实失败、未保存和信息不完整状态仍明确可见。旧数据库消息不因文案修改而被重写，也不恢复已经丢失的段落。
- Python 始终在独立 job 容器执行。adaptive 支持按当前可用物理内存选择额度；本次低内存目标配置为 job 128/192/256 MiB、reserve 128 MiB，不以 swap 补足预算。
- `logs/logs_truncated/code_error` 提供有界 stdout/stderr 与代码错误线索；只 print、没有 `result` 的任务返回未产生结果。`get_frame()` 读取已授权数据引用/原包/行表，原 `datasets` 不改写；最新接口边界与故障定位见[Runbook](../../11_PRODUCTION_RUNBOOK.md)。
- fresh4 暴露了 inspect 的 `companyfacts/period_end` 与 worker 原 `period_ends` 不一致：现已支持该表别名、`period_end/period` 和已有标量上下文列，保留原字段。NumPy 标量、`pd.Timestamp` 可编码为原生 JSON，NaN/Infinity 仍拒绝；输出/日志限额没有扩大。
- `inspect_dataset` 默认投影标量列并保留 `column_units`，最多 12 行且受 8000 保守字节/token估算约束；过大时减行或明确拒绝。图表逐字段保存 coverage/leading_missing 与 limitations，追问通过仍有效的 prior_artifacts 投影核对旧图，不重新画旧图冒充新结果。
- 续研 catalog 只暴露 `success` 且有 `source_refs` 的资料，control/旧失败回执不当作研究证据；历史图投影明确不是当前 run 新交付。字符串报价的非实时与否定表述已有相关回归和选定run证据，生产连续会话仍单独验收。
- `comparison_crossovers` 纯函数及 `comparison_stats.crossovers` 统一检查领先方交换，初次持平后的分离不计交叉。真实215点独立检查为4次（2026-01-06/01-13/02-05/03-19），旧Python误计5次保留为 before。文字次数/日期核对及“两期只证明一次变化”合同已实现；相关回归见分类摘要，不据此推断所有生成语句通过。
- 修正反馈硬限4000 UTF-8字节、优先可验证比较统计；原长会话离线重放没有真实模型调用，修正轮25249字节未超窗。最后比较统计的根投影保留真实日期，展示使用中文，协议字段不改。

## 正式部署与生产验证

主应用 `agent-20261107-8f0622c4d835` 于 **2026-11-07 22:07:06 UTC** 完成正式切换，部署结果为 `deployed_healthy`。readiness为true、失败组件为空；RAG索引为2228个semantic_ready、pending=0。这里记录发布时快照，不将其当作长期SLO或所有用户任务已经验证。

- [部署/镜像/readiness投影](production-deployment.json)
- [公网版本与页面验证](production-public-smoke.json) · [实际欢迎页截图](production-welcome.png)
- [受保护canary未执行与401边界](production-protected-canary.json)

公网确认 build_id 为当前8f版本、原Logo SHA与版本化资源一致、GitHub登录入口可见，pageErrors=0。完整本人OAuth仍未测试，不能将入口可见写成登录全流程通过。

**生产默认预算的两个连续会话、共4个query没有执行。** 原因是无可用Supabase验收登录态，生产未配置内部API keys；记录明确 `status=not_executed`、`model_calls=0`、`runtime_authentication_changed=false`。匿名外部POST返回401及`auth_required`符合预期。本次没有为验收创建测试账号、开启内部密钥或绕过鉴权。缺失的是生产受保护路径的正向证据，既不能改记为成功，也不能伪称发现了研究业务失败。

真实八query与生产worker同输入重放仍按各自范围成立：前者使用250秒harness和本机隔离PG，虽实耗均小于180秒，也不替代上述生产默认预算验证。

## 定向清理与保留

[清理/挂载投影](production-cleanup.json)记录了本次结果：

| 项目 | 结果 |
| --- | --- |
| 保留应用 | 当前8f与上一主应用8b |
| 保留上一前端 | `ui-20261107-9cfdc5be5e05` 镜像 |
| 保留compute | 当前a0与上一48 |
| 删除旧镜像标签 | 14个 |
| 删除旧release目录 | 7个 |
| 删除旧上传包 | 12个 |
| 实测回收 | 5,030,903,808 bytes，约5.0 GB |
| 卷是否被处理 | `volumes_touched=false` |

backend数据(`/app/data`)、日志(`/app/logs`)及PostgreSQL(`/var/lib/postgresql/data`)均为命名卷，已确认不在release目录删除范围。镜像标签、release和上传包按各自对象计数，不将标签数冒充独立镜像层数，也不擅自扩大清理范围。

## 最终选定的八项核心验收

来源为 `.omx/acceptance-natural/FINAL_REPORT.md/.json`，本目录保存不含终态长正文的[证据投影](after-core-evidence.json)。每题只采纳一个完整 run 的正文与产物；旧失败与修复重放保留，不拼接答案。

| 问题 | 采纳 run | 模型调用 | 实耗秒 | 核心结果 |
| --- | --- | ---: | ---: | --- |
| 1 报价/涨跌/日期 | `acceptance-natural-1f4f06023d-1` | 2 | 15.80 | 通过 |
| 2 Python均值与MA20双序列图 | `acceptance-natural-1f4f06023d-2` | 6 | 64.22 | 通过 |
| 3 均线算法与交易日解释 | `acceptance-natural-1f4f06023d-3` | 1 | 11.66 | 通过，保留一般月份表述限制 |
| 4 两期营收及一次变化 | `acceptance-natural-1f4f06023d-4` | 8 | 86.75 | 通过 |
| 5 单位与不能保证下季增长 | `acceptance-natural-1f4f06023d-5-retry-bd21` | 2 | 18.64 | 通过 |
| 6 NVDA/AMD年初至今对比图 | `acceptance-natural-e2e58933cf-6` | 7 | 96.69 | 通过 |
| 7 仅按图确认路径/交叉 | `acceptance-natural-e2e58933cf-7` | 3 | 69.08 | 通过，旧展示与日期预览问题已另做机械修复 |
| 8 实时暗盘净流入不可得边界 | `acceptance-natural-5b2c9eb8bd-8-retry-cd46` | 2 | 20.22 | 通过 |

**验证范围与限制：**

- 31 次/188829 tokens 仅为选定的8个run小计，不是整个修复期间的累计成本，也不是计费金额；不能再与 before 或中间重试重复相加。
- 模型、行情/SEC数据和生产隔离worker是真实调用；会话 begin/checkpoint/finish/get 使用本机隔离 PostgreSQL，未写生产会话库。
- harness预算250秒；8项实耗均小于180秒。生产默认chat180秒的两个连续会话、共4个query因无验收登录态未执行，详上方边界记录，不能写成已通过。
- 均线说明中的一般月份“约20～21个交易日”不能替代该图实际24点。SEC所取4个期末没有同比需要的去年Jul25，不能把缺该同比期说成没有任何历史数据。
- 旧5次交叉统计已被统一定义纠正为4次。选定图解曾裸露技术字段、误说日期未完整提供，实际源中有4个日期；最后的预览根投影和中文展示修复不改变原数据，也不回写旧终态。
- 8/8是核心交付 gate，不是所有旁支因果/覆盖/措辞均由机器证明，更不能外推全站准确率。before的1/8完整性记录保持原样，判定口径和范围明确分开。

## 未上线的中间候选

`agent-20261107-7fedbf9b1f5d` 曾完成前后端构建、source scan/export smoke、锁定版本/无本地 ML 包和当时 B 运行时一致性检查，服务器目录 prepared，但**从未启动**。后续续研目录与字符串报价修复使其被新候选取代，不可当作上线版本。

| 中间候选证据 | SHA-256 |
| --- | --- |
| Runtime | `7fedbf9b1f5d192e76cf11a07cc52cfff6ac36268761c769f18c48db19340da4` |
| Backend image | `52f482c714ea8968726192e125fc337dfdf9e52d5956ee37074407459f2610d4` |
| Frontend image | `5fd2437ca62f5c4b43b9be188f586cef8dcee7460a026c583af9dc7a6db7b84e` |

先前 165/37/172 项定向属于过程证据，与最终 170 项验证范围存在重叠，不累计为新的通过数量。

随后 `agent-20261107-2c7016c687d3` 与 `agent-20261107-7d6d190093eb` 也只构建/prepared、从未上线，因后续修复被取代。对应 runtime SHA 分别为 `2c7016c687d3c9a0e6a872d8c8ffe60f003124cdd0c0b31135878cf68660759e`、`7d6d190093eb258bc631f678a4090123cc20884c137f07df7fc3bd330c29706c`。presentation 自然时段映射曾有72项定向通过，属于分类证据，不与其他范围相加。

`agent-20261107-9c524d7c9e9e` 是最后一次 Python 适配同步前的候选，未列为当前上线版本；其 runtime SHA 为 `9c524d7c9e9e48184bc4d9f13dfdf2e6488cee9b3e7a21b9d3de088a7bf5b0eb`。最终主应用版本已由重建后的 source proof 确认为8f，见正式部署记录。

## Worker 同输入生产重放

主代理的 `.omx/python-fix/production-sec-replay.json` 确认 `original_failed_code_unmodified=true`、`original_sec_data_unmodified=true`。这里保存不含完整日志的[结果与 hash 投影](production-sec-replay.json)，不重跑生产请求。

| 重放 | 状态 | 最新/前期收入（USD） | 差额（USD） | 变化率 | 内存 / 保留 | 耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| 原失败代码 1 | ok | 96,221,000,000 / 81,615,000,000 | 14,606,000,000 | 17.8962200576% | 256 / 128 MiB | 1877 ms |
| 原失败代码 2 | ok | 96,221,000,000 / 81,615,000,000 | 14,606,000,000 | 17.8962200576% | 256 / 128 MiB | 1382 ms |

财期为 2026-07-26 与 2026-04-26。两段代码各自保留 code_hash/input_hash；这是两份不同原代码的重放，不要求两份请求 hash 相同。worker成功与主模型完整回答分开验收；长历史修正反馈现已另外做4000字节有界修复。

## After 验收清单

- [x] 每个原样问题采纳一个完整run，保留会话/原问与失败记录，不拼答案。
- [x] 核心交付已核对价格、均值/双序列图、营收变化、单位与未来不能保证的理由；旁支限制另列。
- [x] 路径/交叉按完整源序列核对，初次持平分离不计，真实领先交换4次。
- [x] 暗盘场所与盘前盘后时段、成交量与净流入区分；对应数据不可得时明确说明。
- [x] 实际图表逐点核对，百分比不重复乘100；旧失败没有产物时不补预制图。
- [ ] 验证 `progress` 不进入正式复制/历史摘要，正式答案只显示一次，旧候选清空后没有成批撤回占位；刷新/恢复保留 phase、seq 与 owner 边界。
- [ ] 验证取消、中断和修正失败恢复时，未完成预览与正式 answer 的含义一致，不把停止前的过程片段标成已完整回答。
- [ ] 核对 Python 实际分配内存、保留量、容量拒绝、OOM/超时、日志截断、代码行号、`get_frame` 常见数据包/多表，以及最终 `result` 进入回答/图表。
- [ ] 区分本机、Docker、前端 fixture、真实模型、生产 canary，各自记录结果；失败和部分完成不能改记为成功。
- [x] 正式启动、公网版本/页面、鉴权负向边界、镜像身份和定向清理已留证；文档overlay不改runtime hash。
- [ ] 生产默认180秒的受保护连续会话尚未执行；不得以harness或401结果代替。
- [ ] 长期观察期/SLO与完整本人OAuth仍待独立验证。
- [x] 修正反馈已按UTF-8硬限4000字节，原长会话离线重放0次真实模型，修正轮25249字节未超窗；生产连续会话仍单独验收。

## 最终发布与结果

| 字段 | 值 |
| --- | --- |
| 主应用正式版本 | `agent-20261107-8f0622c4d835`，deployed_healthy |
| 最终 Runtime SHA-256 | `8f0622c4d8353d1dd01dc8511708158845c6bfd489cc312921eea602b391e1e4` |
| Backend image SHA-256 | `fee57e84a7d69bbd2a8a7df5ab9bcd0d00af47cc80ac6ff13b0ce3a71593110b` |
| Frontend image SHA-256 | `1d748c49ce128f059bf802a2630550905e1138bcce04e84ce0cd050b9c3f2eb0` |
| 主应用正式启动 / 发布日期 | 2026-11-07 22:07:06 UTC |
| After 核心通过数 / 原样问题数 | 8/8核心交付，不等同每句话严格证明 |
| After 选定run模型调用 / reported tokens | 31 / 188829，独立于before及其他中间重试 |
| 生产受保护连续会话/默认预算canary | not_executed，model_calls=0；无可用Supabase登录态/内部API keys |
| 部署后观察期 | 待记录 |
| Git 提交 | 报告生成时未提交；2026-11-08 恢复任务已授权，部署快照已按功能提交 |

## 文档检查

README、当前架构、事件、图表、防幻觉、Agent、Runbook、索引与 legacy 边界已同步。10 个 Mermaid 图经独立浏览器中的 Mermaid 11 parse/render 通过，SVG和哈希见[检查记录](mermaid-check.json)；[README图](mermaid/README-1.svg)、[当前架构图](mermaid/docs-01_ARCHITECTURE-1.svg)、[事件图](mermaid/docs-execution-event-contract-1.svg)、[计算额度图](mermaid/docs-11_PRODUCTION_RUNBOOK-2.svg)可直接查看。overlay 本地链接与围栏的[检查记录](links-check.json)单独保存。此检查没有运行生产启动、数据库迁移、模型请求或全局包安装，不能替代业务 after 验收。
