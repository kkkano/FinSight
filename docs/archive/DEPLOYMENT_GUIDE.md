# FinSight 部署与常驻指南

## 环境变量（核心）
- SMTP: `SMTP_SERVER` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` `EMAIL_FROM`
- 调度开关：
  - `PRICE_ALERT_SCHEDULER_ENABLED=true`
  - `PRICE_ALERT_INTERVAL_MINUTES=15`（按需调整）
  - `NEWS_ALERT_SCHEDULER_ENABLED=true`
  - `NEWS_ALERT_INTERVAL_MINUTES=30`
- 行情/新闻 API（可选回退）：
  - `FINNHUB_API_KEY`，`ALPHA_VANTAGE_API_KEY`，`MASSIVE_API_KEY` 等

## 启动后端（Windows 示例）
```bash
set PRICE_ALERT_SCHEDULER_ENABLED=true
set NEWS_ALERT_SCHEDULER_ENABLED=true
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```
保持窗口不关即为常驻；如需开机自启，可用“任务计划程序”在登录时运行以上命令（工作目录指向项目根）。

## 前端（可选）
- 开发：`cd frontend && npm run dev -- --host --port 5173`
- 生产：`npm run build` 后使用任意静态服务器托管 `dist`。

## 调度与日志
- 调度日志：`logs/alerts.log`，记录价格/新闻轮次、发送条数。
- 手动触发：
```bash
python - <<'PY'
from backend.services.alert_scheduler import run_price_change_cycle, run_news_alert_cycle
print(run_price_change_cycle())
print(run_news_alert_cycle())
PY
```
- 订阅数据存储：`data/subscriptions.json`。
