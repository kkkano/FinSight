# -*- coding: utf-8 -*-
"""
Tools Bridge - 工具桥接模块
连接 ToolOrchestrator 和现有的 backend.tools
"""

import logging
import sys
import os
import importlib

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
    
    # 配置股价数据源
    orchestrator.sources['price'] = []
    def _cfg_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, default))
        except Exception:
            return default

    def _is_configured(source_name: str) -> bool:
        key_map = {
            'tiingo': 'TIINGO_API_KEY',
            'iex_cloud': 'IEX_CLOUD_API_KEY',
            'twelve_data': 'TWELVE_DATA_API_KEY',
            'alpha_vantage': 'ALPHA_VANTAGE_API_KEY',
            'finnhub': 'FINNHUB_API_KEY',
        }
        key_attr = key_map.get(source_name)
        if not key_attr:
            return True
        val = getattr(tools_module, key_attr, "") if tools_module else ""
        return bool(val)

    price_sources = [
        ('index_price', getattr(tools_module, '_fetch_index_price', None), _cfg_int('PRICE_PRIORITY_INDEX', 1), _cfg_int('PRICE_RATE_INDEX', 10), _cfg_int('PRICE_COOLDOWN_INDEX', 0)),
        ('alpha_vantage', getattr(tools_module, '_fetch_with_alpha_vantage', None), _cfg_int('PRICE_PRIORITY_ALPHA', 1), _cfg_int('PRICE_RATE_ALPHA', 5), _cfg_int('PRICE_COOLDOWN_ALPHA', 0)),
        ('finnhub', getattr(tools_module, '_fetch_with_finnhub', None), _cfg_int('PRICE_PRIORITY_FINNHUB', 2), _cfg_int('PRICE_RATE_FINNHUB', 60), _cfg_int('PRICE_COOLDOWN_FINNHUB', 0)),
        ('yfinance', getattr(tools_module, '_fetch_with_yfinance', None), _cfg_int('PRICE_PRIORITY_YFIN', 3), _cfg_int('PRICE_RATE_YFIN', 30), _cfg_int('PRICE_COOLDOWN_YFIN', 0)),
        ('twelve_data', getattr(tools_module, '_fetch_with_twelve_data_price', None), _cfg_int('PRICE_PRIORITY_TWELVEDATA', 4), _cfg_int('PRICE_RATE_TWELVEDATA', 30), _cfg_int('PRICE_COOLDOWN_TWELVEDATA', 0)),
        ('yahoo_scrape', getattr(tools_module, '_scrape_yahoo_finance', None), _cfg_int('PRICE_PRIORITY_YAHOO', 5), _cfg_int('PRICE_RATE_YAHOO', 10), _cfg_int('PRICE_COOLDOWN_YAHOO', 0)),
        ('search', getattr(tools_module, '_search_for_price', None), _cfg_int('PRICE_PRIORITY_SEARCH', 6), _cfg_int('PRICE_RATE_SEARCH', 30), _cfg_int('PRICE_COOLDOWN_SEARCH', 0)),
    ]
    for name, func, priority, rate_limit, cooldown in price_sources:
        if func:
            if not _is_configured(name):
                continue
            orchestrator.sources['price'].append(
                DataSource(name, func, priority, rate_limit, cooldown_seconds=cooldown)
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
