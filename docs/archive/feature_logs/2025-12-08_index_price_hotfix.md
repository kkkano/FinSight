# Feature Log - 指数价格兜底热修复 - 时间：2025-12-08 14:18:00
- 负责人：Codex

## 背景 / 范围
- 指数（如 ^IXIC）通过 yfinance 经常被限流，导致回复空洞；同时终端编码对 ✓/✗ 符号不友好。

## 实施内容
1) 指数价格兜底链路  
   - `_fetch_index_price`：yfinance.download 失败后，自动回退 Stooq 免 Key，再回退搜索 `_fallback_price_value`，保证返回价格字符串。  
   - `get_stock_price` 指数场景首选 `_fetch_index_price`，成功即返回，并沿用分批价逻辑。  
2) 日志编码兼容  
   - 将 price pipeline 日志中的 ✓/✗ 改为 ASCII（OK/FAIL），避免 gbk 环境报错。  
3) 分批价文案 ASCII 化  
   - “Suggested ladder” 文案改为 “+/-1% / +/-2%”，避免 ± 符号乱码。

## 测试
- `python -m pytest backend/tests/test_orchestrator_metadata.py backend/tests/test_kline.py -q`  
- 结果：通过（test_kline 仍有既有 PytestReturnNotNoneWarning，未修改原测试结构）。

## 影响 / 下一步
- 指数查询不再因 yfinance 限流而返回空文本，健康面板 index 源可统计。  
- 命令行/日志在 gbk 环境下不会因符号编码中断。  
- 后续可考虑：对 IEX/Tiingo/Marketstack 返回的 K 线时间再做统一 UTC 化（如出现偏移再处理）。
