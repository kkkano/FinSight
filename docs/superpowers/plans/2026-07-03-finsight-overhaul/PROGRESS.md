# 执行进度账本（唯一进度事实源）

| 日期 | 任务 | commit | 测试结果 |
|------|------|--------|----------|

## Installed Dependencies

## Deviations

- 2026-07-03 | 环境 | 测试 LLM 端点 http://175.178.159.112/v1 的 /models 正常但 chat completions 全模型报 upstream_error（sub2api 上游故障，有升级镜像修复的前科）。不阻塞 WP0/WP1（LLM-off 路径）；进入需要真 LLM 的环节（WP2 shadow 对拍、部署冒烟）前需复测并提醒主人。
- 2026-07-03 | 环境 | 本地 Python 3.12.10（spec 基线 3.11）：requirements 按 pin 版本安装，若有兼容性问题记录于此。

