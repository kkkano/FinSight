# Massive.com (原 Polygon.io) API 配置完成

## ✅ 配置状态

**API Key**: `NnE_U49S5fwLhgGjqpgBAKCVEZQaGpLE`  
**状态**: ✅ 已配置并测试通过

## 📋 配置详情

### 1. API 端点
- **URL**: `https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}`
- **注意**: Polygon.io 已更名为 Massive.com，但 API 端点仍为 `api.polygon.io`

### 2. API 格式
- **日期格式**: 必须作为路径参数，格式为 `YYYY-MM-DD`
- **查询参数**:
  - `apikey`: API key（必需）
  - `adjusted`: `true`（调整后价格）
  - `sort`: `asc`（升序）
  - `limit`: `50000`（最大数据点数）

### 3. 响应状态
- `OK`: 正常响应
- `DELAYED`: 延迟数据（但数据仍可用）

## 🔧 代码实现

### 配置位置
- **文件**: `backend/tools.py`
- **变量**: `MASSIVE_API_KEY`（默认值已设置）
- **函数**: `_fetch_with_massive_io()`

### 数据源优先级
Massive.com 作为**策略 5**，在以下数据源失败后使用：
1. Alpha Vantage
2. yfinance (Ticker.history)
3. Finnhub
4. Yahoo Finance 网页抓取
5. **Massive.com** ← 当前配置
6. yfinance (download 备用方法)

## ✅ 测试结果

```
测试股票: AAPL
✅ Massive.com 成功获取 20 条数据
   时间范围: 2025-10-31 至 2025-11-28
```

## 📝 使用说明

### 环境变量（可选）
如果需要通过环境变量配置，可以在 `.env` 文件中添加：
```env
MASSIVE_API_KEY=****
```

### 代码中已设置默认值
如果未设置环境变量，代码会使用默认的 API key。

## 🎯 功能特性

1. **多时间周期支持**: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max
2. **自动回退**: 如果其他数据源失败，自动使用 Massive.com
3. **错误处理**: 完善的错误日志和异常处理
4. **数据格式**: 自动转换为 ECharts 所需的格式

## ⚠️ 注意事项

1. **API 限制**: 注意 Massive.com 的 API 调用限制
2. **数据延迟**: 可能返回 `DELAYED` 状态，但数据仍可用
3. **日期格式**: 日期必须作为路径参数，不能作为查询参数

## 🚀 下一步

现在系统已配置好 Massive.com API，可以正常获取股票历史数据。如果其他数据源遇到速率限制，系统会自动使用 Massive.com 作为备用数据源。

