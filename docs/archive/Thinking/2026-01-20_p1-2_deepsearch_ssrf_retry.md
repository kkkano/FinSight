# P1-2 思考：DeepSearch SSRF 与重试

- 抓取链路是最容易被滥用的入口，先做“默认拒绝”比事后追踪更关键。
- 重试逻辑应放在 Session 层统一处理，避免多处散落的 `requests.get`。
