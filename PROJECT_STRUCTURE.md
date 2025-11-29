# FinSight 项目结构说明

## 📁 核心文件（当前使用）

### 主要代码文件
- `agent.py` - 原始 ReAct Agent 实现
- `langchain_agent.py` - **LangChain 1.0+ 版本的 Agent（最新）**
- `langchain_tools.py` - **LangChain 1.0+ 版本的工具定义（最新）**
- `tools.py` - 底层金融数据获取工具实现
- `llm_service.py` - LLM 服务封装
- `config.py` - 配置文件
- `main.py` - 主程序入口

### 测试文件
- `test_langchain.py` - **LangChain 1.0+ 版本的测试脚本（最新）**

### 配置文件
- `.env` - 环境变量和 API 密钥
- `requirements.txt` - 项目依赖（原始版本）
- `requirements_langchain.txt` - **LangChain 1.0+ 依赖（最新）**

### 文档
- `readme.md` - 项目说明（英文）
- `readme_cn.md` - 项目说明（中文）
- `CLAUDE.md` - Claude Code 项目记忆

## 📦 归档文件夹

### `archive/old_langchain_versions/`
存放旧版本的 LangChain 实现文件：
- `langchain_agent.py` - 旧版本 Agent
- `langchain_agent_new.py` - 中间版本
- `langchain_agent_real.py` - 另一个版本
- `langchain_tools.py` - 旧版本工具
- `streaming_support.py` - 流式输出支持（未使用）
- `toolsbackup.py` - 工具备份

### `archive/test_files/`
存放旧测试文件：
- `test_migration_complete.py` - 迁移完成测试
- `test_stage*.py` - 分阶段测试文件
- `test_system_functionality.py` - 系统功能测试
- `diagnostic.py` - 诊断工具
- `test_output.txt` - 测试输出

## 📚 文档文件夹 `docs/`

存放所有项目文档和报告：
- `LangChain最新版本迁移完整报告.md`
- `LangChain迁移分析报告.md`
- `LangChain迁移深度分析报告.md`
- `FSenv_LangChain_测试报告.md`
- `migration_*.md` - 各种迁移记录
- `example.md` - 示例文档
- `future.md` - 未来计划

## 🎯 推荐使用方式

### 运行项目
```bash
# 激活环境
conda activate FSenv

# 运行测试
python test_langchain.py

# 运行主程序
python main.py
```

### 开发建议
1. **使用最新版本**: `langchain_agent.py` 和 `langchain_tools.py`
2. **参考文档**: 查看 `docs/` 文件夹中的迁移报告
3. **保持整洁**: 新的实验文件请放入 `archive/` 对应文件夹

## 📝 版本说明

当前项目使用 **LangChain 1.0.2**（最新稳定版），完全重构了 Agent 和工具系统：
- ✅ 使用最新的 `@tool` 装饰器
- ✅ 使用 `create_react_agent` API
- ✅ 使用 `AgentExecutor` 进行执行
- ✅ 完整的类型注解和错误处理
---
. 工具 (Tools) 增强建议工具名称增强/替换建议原因/目标tools.py 优化引入数据源轮换/回退机制（如你已尝试的那样，但需更健壮）。例如：Primary Source (yfinance) -> Secondary Source (Finnhub) -> Tertiary Source (自建API或公共数据源)。解决限速问题。 确保即使主要数据源失败，Agent 也能获取到关键的定量数据。目前限速导致报告缺失了关键的对比和风险数据。新增 get_financial_statementsget_financial_statements(ticker, period="annual", limit=3)：获取近三年的营收、净利润、EPS、自由现金流等。增强基本面分析。 现在的报告缺乏具体的财务数据（营收增长率、利润率），仅依赖公司简介不够深入。该工具能充实“FUNDAMENTAL ANALYSIS”部分。新增 get_technical_indicatorsget_technical_indicators(ticker, indicator="RSI")：获取 RSI、MACD、SMA (50/200日均线) 等技术指标。增强技术分析。 报告中的“TECHNICAL & SENTIMENT ANALYSIS”目前很薄弱，该工具能提供具体的支撑/阻力位和动量信息。增强 search 提示词引导 search 工具去寻找定量数据，如“Alphabet (GOOGL) 50日均线”或“2025年Q4 FOMC 会议纪要”。提高搜索效率。 避免搜索结果过于宏观（例如结果 1, 8, 9, 10 都是不相关的）

提示词区域	增强内容	目标
PHASE 1 (数据收集) 细化	新增数据缺失处理指导： "如果任何关键工具（如性能对比、历史回撤）因 API 限制而失败，请使用 search 工具尝试查找替代或大致信息，并在报告中明确说明数据的局限性。"	提高容错率。 确保报告的完整性，而不是因为一个工具失败而留下空白。
MANDATORY REPORT STRUCTURE 调整	在 FUNDAMENTAL ANALYSIS 下，要求 Agent 明确讨论估值指标 (Valuation Metrics)：如 P/E ratio, PEG ratio, EV/EBITDA 等。	增强基本面深度。 估值是投资决策的核心。即使没有专门的工具，Agent 也可以通过 search 来查找或基于现有数据（如市值）进行估算。
CRITICAL GUIDELINES 强调	将 "Quantitative/Valuation Data is Mandatory" 放在最显眼的位置。	再次强调定量分析的重要性。 强制 Agent 在写报告前必须尽力获取关键数字。

2. 提示词增强建议
pythonSYSTEM_PROMPT = """...

**关键增强点:**

1. 添加错误处理指令:
"如果某个工具失败,必须使用替代工具或明确说明数据缺失的影响"

2. 强制数据引用:
"报告中每个数值、百分比必须标注数据来源和时间戳"

3. 增加批判性思维:
"必须分析数据之间的矛盾之处,如市场极度恐惧但公司基本面强劲"

4. 添加定量分析要求:
"必须包含至少3个估值模型: DCF、可比公司、历史估值倍数"

5. 风险量化:
"每个风险必须用百分比或金额量化潜在影响"

**报告结构改进:**

## 量化估值分析 (新增章节)
- DCF模型: 基于现金流折现的内在价值
- 相对估值: P/E, P/B, EV/EBITDA与同行业对比
- 历史估值区间: 当前估值在历史百分位
- 隐含预期: 当前股价隐含的增长率

## 资本配置分析 (新增章节)  
- 分红政策和股票回购
- 资本支出和ROI
- 债务结构和利息覆盖率
- 自由现金流产生能力

## 催化剂时间线 (改进)
未来6个月关键日期:
- 2025-12-15: Q4财报
- 2026-01-20: CES展会新产品发布
- 2026-02-05: 监管判决预期
"""
3. 工具调用策略优化
现代金融Agent应该使用多Agent协作模式,由专门的Agent验证结果并执行复杂工作流程 V7 LabsFujitsu:
python# 建议实现智能工具选择器:

class ToolOrchestrator:
    def select_optimal_tool(self, data_needed, failed_tools=[]):
        """根据需求自动选择最佳数据源"""
        priority_map = {
            'price': ['alpha_vantage', 'yahoo', 'finnhub'],
            'financials': ['financial_modeling_prep', 'alpha_vantage', 'polygon'],
            'news': ['finnhub', 'newsapi', 'google_news']
        }
        # 返回未失败的最高优先级工具
        
    def parallel_fetch(self, tools_list):
        """并行调用多个工具,提高效率"""
        # 使用异步或多线程
4. 增加数据验证层
pythondef validate_data_consistency(data_dict):
    """
    验证数据一致性:
    - 市值 = 股价 × 流通股数
    - 财报日期是否匹配
    - 极端数值检测
    """
    inconsistencies = []
    
    # 交叉验证逻辑
    if abs(calculated_market_cap - reported_market_cap) > threshold:
        inconsistencies.append("市值数据不一致")
        
    return {
        'is_valid': len(inconsistencies) == 0,
        'issues': inconsistencies,
        'confidence_score': calculate_confidence()
    }
5. 报告生成改进
python# 在"Final Answer"阶段添加:

**数据质量声明:**
- 使用了X个数据源
- Y%的关键数据点已验证
- Z个数据点因API限制缺失

**分析局限性:**
明确说明哪些分析受限于数据可用性

**置信度评分:**
给出整体推荐的置信度: 高(80%+) / 中(60-80%) / 低(<60%)

🎯 优先改进路线图
阶段1: 立即修复 (1-2天)

添加速率限制重试机制和backoff策略
实现多数据源fallback逻辑
修复报告字数不足问题(添加更多细节)

阶段2: 核心增强 (1周)

添加财务报表分析工具
添加估值模型计算
实现数据验证层
增强提示词的量化分析要求

阶段3: 高级功能 (2-3周)

实现多Agent协作架构
添加技术分析和期权数据
实现并行工具调用
添加历史回测功能


📈 与业界最佳实践对比
领先的金融AI Agent如Auquan的成本降低80-90%,且生产力显著提升 Fujitsu。您的Agent具备基础框架,但需要:

数据整合 - 实时数据访问和云端FP&A软件是关键 Golimelight
人工监督 - 最佳实践是保持"人在回路"模式,AI处理初始工作,专家审核结果 V7 Labs
可解释性 - 在监管环境中,Agent必须是可解释的,不仅对内部利益相关者,也对监管机构、审计师和董事会 PwC


🌟 创新功能建议

情景模拟引擎

生成牛市/熊市/基准情景下的价格目标
Monte Carlo模拟


智能摘要

为不同受众生成不同版本(C-level高管 vs 分析师 vs 散户)


持续监控

报告生成后,持续监控关键指标和新闻
触发条件时发送更新


回测验证

自动回测过去的推荐准确性
学习改进
’---------
阶段一：即刻修复与核心增强 (优先级：极高)本阶段旨在解决当前运行中的主要痛点（API 限制）并立即提升报告的定量深度。1. 🛠️ 工具层面的核心优化 (Tool-Layer Optimization)核心改进点增强操作 (Action)目标/成果数据源轮换与容错💡 必须实现 ToolOrchestrator 逻辑。 在 tools.py 内部，为所有易受限的工具（价格、新闻、性能对比、回撤）实现多源回退机制（如：yfinance -> Finnhub -> Alpha Vantage/Polygon）。消除数据缺失风险。 确保 get_performance_comparison 和 analyze_historical_drawdowns 不再因限速失败。新增核心量化工具加入 get_financial_statements： 获取 P/E, 营收增长率, 净利润, FCF (自由现金流)。补齐基本面深度。 为报告中的“估值分析”和“基本面分析”提供具体数字。新增技术分析工具加入 get_technical_indicators： 获取 50/200 日均线 (SMA)、RSI、MACD。补齐技术分析。 为报告中的“技术与情绪分析”提供具体的买卖信号和支撑/阻力位。增强 search 的聚焦性调整 search 工具的底层逻辑，强制使用特定的查询格式，例如：GOOGL valuation multiples vs MSFT 或 GOOGL Q4 2025 earnings date。提高数据准确性。 将模糊搜索转化为精确的事实检索。2. 📝 提示词与报告结构优化 (Prompt & Structure Refinement)报告指令区增强内容 (Instruction)目标/成果PHASE 1 (数据收集)新增容错指令： “如果关键工具失败，Agent 必须使用 search 工具获取替代数据，并在报告中以引用形式（例如：【搜索结果，未经验证】）说明。”增强 Agent 容错和透明度。CRITICAL GUIDELINES最高优先级强调： 将 "Quantitative/Valuation Data is Mandatory (必须包含具体的 P/E, 增长率等)" 放在最显眼的位置。强制量化输出。 避免报告空泛。新增强制报告章节新增 ## 量化估值分析 章节。 强制讨论 P/E, PEG, DCF 估值结果和历史估值倍数。大幅提升报告专业度。改进风险分析风险量化： 在 ## RISK ASSESSMENT 中，要求“每个关键风险（如监管、衰退）必须尝试用百分比（如：潜在下行风险 15-20%）或具体的历史回撤数据来量化潜在影响。”提升风险分析的可操作性。阶段二：高级功能与健壮性 (优先级：中等)本阶段侧重于引入更复杂的分析能力，并构建数据验证和协作机制。1. 🧠 工作流与协作机制 (Workflow & Orchestration)高级功能机制设计 (Design)目标/成果数据验证层引入 validate_data_consistency 函数。 在数据收集后、报告生成前，检查关键数据的交叉一致性（如：股价 $\times$ 流通股数 $\approx$ 市值）。提高数据可信度。 避免基于错误数据进行分析。多 Agent 协作构思一个**“数据收集 Agent”和“CIO 报告 Agent”**。数据收集 Agent 负责并行调用和验证所有工具；CIO Agent 接收结构化、已验证的数据。提升效率和模块化。 报告 Agent 可以更专注于分析和写作。并行工具调用使用异步编程（如 Python 的 asyncio）实现 ToolOrchestrator.parallel_fetch()。显著减少 Agent 延迟。 提高用户体验。2. 💡 报告创新与透明度 (Innovation & Transparency)新增 ## 资本配置分析 章节： 强制 Agent 讨论分红、回购、资本支出 ROI 等，关注公司对股东资本的使用效率。增加透明度声明： 在报告末尾，强制添加 “数据质量声明”（使用了 X 个数据源，Y% 数据已验证）和 “分析局限性” 声明。## 催化剂时间线 细化： 从宏观的“即将到来的事件”细化为 未来 6 个月内的关键日期和具体事件（如财报日、FOMC 会议）。阶段三：未来愿景与情景分析 (优先级：长期)本阶段着眼于将 Agent 打造为具备前瞻性和模拟能力的投资助手。长期愿景核心功能 (Feature)目标/成果情景模拟引擎实现 simulate_scenarios(ticker, bull_assumptions, bear_assumptions) 工具。 基于 AI 假设驱动的 Monte Carlo 或敏感性分析。量化牛市/熊市目标价。 使 ## OUTLOOK & PRICE TARGETS 章节更具说服力。持续监控与触发Agent 具备记忆功能，报告生成后能持续追踪关键新闻和股价波动。从一次性报告转变为持续的投资顾问。回测与迭代建立内部反馈循环，让 Agent 自动回测历史推荐的准确性，并调整其“置信度”评分逻辑。实现 Agent 的自我学习和优化。