# 预测账本 v1：运行与验收

公开页面 `/track-record`、只读 API `/api/benchmarks/us20-v1/track-record`。这两个入口不要求登录，仅展示固定公开样本，不包含用户聊天或自定义模型凭据。旧 API `/api/predictions/track-record` 仅保留为隐藏兼容入口，新客户端使用独立的 benchmark 地址。明细支持 `limit` / `offset` 翻页，汇总始终覆盖全部样本。

## 采集与评分

固定 `us20-v1` 股票池，共 20 只股票。每个交易日美东 08:45 开始、09:20 截止；Technical 预测五日上涨/下跌/横盘，Risk 预测五日按收盘序列计算的最大回撤是否至少 5%。两个 Agent 使用同一份截至前一交易日收盘的冻结数据；结果不确定时允许明确弃权。

每日 40 个机会，先首试后重试，最多 60 次 LLM 尝试、每个机会最多两次、并发 2。每次输出预算默认 4096 token、最低 2048，硬超时 60 秒；SDK/内部 helper 不重复重试。剩余不足 65 秒不启动新尝试，超时返回的结果不会越过截止登记。

行情拉取失败时机会保留 `queued`，记录数据错误但不消耗 LLM 尝试次数；下一轮按同一知识截止时间重新拉取，过 09:20 才记为 `missed`。已有冻结行情的首试优先，缺行情股票不会阻塞其它股票的重试；每日最多 20 次重试，并为全部 40 个机会保留首试额度。例如 2 个机会缺价时，其他 38 个首试加 20 个重试后，仍有 2 次预算供恢复行情的机会首试。

起点为发布后下一个常规交易时段开盘价 P0，终点为包含该日的第五个交易时段收盘价 P5。涨跌超过 ±0.5% 才归为上涨/下跌，边界值归横盘。风险事件使用 P0 和五个收盘的运行高点计算最大回撤，与终点跌幅不同。

交易日历使用锁定版本的 pandas_market_calendars，包含跨年、提前收市和时区处理。行情通过现有 `backend.tools.yfinance_client.create_ticker` 工厂复用 `YFINANCE_PROXY`，固定 yfinance 0.2.66 / Yahoo，显式关闭 auto_adjust、back_adjust 和 repair；不计现金分红回报，不做跨供应商回退。结算时冻结整个价格窗口，两类预测共享该窗口；缺行情显示等待数据，不延长预测期限。

该账本是固定公开样本的独立评估数据集；现有 PostgreSQL 个股 Prediction/Outcome 继续按用户隔离，两套样本不合并统计。
用户触发的 PredictionTrack 可以覆盖不同标的与判断范围；US20 账本每天固定 20 只股票、两个五交易日判断，并按相同样本与简单基准比较。两者的采样方式、期限、访问边界和存储不同，当前分别展示、分别统计。兼容旧账本地址的静态路由位于现有 `predictions_router` 的 ID 详情路由前；两个 Router 在应用中的注册顺序不影响新旧账本地址。

## 开关与部署准备

采集默认关闭。`.env.server.example` 提供以下部署配置项，真实配置写入不入库的 `.env.server`：

```dotenv
PREDICTION_ENABLED=true
PREDICTION_DAILY_ATTEMPTS=60
PREDICTION_OUTPUT_TOKENS=4096
PREDICTION_ALERT_EMAIL=your-own-alert-address@example.com
```

独立 watchdog 使用标准 SMTP 客户端读取 SMTP_SERVER / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / EMAIL_FROM，587 使用 STARTTLS、465 使用 TLS。收件人必须明确配置，不能根据提交邮箱或聊天内容推断。模型使用服务端已有端点配置；没有其它配置时可用 STEPFUN_API_KEY。后台预测显式清除请求级用户模型选择，不使用浏览器自定义 key。

部署命令示例（需在 push/部署前完成用户要求的汇报）：

```bash
IMAGE_TAG="$release_sha" docker compose --env-file .env.server --profile predictions up -d --build backend frontend prediction-watchdog
```

`prediction-watchdog` 是独立容器进程，复用后端构建配置与 SMTP，后端停止时仍会检查。后端维持单 worker；v1 不支持多个采集实例同时运行。数据写入 backend_data 卷内的 prediction_ledger.db，告警去重状态写入 prediction_watchdog.json。关闭/重启不得删除这些文件。

不能沿用只列 `backend frontend` 的启动命令：即使启用了 profile，显式服务列表也必须包含 `prediction-watchdog`。完成实际部署网络的 Yahoo 全池与 SMTP 验证后，再选择美东 08:45 前启用采集；若当日截止后才首次启用，当天 40 个机会会记为 missed 并参与低覆盖告警。

不使用 Docker 时，分别启动后端及 `python scripts/prediction_watchdog.py`；可用 `--once` 接入已有独立定时机制。看门狗默认每 300 秒检查，不能放在预测任务自己的 scheduler 中。共宿主部署不能覆盖整机故障，需要外部可用性监控时将检查部署到另一宿主。

## 健康与告警

`/health` 的 `components.prediction_collection` 展示应有批次、最近批次、接受数/40、尝试数和失败原因计数等。09:25 ET 后没有当日批次，或接受数低于 30/40，触发告警条件；30/40 与 38/40 只显示部分覆盖。休市、采集窗口内及功能关闭时不会触发低覆盖告警。

健康接口不发送邮件。独立 watchdog 对连续两次后端不可访问发告警，持久化去重；SMTP 失败最多尝试三次，不把未投递记作成功。SMTP 未配置会给出明确状态。告警条件与实际投递结果分别记录。

## 审计与公开原则

每个机会唯一登记，首次合法预测冻结；失败重试保留次数、实际端点/模型、提交参数、完成原因、token 用量和响应摘要。弃权保留理由、证据引用和提示版本。跨日重启会结清所有已过截止的未采集机会，避免旧批次悬空。公开结果按 Agent、实际模型确认状态、提示/策略/评分版本分组。供应商没有报告模型身份时显示未确认。

采集起点按股票池持久化：已有库取最早批次，新库取首次实际运行采集循环的纽约日期。重启时为起点之后、已过截止且没有批次的 NYSE 交易日补写每日 40 条 `missed`，不拉行情、不调用模型、不伪造预测或增加尝试次数。不会补写启用之前的历史；关闭采集时不登记新起点，已有起点也不会因关闭或重启而后移。

方向基准是相同已结算样本的“永远看多”；风险基准是“始终不发生”，并显示 TP/FP/TN/FN 与事件发生率。AI 落后基准也公开保留；不能通过删除失败样本、改窗口或换基准改善成绩。空结果显示等待首批结算，早期样本不足与窗口重叠明确提示。

测试 fixture 只在临时数据库/浏览器 mock 中使用，不写入公开账本。真实战绩必须先登记并自然经过五个交易日。技术测试通过不代表已经获得预测优势。

## 验证入口

后端聚焦测试：`backend/tests/test_prediction_forecasting.py`、`test_prediction_pipeline.py`、`test_prediction_watchdog.py`。覆盖结构化真实产出路径、推理 JSON、预算/重启/截止、日历、评分、源口径、失败可见、公开白名单和告警去重。

前端测试：`frontend/src/pages/trackRecord.test.tsx` 与 `frontend/e2e/track-record.spec.ts`。覆盖公开入口、待结算、AI 落后基准、未知模型、失败明细、历史分页及移动布局。

上线前须从实际部署网络验证 Yahoo 行情可达与样本池数据覆盖，并验证告警收件配置。新实例没有历史成熟样本是预期状态，不能通过导入开发 fixture 代替首批真实结果。
