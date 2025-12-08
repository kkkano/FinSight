# Feature Log - 指数价格兜底 & K 线时间修正 - 时间：2025-12-08 14:02:27
- 负责人：Codex

## 背景 / 范围
- 修复两类体验问题：指数查询频繁失败、回复缺少具体买入价格，以及 K 线时间轴显示 08:00 的偏移。

## 实施内容
1) 指数价格兜底  
   - 新增 `_fetch_index_price`（yfinance.download 最近两日收盘），优先处理以 `^` 开头的指数。  
   - get_stock_price 对指数使用专属 pipeline（index -> Stooq -> search）；Orchestrator/bridge 注册 `index_price` 源，健康面板可见。  
2) 回复带买入档位  
   - get_stock_price 在成功返回后解析当前价，追加 “Suggested ladder: ±1%/±2%” 两档分批价，保证有具体数字。  
3) K 线时间 08:00 偏移修正（主路径）  
   - yfinance 主路径/指数路径/备用路径的 `time` 字段改为 `YYYY-MM-DDT00:00:00`，避免被前端当作 UTC 后显示 08:00。

## 测试
- `python -m pytest backend/tests/test_orchestrator_metadata.py backend/tests/test_kline.py -q`  
- 结果：通过（test_kline 仍有既有 PytestReturnNotNoneWarning，未更改原测试返回结构）。

## 影响 / 下一步
- 指数查询可回退到 yfinance 下载，避免一律失败；健康面板能看到 index 源调用。  
- 响应默认附带两档买入价，减少“给不出数字”。  
- K 线时间主路径已去除 08:00 偏移；其他付费源如 IEX/Tiingo/Marketstack 尚保留原格式，后续可视化若仍有偏移再统一归一化。
