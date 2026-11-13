# 历史研究对照包

本目录保存退出生产的旧研究实现、原测试和金样。`manifest.json` 逐文件记录来源与 SHA256；`retirement_scope.json` 列出删除、保留和测试迁接范围。旧文件不通过生产兼容 alias 重新暴露。

`loader.py` 仅在评测子进程中按精确模块名加载归档。原 `baseline_runtime` 的源码、提示词和历史摘要算法保持不变。当前版本录制工具原始结果时只使用冻结工具包装的 `invoke`，不启用旧图加载器。

冻结的 Technical/Risk、基础类、图表模块和 orchestration 加载闭包仍在生产路径，27 个受保护文件由 manifest 校验。历史个人预测和 checkpoint 清理由 `backend/common` 提供。

在仓库根目录执行：

```powershell
tmp/agentic-venv/Scripts/python.exe -B tests/agent_eval/run.py --runtime baseline --list
tmp/agentic-venv/Scripts/python.exe -B -m pytest tests/agent_eval/test_baseline_runtime.py -q -p no:cacheprovider
tmp/agentic-venv/Scripts/python.exe -B tests/agent_eval/reference/run_tests.py -q --tb=short
```

对照单测默认禁网，Windows asyncio 自唤醒用的标准库 socketpair 除外。根 pytest 的 `test_reference_suite.py` 和 CI 都会调用该独立门禁；目录不被根 pytest 再次直接收集，避免旧模块污染当前测试进程。

`reference_test_selection` 只选择迁出的旧断言。混合文件中的现行业务断言继续在 `backend/tests` 执行；对应关系见 `live_contract_map.json`。原始测试文件完整保留，不使用新增 skip/xfail 隐藏失败。`scripts/` 下需要真实供应商的历史手工探针不属于离线单测或当前质量分数。

原生答案质量由 `agent_eval` 的固定输入、回放与核查评估承担。这里的旧关键词、路由和模板断言只描述历史版本，不是新运行时的需求。
