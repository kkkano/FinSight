# Agent 评测与回放

更新：2026-11-13。生产代码仅有 `backend/agent_runtime/`；`baseline_runtime/` 和 `reference/` 只用于冻结旧实现对照，不进入生产镜像。原始失败记录保留，不用挑选成功尝试拼成通过结果。

## 当前状态

- M1 旧实现基线已完成：`results/m1_qwen_baseline_complete.json`，60/60 独立评分，均分 3.33/7，正常完成 12/60。它是录制阶段基线，不能直接作为新实现回放的比较对象。
- 当前被测模型为用户指定的 APIKL `gpt-6.1-terra`，独立评分模型为 `gpt-6.1-sol`。原生工具调用与 SSE 已通过[模型探针](results/m0_apikl_terra_probe_20261113.json)，独立 `submit_score` 链路通过[合成探针](results/m0_apikl_judge_probe_20261113.json)；这些探针不代表 60 题质量门槛已通过。
- 原先指定的 `gpt-6-luna` 在 Chat Completions 与 Responses 路径均返回 `model_not_found`，不是可用别名，见[协议核验](results/m0_apikl_protocol_followup_20261113.json)。Vectide 的历史对照保留在 `results/vectide_matched_execution.json`：当前实现录制完成 34/60，基线随后因周额度耗尽中断，不能与 APIKL 批次混用或算最终通过。
- M4 用 `run_review.py` 单独测量 12 对正确/注错答案；合成资料明确标注，不能当真实行情。Step 5 已有完整测量；Vectide 失败与恢复批次分别保存于 `results/m4_vectide*`，不能混为一个批次。
- APIKL Terra 的[本轮核查测量](results/m4_apikl_terra_review_20261113.json)与[独立 Sol 语义裁定](results/m4_apikl_terra_adjudication_20261113.json)均完整完成 24/24：注错语义检出 12/12、原答案语义误报 0/12、不可用 0/24。结构测量中 1 条原答案收到完整性提醒，独立评审判定该提醒有资料依据；它仍保留在原测量，不改写为无 finding。评分阶段两条无效提交仅补判失败项，原提交保存在 `previous_attempts`，有效评分未重跑。
- M3 [原严格 Tape 测量](results/apikl_matched_execution_20261113.json)保留完整录制及回放失败。当前/基线录制各 60/60、正常全回合终态 52/49；双方严格回放各 60/60、正常终态 54/50，但新自然查询参数大量 `tape_miss`，不能算通过。严格回放数据不混入新语料 provider 的正式比较。
- 新 M3 代次使用统一冻结文档全文检索及原生产者快照离线重执行。原模型参数、预算、调度、被测源码和冻结基线保持绑定；独立分页评分统一评价全部 120 题。首次试跑的全进程 socket 阻断误伤 Windows 模型事件循环，原失败和部分答案已保留；现改为专用离线子进程，32 项相关合同测试通过，[新双方试跑](results/apikl_frozen_pilot_execution_20261113_isolated.json)各完成 5 题采集，当前/基线正常终态 4/5。当前实现 1 题真实预算耗尽，结果未重试。现正[各完整回放 60 题并统一评分](results/apikl_frozen_remaining_execution_20261113_isolated.json)，实际完整测量与质量门槛尚未完成。
- [APIKL 模型元数据](results/m0_apikl_terra_metadata_20261113.json)与[公开文档查证](results/m0_apikl_terra_public_docs_20261113.json)均未提供 Terra 的官方容量和视觉规格。[实际长输入与 PNG 探针](results/m0_apikl_terra_capacity_vision_20261113.json)已通过：供应商报告输入 101285 tokens；96×96 PNG 的四象限颜色全部识别正确。131072/16384 仍是本地预算，101285 是本次最大已测输入，不能推断官方上限或金融图表 OCR 精度。
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

APIKL 本轮独立评分使用 `FINSIGHT_EVAL_JUDGE_MODEL=gpt-6.1-sol`、相同 API 地址与安全引用的 API key，`--judge-protocol tools`；评分模型必须与被测模型不同。研究运行从一开始绑定相同评分配置，`--no-judge` 只推迟评分，不改变评分身份。新冻结语料批次通过 `run_paged_grading.py` 实际调用同一独立模型，不使用旧非分页评分拼接结果。

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

## 新统一冻结语料与分页评分

`frozen_corpus_provider.py` 从原严格录制的全部文档构建 SQLite FTS5/BM25 语料，复用现有 RAG 词法 tokenizer。当前冻结语料包含 566 条原工具记录、1636 篇按内容 SHA 去重的文档、600 条捕获的生产者记录；保存原 URL、发布/观察时间、实体出处、完整原文与捕获边界。自然查询由标准全文检索处理，不追加意图关键词规则、不借相近参数补数据。SEC 有限结构参数用真实生产函数和已捕获 HTTP 快照离线重执行；其他金融工具仅允许完整参数对应的 producer 快照重执行。缺来源保留 `frozen_corpus_gap`，不得伪装成新联网结果。

`run_frozen_eval.py` 包装原测量入口，不修改被测运行时。双方使用 `fixtures/apikl-frozen-provider-20261113` 同一个 manifest/数据库；每次实际调用另存 `frozen_provider_calls.json` 并绑定 SHA。语料、provider、driver、题集和运行时摘要相同才具备比较条件。此测量只证明同资料上的决策质量，真实联网及产品能力由独立线上验收证明。原始资料、请求和数据库留在本机；安全摘要与代码版本化，不提交密钥或整批大原文。

`frozen_offline_worker.py` 为每个研究评测进程维护一个专用离线解析子进程；生产函数、其内部线程和 socket 阻断都在该子进程内，模型连接与 Windows asyncio self-pipe 保持在父进程。子进程不接收供应商密钥或用户凭据。完整快照与相同实际参数仍由原生产函数处理，缺完整来源继续返回 gap。每次调用绑定子进程隔离器的源文件 SHA；隔离器变化后，双方须使用新同版本批次。

`run_frozen_comparison.py` 依次运行可复核的 `pilot`、`full`、`grade`、`compare` 阶段，安全加载 `.env.runtime.local`，固定本轮双方模型/语料/调度。阶段状态与 PID、实际命令、输出摘要、时间预算与耗时策略分别保留；不会把未判分的非零退出当崩溃，也不会覆写中断测量。默认 `non_regression` 保持原 `compare()` 门槛；用户最新质量优先要求使用显式 `report_only`，只把耗时退步改为观察项，其余输入、独立评分与质量门槛不变。旧报告缺省仍按原严格策略解释，失败必须公开保留。

正式对照在已核验的生产 Linux 镜像内执行；不能用宿主 Windows 系统 Python 直接运行下列批次。`environment_preflight.py` 核对父子进程解释器、生产分发版本与模块导入，`offline_network_isolation.py` 在离线工具进程导入生产者前安装 `no_new_privs` 与 seccomp，同时阻断 Python 和 C/libcurl 的 IPv4/IPv6 socket。模型父进程仍可访问供应商与独立计算服务。原始录制目录、冻结语料和安全配置均只读挂载；跨平台路径由显式 mount manifest 映射，原件及数据库不修改。

下面命令在容器内 `/app` 执行，三个 manifest 必须来自同一轮真实预检。每次隔离器、provider 或 driver 改动使用新的 `--generation`；不覆盖旧失败或混用不同环境的成绩。

```bash
eval_args=(--generation 20261114_quality_priority_linux --timeout 300 --latency-policy report_only
  --source-git-metadata /app/tmp/r261113/linux-eval/host-git-metadata-20261114.json
  --mount-manifest /app/tmp/r261113/linux-eval/mount-manifest.json
  --environment-manifest /app/tmp/r261113/linux-eval/environment-preflight.json)
python -B -X utf8 tests/agent_eval/run_frozen_comparison.py --phase pilot "${eval_args[@]}"
python -B -X utf8 tests/agent_eval/run_frozen_comparison.py --phase full "${eval_args[@]}"
python -B -X utf8 tests/agent_eval/run_frozen_comparison.py --phase grade "${eval_args[@]}"
python -B -X utf8 tests/agent_eval/run_frozen_comparison.py --phase compare "${eval_args[@]}"
```

```powershell
chcp 65001 > $null
$frozenArgs = @('--provider','apikl','--jobs','2','--request-interval','6.1',
  '--timeout','180','--model-protocol','sse','--no-judge','--judge-protocol','tools',
  '--fixtures-root','fixtures/apikl-frozen-provider-20261113')
python -B -X utf8 tests/agent_eval/run_frozen_eval.py @frozenArgs --runtime current --mode replay --output tests/agent_eval/results/frozen_current.json
python -B -X utf8 tests/agent_eval/run_frozen_eval.py @frozenArgs --runtime baseline --mode replay --output tests/agent_eval/results/frozen_baseline.json
python -B -X utf8 tests/agent_eval/run_paged_grading.py --source tests/agent_eval/results/frozen_current.json --output tests/agent_eval/results/frozen_current_graded.json --shared-quota tmp/agent-eval/independent_judge_quota.sqlite
python -B -X utf8 tests/agent_eval/run_paged_grading.py --source tests/agent_eval/results/frozen_baseline.json --output tests/agent_eval/results/frozen_baseline_graded.json --shared-quota tmp/agent-eval/independent_judge_quota.sqlite
```

`paged_judge.py` 保留完整题目/原答案/资料 canonical JSON 和 SHA，提供结构路径、JSON 解码路径、Unicode/UTF-8 范围、cursor/has_more 与每页 hash；大节点返回可继续读取的描述符。每轮最多 4 页、单页最多 8192 UTF-8 字节，完整共享库原件/目录/全文检索始终可读。模型已收到的旧工具页可用可回读 receipt 替换，未交付页不压缩。先独立调用 `finish_reading` 保存公开事实笔记，最后仅调用原 `submit_score` 契约。每题读取总预算 600000、单请求仍受 131072 上下文和 160000 预约限制；失败保留 `N/A`。

`grade_apikl_budgeted.py` 通过实际 `BudgetedModel`、共享账户标识与等待式 `LeaseLimiter` 预约 RPM 30/TPM 250000/最小间隔 10 秒，并按供应商实际 usage 结算。供应商返回模型必须为声明的 Sol。`--trial --case reports-02` 仅用于非正式长报告验证；正式批次必须完整 60 题。`--resume` 只补失败评分，原失败文件归档，已成功评分不重跑；评分实现或 prompt 改动必须重新建立统一批次。

## 隔离与证据

每题的工件、动作、配额与公开事件位于 `tmp/agent-eval/<run_id>/<case_id>/`；评测自选和知识库不访问生产用户数据，用量不写生产数据库。完整资料带来源和采集时点；回放报价不能作为当前实时行情。供应商原始推理正文不写评测产物，只保留结构化用量和传输耗时。

协议与资产测试使用 `tests/agent_eval/test_*.py`；它们验证录制、回放、绑定、共享配额与配置隔离，不给自然语言答案质量打分。历史模型拒绝、断流、超时及之前的评分都保存在 `results/`，历史状态以对应文件时点为准。

显式 `FINSIGHT_EVAL_ARTIFACT_ROOT` 可将每题完整事件、模型请求、分页评分资料和离线日志保存到专用磁盘；目录必须挂载到两方及评分进程的同一路径，并写入测量元数据。默认目录保持兼容，外部引用只允许落在配置的产物根内。当前大产物在 D 盘，原冻结资料仍只读保留在原工作树，安全摘要与完整原件各有独立 SHA。上面的单独 `run_frozen_eval.py` 180 秒示例是旧预算重现入口，不代表当前质量优先正式批次。
