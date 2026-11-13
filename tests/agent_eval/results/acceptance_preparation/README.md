# 48项线上验收准备

当前48项全部为 **pending**，线上通过数为0。此目录的矩阵、动作模板和离线自检不是线上验收结果。M6/M8 mock走查、M9本机E2E、第7节模型评测均不能替代第12节产品验收。

## 原文与前置

`../../acceptance_cases.json` 是唯一验收定义，逐字保存计划第12节的输入、期望和查询；完整覆盖见 `coverage_matrix.md`。A/B/C/D/E/F/G分别为8/8/7/8/5/6/6项。

A6复用multiturn-03首问，A7复用multiturn-02首问，A8复用multiturn-04首问；B3复用statistics-02首问，B4复用comparison-01，B5复用statistics-03；QA报告可由reports-01原问生成。前置问题只引用第7节原文，不改写第12节问题。已有真实QA结果可复用，不能把本地mock当真数据，也不把陈旧录制报价当当前报价。

截图采集约定为桌面1440×900、移动390×844；390px来自E1原文，其余高度与桌面尺寸只是采集设置。每个case声明所需视口。

## 现在可以执行的离线命令

在工作树根目录：

```powershell
chcp 65001 > $null
tmp/agentic-venv/Scripts/python.exe -B .omx/deploy/agentic_acceptance.py prepare
tmp/agentic-venv/Scripts/python.exe -B .omx/deploy/agentic_acceptance.py self-test
```

这两个命令不连接服务器、不访问模型、不加载实际凭据。离线自检只验证原文、镜像证明边界、SSE/引用/hash协议及脱敏。

## 部署完成后再执行

用户已授权上线和走查，不新增审批。`--release-manifest` 是实际部署证明，不是再次申请许可：按 `deployment_observation.template.json` 记录真实docker image ID、镜像manifest文件及SHA256、已观察的前端build ID、观测时点。收集器会核对manifest/image ID，并读取实际 `/app-version.json` 核对前端版本。没有真实部署观测时拒绝live路径。

把输入模板复制为私有QA配置，填环境变量名、QA自选PNG/报告/公开分享路径和实际模型ID。`model_id`为空时只采用真实目录声明且available的default_model_id。两个QA身份必须预先指定，禁止使用内部X-API-Key、service-role或普通用户资料冒充QA。现有remote.py的SSH已固定known_hosts/RejectPolicy；准备和采集脚本不使用SSH读取私密配置。

QA访问令牌仅经环境变量传入，并由真实 `/api/user/profile` 核对user_id。浏览器使用专用QA正常登录得到的Playwright storage-state JSON，通过指定环境变量以内存方式传入；必须只有目标站点和已验证QA身份，不能使用个人浏览器状态。收集器不导出storage_state，不保留含Authorization的原始Playwright trace，不调用账号创建、OTP、找回或邮件接口。

部署证明提供后，可复现API采集命令：

```powershell
tmp/agentic-venv/Scripts/python.exe -B .omx/deploy/agentic_acceptance.py capture-api --case A7 --release-manifest .omx/deploy/agentic_acceptance_deployed.json --settings .omx/deploy/agentic_acceptance_inputs.json
```

浏览器采集命令：

```powershell
tmp/agentic-venv/Scripts/python.exe -B .omx/deploy/agentic_acceptance.py capture-browser --case A2 --release-manifest .omx/deploy/agentic_acceptance_deployed.json --settings .omx/deploy/agentic_acceptance_inputs.json --actions tests/agent_eval/results/acceptance_preparation/actions/A2.json
```

`actions/*.json` 给出逐字问题的基本可执行步骤。只读页面默认导航并采集；设置、多账号、下载、键盘/读屏等复合步骤需要原生浏览器执行者根据实际DOM补充动作。动作支持click/click_testid、fill_query、press、reload、navigate、checkpoint、wait_busy、wait_terminal、upload_qa_png、offline_30_seconds和仅限指定秘密字段的fill_secret；不能执行任意JS，不能提供任意改写查询。填问句时只能选case原问或已登记的第7节setup原问。

C4使用真实浏览器断网30秒后重连，不能伪造成功SSE。B7/C1/C2/C6/C7需要隔离QA范围内的真实故障证据；不关闭全站配置、不新增后门、不改数据库。无法安全复现时保持pending。C6服务器保存失败不能由旧浏览器快照失败替代。真实输入法、读屏和缺失模型能力分支同样不能由模拟事件/空元数据代替。

## 证据与独立评审

每次采集使用新的目录，保存原问、SSE原字节SHA256、脱敏事件、唯一run/session绑定、终态、原始回答hash、引用表、产物、真实持久化回读hash、截图、DOM/ARIA/输入事件。回答原文只保留在该QA验收资料中；供应商原始推理只保留来源类型、长度/哈希，截图中遮盖推理正文与秘密输入。F5按已知测试秘密精确检查页面/存储泄漏，只保留布尔值和键名。

协议结果不等于内容/覆盖通过。`review_packet.json` 必须交给与被测运行独立的原生评审，逐项核对计划原文、文案第11节与证据；不使用关键词打分，也不把被测模型自己的review判定当验收。

按 `independent_review.template.json` 保存独立评审。每个未自动确认的必要协议项需要带证据的protocol_adjudications；自动协议失败、缺截图、秘密泄漏或无真实QA故障证据都不能被标为通过。

```powershell
tmp/agentic-venv/Scripts/python.exe -B .omx/deploy/agentic_acceptance.py record-review --capture-directory tests/agent_eval/results/acceptance_live/RELEASE/A2/CAPTURE --review .omx/deploy/agentic_acceptance_review_A2.json
```

本阶段没有运行任何live命令。所有case依然pending，等根代理明确部署完成并提供实际部署证据后再执行。

按真实release离线汇总全部48项，不读取服务器，也不选择性拼接通过尝试：

```powershell
tmp/agentic-venv/Scripts/python.exe -B .omx/deploy/agentic_acceptance.py summarize --release-manifest .omx/deploy/agentic_acceptance_deployed.json
```

汇总保留所有尝试；最新尝试尚未独立评审时该项仍pending。
