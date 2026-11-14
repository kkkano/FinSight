# 独立计算作业

更新：2026-11-13。当前 dispatcher/job 源码、默认配置和实际发布分别记录；生产身份及本轮候选见[运行手册](../../docs/11_PRODUCTION_RUNBOOK.md)。

HTTP 调度器不运行用户 Python。它为每次请求创建独立 Docker 输入卷，通过可信初始化容器只写入 JSON，再让非 root 作业容器只读挂载输入。用户代码在 `datasets`、`pd` 和 `np` 可用的命名空间中赋值 `result`，结果必须可序列化为有限数值 JSON。DataFrame（包括嵌套值）按 `to_dict(orient="records")` 转换，数值不变且不包含索引；有意义的索引应先 `reset_index()`。Series 仍需显式转换，非有限数值与 1 MiB 输出限制保持不变。图表仍经过主服务的声明式 artifact 校验，不能提交可执行 HTML/JS 文件。

默认仅允许一个任务、15 秒总预算、512 MB 内存、1 CPU、64 PID。网络关闭、根目录只读、capabilities 全部删除、禁止提权，使用 Docker 内置 seccomp、私有 PID/IPC/cgroup namespace 和独立 64 MB `/tmp`。代码最多 16000 字符，请求最多 4 MiB，结果最多 1 MiB，日志保留最多 16 KiB。直接写文件描述符造成的输出淹没会触发取消。

每次作业创建任何容器或卷之前都会读取计算宿主 `/proc/meminfo` 的 `MemAvailable`。默认需要至少 768 MiB 可用物理内存，即 512 MiB 作业上限加 256 MiB 保留余量；swap 不计入可用额度。内存不足返回 `analysis_capacity_insufficient`，无法读取有效指标返回 `analysis_capacity_unavailable`，均不启动作业。调度器与 Docker daemon 必须部署在同一计算宿主，不能让本机内存指标替代远端 daemon 的容量。

输入初始化进程以 root 运行，但只把 stdin 写入新卷，不解析或执行 Python；实际用户代码始终使用 UID/GID 65532。卷在结束时删除，任务之间不复用可写数据。任务取消、超时、失败均强制删除两个容器和输入卷；清理失败会关闭接单能力，重启后仅回收相同 `FINSIGHT_ANALYSIS_WORKER_ID` 标签的遗留作业。一个 Docker daemon 上的独立调度实例必须使用不同 worker id，不能用相同 id 横向扩容。

## 配置与启用

默认部署不启动计算服务。可选 `compute` profile 与 `local-ml` profile 独立。

在安全部署配置中提供至少 32 字符的随机 `FINSIGHT_ANALYSIS_WORKER_TOKEN`。主服务需要设置 `FINSIGHT_ANALYSIS_WORKER_URL=http://compute-dispatcher:8020` 并持有相同 token；调度器通过 compose 的显式 environment 获得该 token，不读取主服务的完整 env_file。示例不包含实际密钥。

`FINSIGHT_ANALYSIS_JOB_MEMORY_MB` 和 `FINSIGHT_ANALYSIS_MEMORY_RESERVE_MB` 默认分别为 512/256 MiB，`FINSIGHT_ANALYSIS_ADAPTIVE_MEMORY=false`。固定模式要求当次 `MemAvailable >= job + reserve`，配置错误或超出边界会关闭服务。

显式启用 adaptive 时，作业内存为 `min(max_job, floor((MemAvailable - reserve) / 64) * 64)` MiB，低于 `FINSIGHT_ANALYSIS_MIN_JOB_MEMORY_MB` 拒绝。最小值默认 128 MiB；当前低内存发布配置可显式选择 min/max/reserve=128/256/128，仍需当次实际物理容量，不计 swap。单并发、无网络和清理约束不变。默认值、显式配置与历史小算例峰值不能互相替代。

```bash
docker compose --env-file .env.server --profile compute build compute-job-image compute-dispatcher
docker compose --env-file .env.server --profile compute up -d compute-dispatcher
```

`compute-job-image` 仅预建镜像并退出，调度器启动时检查 Linux、seccomp、资源限制、总内存与镜像配置，解析不可变镜像 ID 后才接单。启动条件不足时 `/health` 返回 503，不降级为主进程执行。服务已就绪也会在每次作业前重新执行实际可用内存检查；`/health` 的就绪状态不保证下一次作业一定通过容量门禁。调度镜像只安装 `docker-cli`，不需要安装 Docker daemon/containerd。

只有调度器持有 Docker socket，这等同于管理计算宿主的权限。不要把该 HTTP 服务或 Docker socket 暴露到公网；生产推荐专用计算宿主。公开业务 API 和作业容器均不能接触 socket。业务 API 跨宿主连接时应通过私网 TLS 保护 HTTP 调度链路，调度器仍与它使用的 daemon 同宿主。调度器不信任模型指定的镜像、路径、命令参数。

## HTTP 合同

作业环境提供 `datasets`、`frames`、`get_frame`、`pd`、`np` 和 `finsight`。`get_frame` 从本请求授权资料生成表；SEC CompanyFacts 可用具名 `companyfacts` 表，完整字段/单位/财期仍来自原数据。`finsight` 提供均线、统计、连续下跌、回撤事件、共同起点比较、估值情景和财务比率；函数结果与假设、方法及来源关系返回主运行时，日志不作为金融证据。

`POST /jobs` 使用 `Authorization: Bearer <token>` 和 `Content-Type: application/json`：

```json
{"code":"result = float(pd.DataFrame(datasets['dataset_ref'])['value'].mean())","datasets":{"dataset_ref":[{"value":1},{"value":3}]},"timeout_seconds":15}
```

`timeout_seconds` 可省略，取请求预算和 worker 预算的较小值，协议硬上限 60 秒。数据引用的用户/会话授权由主服务校验，worker 只接受当前请求内的数据，不解析外部路径或 URL。运行期间 HTTP 断线会触发取消并等待清理。

成功返回 `status=ok`、`result`、有限日志以及 `job_id/code_hash/input_hash/duration_ms`；失败返回 `status=error` 和稳定错误码，例如 `analysis_timeout`、`analysis_cancelled`、`analysis_memory_limit`、`analysis_output_limit`、`analysis_cleanup_failed`。未配置/未就绪返回 503，未鉴权返回 401，繁忙返回 429，代码和结果错误使用正常协议响应。接口不会回传 Docker stderr、内部堆栈或调度密钥。

## 验证

```bash
python -m pytest backend/tests/test_analysis_worker.py backend/tests/test_analysis_worker_docker.py
```

上述默认运行模拟 CLI/HTTP 合同测试，真实容器验收明确跳过。具备 Linux Docker 且预建镜像后，显式设置 `FINSIGHT_ANALYSIS_DOCKER_TEST=1` 再运行 `backend/tests/test_analysis_worker_docker.py`，验证网络、权限、只读输入、主服务密钥缺席、跨任务文件隔离、超时与子进程清理。

2026-11-07 已在本机 WSL Debian 的独立 Docker daemon 完成构建与真实验收：52 项测试通过、无跳过，其中 6 项为实际容器隔离/容量测试；另外通过实际 uvicorn HTTP 端口完成健康检查与 Pandas 作业。192/256 MiB 下的一万行滚动均值算例进程 RSS 峰值分别约 76.6/76.3 MiB；cgroup 峰值约 51 MiB。进程 RSS 与 cgroup 对共享页的统计口径不同，不能把小算例峰值视为任意代码的内存保证。

验收还实际观察了取消/超时前的 `sleep` 子进程，随后确认所属容器和输入卷全部清除。镜像未压缩大小为 job 274,829,836 字节、dispatcher 183,109,344 字节。详细构建日志、测试 XML、容量及 HTTP 观测保存在该工作树的 `.omx/compute-live/`；这是本机验收，不代表生产容量足够或生产计算已启用。
