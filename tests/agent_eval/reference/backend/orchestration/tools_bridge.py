# -*- coding: utf-8 -*-
# ruff: noqa: E402
"""
Tools Bridge - 工具桥接模块
连接 ToolOrchestrator 和现有的 backend.tools
"""

import logging
import sys
import os

logger = logging.getLogger(__name__)


# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.orchestration.orchestrator import ToolOrchestrator, DataSource


def _import_tools_module():
    """尝试导入 tools 模块"""
    try:
        # 尝试从 backend.tools 导入 (新结构)
        from backend import tools
        logger.info("[Bridge] 成功从 backend.tools 导入")
        return tools
    except ImportError:
        try:
            # 尝试从根目录 tools 导入 (旧结构)
            import tools
            logger.info("[Bridge] 成功从 tools 导入")
            return tools
        except ImportError as e:
            logger.info(f"[Bridge] 警告: 无法导入 tools 模块: {e}")
            return None


def create_orchestrator_with_tools() -> ToolOrchestrator:
    """
    创建已配置好数据源的 ToolOrchestrator
    
    Returns:
        配置完成的 ToolOrchestrator 实例
    """
    orchestrator = ToolOrchestrator()
    register_all_financial_tools(orchestrator)
    return orchestrator


def register_all_financial_tools(orchestrator: ToolOrchestrator) -> None:
    """
    注册所有金融工具到 Orchestrator
    
    Args:
        orchestrator: ToolOrchestrator 实例
    """
    tools_module = _import_tools_module()
    
    if not tools_module:
        logger.info("[Bridge] 工具模块未加载，跳过注册")
        return
    
    # 保存 tools 模块引用
    orchestrator.set_tools_module(tools_module)
    
    # 价格供应商选择只在 MarketDataGateway 内发生，编排层不得再建立第二套 fallback。
    orchestrator.sources['price'] = []
    quote_func = getattr(tools_module, 'get_stock_price', None)
    if quote_func:
        orchestrator.sources['price'].append(DataSource('market_gateway', quote_func, 1, 120))
    
    # 配置公司信息数据源
    orchestrator.sources['company_info'] = []
    # 注意：这里使用 lambda 是为了延迟绑定，但如果 tools_module 变了会有问题
    # 更好的方式是直接绑定函数
    get_info_func = getattr(tools_module, 'get_company_info', None)
    if get_info_func:
        orchestrator.sources['company_info'].append(
            DataSource('default', get_info_func, 1, 30)
        )
    
    logger.info(f"[Bridge] 已注册 {len(orchestrator.sources.get('price', []))} 个价格数据源")


def get_stock_price_with_fallback(ticker: str, force_refresh: bool = False) -> str:
    """
    使用 ToolOrchestrator 获取股价（带多源回退）
    """
    orchestrator = get_global_orchestrator()
    result = orchestrator.fetch('price', ticker, force_refresh=force_refresh)
    
    if result.success:
        return result.data
    else:
        return f"Error: {result.error}"


def get_company_info_with_fallback(ticker: str) -> str:
    """使用 ToolOrchestrator 获取公司信息"""
    orchestrator = get_global_orchestrator()
    result = orchestrator.fetch('company_info', ticker)
    
    if result.success:
        return result.data
    else:
        return f"Error: {result.error}"


# 全局单例（用于复用缓存）
_global_orchestrator = None


def get_global_orchestrator() -> ToolOrchestrator:
    """获取全局 Orchestrator 实例（复用缓存）"""
    global _global_orchestrator
    
    if _global_orchestrator is None:
        _global_orchestrator = create_orchestrator_with_tools()
    
    return _global_orchestrator


def reset_global_orchestrator():
    """重置全局实例"""
    global _global_orchestrator
    _global_orchestrator = None
