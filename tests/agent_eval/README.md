# Agent 评测与回放

更新：2026-11-13。生产代码仅有 `backend/agent_runtime/`；`baseline_runtime/` 和 `reference/` 只用于冻结旧实现对照，不进入生产镜像。原始失败记录保留，不用挑选成功尝试拼成通过结果。

## 当前状态

- M1 旧实现基线已完成：`results/m1_qwen_baseline_complete.json`，60/60 独立评分，均分 3.33/7，正常完成 12/60。它是录制阶段基线，不能直接作为新实现回放的比较对象。
- 当前被测模型为用户指定的 APIKL `gpt-6.1-terra`，独立评分模型为 `gpt-6.1-sol`。原生工具调用与 SSE 已通过[模型探针](results/m0_apikl_terra_probe_20261113.json)，独立 `submit_score` 链路通过[合成探针](results/m0_apikl_judge_probe_20261113.json)；这些探针不代表 60 题质量门槛已通过。
- 原先指定的 `gpt-6-luna` 在 Chat Completions 与 Responses 路径均返回 `model_not_found`，不是可用别名，见[协议核验](results/m0_apikl_protocol_followup_20261113.json)。Vectide 的历史对照保留在 `results/vectide_matched_execution.json`：当前实现录制完成 34/60，基线随后因周额度耗尽中断，不能与 APIKL 批次混用或算最终通过。
- M4 用 `run_review.py` 单独测量 12 对正确/注错答案；合成资料明确标注，不能当真实行情。Step 5 已有完整测量；Vectide 失败与恢复批次分别保存于 `results/m4_vectide*`，不能混为一个批次。
- APIKL Terra 的[本轮核查测量](results/m4_apikl_terra_review_20261113.json)与[独立 Sol 语义裁定](results/m4_apikl_terra_adjudication_20261113.json)均完整完成 24/24：注错语义检出 12/12、原答案语义误报 0/12、不可用 0/24。结构测量中 1 条原答案收到完整性提醒，独立评审判定该提醒有资料依据；它仍保留在原测量，不改写为无 finding。评分阶段两条无效提交仅补判失败项，原提交保存在 `previous_attempts`，有效评分未重跑。
- M3 [本轮完整对照](results/apikl_matched_execution_20261113.json)仍在进行：四次 60 题研究与两次独立评分顺序执行。[当前实现录制](results/m3_apikl_current_record_20261113.json)已采集 60/60，52 题正常全回合终态；8 题预算或期限失败按原始结果保留，其中报告组 1/4 完成。录制未评分，最终质量与耗时比较尚未完成。
- [APIKL 模型元数据](results/m0_apikl_terra_metadata_20261113.json)与[公开文档查证](results/m0_apikl_terra_public_docs_20261113.json)均未提供 Terra 的上下文、输出或视觉规格。131072/16384 是本地配置；长输入和实际 PNG 能力仍须单独验证，不能沿用旧模型的视觉标记或推断官方上限。
- 第 12 节 48 项产品验收独立于本目录评分。资产单测、接口探针和录制成功都不等于上线验收通过。

## 题集与评分

`cases.json` 共 60 题：事实 6、估值 6、归因 6、新闻 5、统计/画图 6、比较 5、多轮 6、概念 4、故障 5、港/A 股 4、报告 4、写操作 3。每题保留原始 `turns`、自然语言 `must/must_not` 和结构化 `expects`。

内容由不同于被测模型的独立模型评分：回答问题 0–2、数字一致性 0–2、口径/局限 0–1、篇幅结构 0–1、无内部标识 0–1。代码只检查终态、引用、产物、动作、错误、预算与证据绑定；不用自然语言关键词打分。

外部原生 `verifier` 评分通过 `--judge-protocol external` 生成完整输入请求，逐题绑定题目、实际回答、资料快照、量表和身份的 SHA256。评分文件必须由实际独立评审产生，不能只填写身份标签。导入只验证绑定，不证明身份本身。迟到资料可以保留在最终库，但不能倒灌既有评分。

## 运行方式

在本 worktree 根目录执行，使用项目虚拟环境。启动时读取私有 `.env.runtime.local`；密钥不写入命令、题集、结果或提交。

```powershell
chcp 65001 > $null
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run.py --list
```

`--runtime` 只接受 `current`（默认）和 `baseline`。选择基线时逐文件核对冻结 manifest，不恢复生产路由。

`--provider apikl` 必须显式提供 `FINSIGHT_EVAL_APIKL_API_BASE/MODEL/API_KEY`，不借用生产凭据。默认上下文预算为 131072、最大输出为 16384；这是保守的本地预算，不是经过实测的模型规格。可用 `FINSIGHT_EVAL_APIKL_CONTEXT_WINDOW/MAX_OUTPUT` 覆盖，完整中转上下文边界仍需实际验证。其它选项为 `configured`、`fallback`、`stepfun`、`moxuna`、`vectide`，各自使用独立配置。

APIKL 本轮独立评分使用 `FINSIGHT_EVAL_JUDGE_MODEL=gpt-6.1-sol`、相同 API 地址与安全引用的 API key，`--judge-protocol tools`；评分模型必须与被测模型不同。四次研究运行从一开始绑定相同评分配置，`--no-judge` 只推迟评分，不改变评分身份；随后 `--grade-report` 实际调用独立模型。

当前对照固定 `--jobs 2 --request-interval 6.1`，并保留 `FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS=10`、RPM 30、TPM 250000、单次运行 token 160000 的原配置。每题存储隔离，模型配额在整批之间共享。不要为了加速绕过共享限额；2026-11-13 的 4 进程快速批次触发本地额度耗尽，已单独保留为失败证据。

先为两个实现收集工具参数的并集，再冻结同一个资料库分别回放。`record` 复用已有同键记录，只采集缺失键；`replay` 的金融工具不联网，缺失键返回 `tape_miss`。查询参数由模型生成，不能为匹配旧录制而改写模型调用。

```powershell
# 以下参数对四次运行保持相同；输出文件各不相同。
$evalArgs = @('--provider','apikl','--jobs','2','--request-interval','6.1',
  '--timeout','180','--model-protocol','sse','--no-judge','--judge-protocol','tools',
  '--fixtures-root','fixtures/apikl-matched-20261113')
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run.py @evalArgs --runtime current --mode record --output tests/agent_eval/results/current_record.json
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run.py @evalArgs --runtime baseline --mode record --output tests/agent_eval/results/baseline_record.json
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run.py @evalArgs --runtime current --mode replay --output tests/agent_eval/results/current_replay.json
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run.py @evalArgs --runtime baseline --mode replay --output tests/agent_eval/results/baseline_replay.json
```

本机行情代理若有需要，可用现有 `tmp/agent-eval/run_with_yahoo_forward.py` 入口；它只加载本任务回环代理，不修改生产网络配置。定向定位可用重复的 `--case` 或 `--limit`，但部分题目不能冒充完整测量。

研究运行完成后，使用 `--grade-report` 对原始结果实际判分，不重新生成答案。使用原生外部评审模式时才提供 `--external-judgments-dir` 导入已完成的绑定裁定。基线和当前报告都须为完整 `replay`，题集、资料摘要、模型/调度、评分配置相同；`compare()` 再逐组比较质量、完成率、引用、产物与耗时。缺分显示 `N/A`，不补默认分。

```powershell
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run.py @evalArgs --runtime current --mode replay --grade-report tests/agent_eval/results/current_replay.json --output tests/agent_eval/results/current_graded.json
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run.py @evalArgs --runtime baseline --mode replay --grade-report tests/agent_eval/results/baseline_replay.json --output tests/agent_eval/results/baseline_graded.json
& tmp/agentic-venv/Scripts/python.exe -B -X utf8 tests/agent_eval/run_review.py --provider apikl --output tests/agent_eval/results/review_measurement.json
```

`ready: true` 只表示整套测量与评分齐备。预算失败保留为低完成率/低分；缺题、缺评分、录制缺失、未知传输失败或绑定错误仍不能过门槛。未评分录制的非零退出码是正常的未就绪状态；必须查看报告和日志，不把非零统一解释为脚本崩溃。

## 隔离与证据

每题的工件、动作、配额与公开事件位于 `tmp/agent-eval/<run_id>/<case_id>/`；评测自选和知识库不访问生产用户数据，用量不写生产数据库。完整资料带来源和采集时点；回放报价不能作为当前实时行情。供应商原始推理正文不写评测产物，只保留结构化用量和传输耗时。

协议与资产测试使用 `tests/agent_eval/test_*.py`；它们验证录制、回放、绑定、共享配额与配置隔离，不给自然语言答案质量打分。历史模型拒绝、断流、超时及之前的评分都保存在 `results/`，历史状态以对应文件时点为准。
