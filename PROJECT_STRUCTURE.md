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
