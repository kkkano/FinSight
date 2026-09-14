# FinSight AI - 生产环境及 SSE 长连接断开故障排查总结 (2026-03-05)

## 故障现象

在生产环境中（Cloudflare Tunnel + Nginx + FastAPI），深度研究报告的生成（需要较长时间的 LangGraph 编排流）会在中途**无任何明确错误提示地静默中断**。
随后问题级联恶化为：**所有 API 请求（包括前端定期轮询的热门股票价格接口、K线数据接口等）都会同时被挂断（出现 `net::ERR_CONNECTION_CLOSED` 报错）**。

## 排查过程与错误归因

1. **初步怀疑：后端超时 / 无心跳**
   - 之前报告流耗时较长（10分钟+），认为可能是 Nginx 或 FastAPI 的网关层面的超时。但将其调整到了 2400s 并不能解决同时挂断所有请求的问题。
   - `FastAPI SSE (Server-Sent Events)` 虽加了 `keep-alive` 评论 `": keep-alive\n\n"`，前端也会遇到被上层网关干掉心跳包的问题。

2. **核心突破：Cloudflare Tunnel 的 HTTP/2 多路复用机制**
   - 查看容器状态均正常运转。但是查看 Cloudflare Tunnel 代理日志 `journalctl -u cloudflared` 发现有明显的：`Incoming request ended abruptly: context canceled`，而且它们总是**成批集中出现**，全都在 `connIndex=3` 上。
   - **根本原因**：
     我们的前端直接作为了反向代理配置 (`VITE_API_BASE_URL=https://finsight-ai.chat`)，导致**静态资源和后端API流量共用了一个 Cloudflare 的 HTTP/2 连接通道**。
     Cloudflare 边缘节点对长轮询/长连接（尤其是如果心跳机制被判定为无效流量，或单条请求的强制超时导致 Edge 重制底层的 H2 连接）进行清理时，**会发送底层的 GOAWAY 帧或者强制关闭底层的 TCP/H2 层连接**。由于 HTTP/2 是多路复用的，这条底层连接断开，会导致**跑在这条连接上的所有其他完全正常的、生命周期各异的 API 请求全部被连带抛弃，出现 `ERR_CONNECTION_CLOSED` 现象**。

## 综合解决方案

解决方案采用“底层架构切分 + 业务层防御”的兜底保障策略：

### 1. 架构级隔离 (The Silver Bullet)
**切分 API 和 前端静态资源的域名路由**：
将所有的 API 请求走独立的二级域名，使得它们的底层通信在 Cloudflare Tunnel 中拥有独立的连接池，互不干扰/殉爆。
- 修改 Tunnel Ingress Rule：
  - `finsight-ai.chat` -> `localhost:5173` (前端静态/Nginx)
  - `api.finsight-ai.chat` -> `localhost:8000` (后端接口)
- 对应的环境变量中，由 `VITE_API_BASE_URL=https://finsight-ai.chat` 改为 `https://api.finsight-ai.chat`

### 2. 网关超时与防发呆配置
- Nginx 对后端的 Read / Send Timeout 解除默认的 60s 限制：
  ```nginx
  proxy_read_timeout 2400s;
  proxy_send_timeout 2400s;
  proxy_buffering off; # SSE流式输出强要求
  ```

### 3. SSE 心跳穿透修正
由于不同反代/网关（包括 Nginx 的代理缓存甚至某些浏览器行为）可能抛弃 SSE 中的标准注释（`: heartbeat\n\n`），改用真正的数据块穿透：
- 心跳间隔从 15s 降低到 **8s**（应对某些网关 10s 发呆阻断原则）。
- 心跳有效 payload 取代标准的空评论，使用：`data: {"type": "heartbeat"}\n\n`。

### 4. 客户端（前端）补偿重联控制
在前端的 SSE `fetch` 接口增加了强力的边界接管：
- 用强包装函数 `wrappedOnDone` \ `wrappedOnError` 并打标记 `sawDone / sawError`。
- 如果底层的 ReadableStream 退出循环但未得到有效的业务 "done / end"，强制给 UI 抛出被切断的错误，或引导重新请求。不再面临业务层“无声僵死”的问题。

## 部署与同步陷阱注意
1. **Windows CRLF 符号问题**：若用 Windows 端的 SFTP 上传脚本或 Nginx 并替换容器内文件，一定小心行尾符问题导致容器启动 / Bash 执行报错。
2. **PyTorch 体积大的环境重建**：带构建参数 `--no-cache` / 废弃 Docker Cache 的重新打包，可能触发非常沉重的底层大依赖下载（如 PyTorch 取决你所在的网络节点，很容易因为 180MB的包直接断联导致容器打包构建挂死）。最终解决方法是以 `--build-arg` 只局部摧毁和清理前端的 Layer。

## 结论
这次排故证明，大模型带来的动辄几分钟到几十分钟的单次网络请求形态，和原本 Web 时代构建于 "短期响应、多路复用共享通道" 的代理与网关基础结构**极不匹配**。遇到牵一发而动全身的情况，**隔离通道、物理独立路由**才是最好的解药。