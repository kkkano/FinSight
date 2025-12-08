# -*- coding: utf-8 -*-
"""
Tools Bridge - 工具桥接模块
连接 ToolOrchestrator 和现有的 tools.py
"""

import sys
import os
import importlib

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
        print("[Bridge] 成功从 backend.tools 导入")
        return tools
    except ImportError:
        try:
            # 尝试从根目录 tools 导入 (旧结构)
            import tools
            print("[Bridge] 成功从 tools 导入")
            return tools
        except ImportError as e:
            print(f"[Bridge] 警告: 无法导入 tools 模块: {e}")
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
        print("[Bridge] 工具模块未加载，跳过注册")
        return
    
    # 保存 tools 模块引用
    orchestrator.set_tools_module(tools_module)
    
    # 配置股价数据源
    orchestrator.sources['price'] = []
    price_sources = [
        ('index_price', getattr(tools_module, '_fetch_index_price', None), 1, 10),
        ('alpha_vantage', getattr(tools_module, '_fetch_with_alpha_vantage', None), 1, 5),
        ('finnhub', getattr(tools_module, '_fetch_with_finnhub', None), 2, 60),
        ('yfinance', getattr(tools_module, '_fetch_with_yfinance', None), 3, 30),
        ('twelve_data', getattr(tools_module, '_fetch_with_twelve_data_price', None), 4, 30),
        ('yahoo_scrape', getattr(tools_module, '_scrape_yahoo_finance', None), 5, 10),
        ('search', getattr(tools_module, '_search_for_price', None), 6, 30),
    ]
    for name, func, priority, rate_limit in price_sources:
        if func:
            orchestrator.sources['price'].append(
                DataSource(name, func, priority, rate_limit)
            )
    
    # 配置公司信息数据源
    orchestrator.sources['company_info'] = []
    # 注意：这里使用 lambda 是为了延迟绑定，但如果 tools_module 变了会有问题
    # 更好的方式是直接绑定函数
    get_info_func = getattr(tools_module, 'get_company_info', None)
    if get_info_func:
        orchestrator.sources['company_info'].append(
            DataSource('default', get_info_func, 1, 30)
        )
    
    print(f"[Bridge] 已注册 {len(orchestrator.sources.get('price', []))} 个价格数据源")


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
