"""Load user config from user_config.json (hot reload on each call)"""

import logging
import os
import json
from dotenv import load_dotenv

logger = logging.getLogger(__name__)



# Load all environment variables from .env
load_dotenv()

# Project root for user_config.json
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_CONFIG_PATH = os.path.join(PROJECT_ROOT, "user_config.json")

def _load_user_config() -> dict:
    
    if os.path.exists(USER_CONFIG_PATH):
        try:
            with open(USER_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.info(f"[Config] Failed to load user_config.json: {e}")
    return {}

def _normalize_api_base(api_base: str) -> str:
    """
    Normalize API base URL - remove trailing /chat/completions if present.
    LangChain ChatOpenAI automatically appends /chat/completions to the base URL.
    """
    if not api_base:
        return api_base
    # Remove trailing slash
    api_base = api_base.rstrip('/')
    # Remove /chat/completions suffix if present (LangChain will add it)
    suffixes_to_remove = ['/chat/completions', '/v1/chat/completions']
    for suffix in suffixes_to_remove:
        if api_base.endswith(suffix):
            api_base = api_base[:-len(suffix)]
            break
    # Ensure /v1 suffix for OpenAI-compatible APIs
    if not api_base.endswith('/v1'):
        api_base = api_base + '/v1'
    return api_base

# ============================================
# LangSmith 可观测性配置
# ============================================
LANGSMITH_CONFIG = {
    "api_key": os.getenv("LANGSMITH_API_KEY", ""),
    "project": os.getenv("LANGSMITH_PROJECT", "FinSight"),
    "endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    "enabled": os.getenv("ENABLE_LANGSMITH", "false").lower() in ("true", "1", "yes"),
}

# ============================================
# LLM 提供商配置
# ============================================
# Centralized Configuration Hub (LLM_CONFIGS)
# Reads sensitive information from environment variables
LLM_CONFIGS = {
    "gemini_proxy": {
        "api_key": os.getenv("GEMINI_PROXY_API_KEY"),
        "api_base": os.getenv("GEMINI_PROXY_API_BASE"),
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-preview-05-20"]  # 优先使用稳定版本
    },
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]
    },
    "anyscale": {
        "api_key": os.getenv("ANYSCALE_API_KEY"),
        "api_base": os.getenv("ANYSCALE_API_BASE"),
        "models": ["meta-llama/Llama-3-8b-chat-hf", "meta-llama/Llama-3-70b-chat-hf"]
    },
    "anthropic": {
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "models": ["claude-3-sonnet-20240229", "claude-3-opus-20240229"]
    }
    # You can easily add more providers here
}


# ============================================
# LLM 配置获取函数
# ============================================

def get_llm_config(provider: str = "gemini_proxy", model: str = None) -> dict:
    """
    获取 LLM 配置（优先从 user_config.json 热加载）

    Args:
        provider: LLM 提供商名称，默认为 "gemini_proxy"
        model: 模型名称，如果不提供则使用该提供商的第一个模型

    Returns:
        包含 api_key, api_base, model, temperature 的配置字典
    """
    # 1. 优先从 user_config.json 热加载
    user_config = _load_user_config()
    if user_config.get("llm_api_key") and user_config.get("llm_api_base"):
        user_provider = user_config.get("llm_provider") or "custom"
        user_model = user_config.get("llm_model") or model or "gpt-4o"
        # 规范化 API base URL，避免 LangChain 重复拼接 /chat/completions
        normalized_base = _normalize_api_base(user_config["llm_api_base"])
        logger.info(f"[Config] Using user_config.json: provider={user_provider}, model={user_model}, api_base={normalized_base}")
        return {
            "api_key": user_config["llm_api_key"],
            "api_base": normalized_base,
            "model": user_model,
            "temperature": 0.3,
            "provider": user_provider,
        }

    # 2. 回退到环境变量配置
    config = LLM_CONFIGS.get(provider)

    if not config:
        logger.info(f"[Config] 警告: 提供商 '{provider}' 不存在，使用默认 'gemini_proxy'")
        config = LLM_CONFIGS.get("gemini_proxy", {})

    if not model:
        models = config.get("models", [])
        preferred_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        for preferred in preferred_models:
            if preferred in models:
                model = preferred
                break
        if not model:
            model = models[0] if models else "gemini-2.5-flash"

    return {
        "api_key": config.get("api_key"),
        "api_base": config.get("api_base"),
        "model": model,
        "temperature": 0.3,
        "provider": provider,
    }


def create_llm(provider: str = "gemini_proxy", model: str = None, temperature: float = 0.3, max_tokens: int = 65536, request_timeout: int = 600):
    """
    统一的 LLM 工厂函数（提取自 langchain_agent.py 和 conversation/agent.py）

    历史背景：
    - 之前 langchain_agent.py 和 conversation/agent.py 都有各自的 LLM 初始化代码
    - 为了避免代码重复，提取到这个统一的工厂函数

    Args:
        provider: LLM 提供商名称，默认为 "gemini_proxy"
        model: 模型名称，如果不提供则从配置中获取
        temperature: 温度参数，默认 0.3
        max_tokens: 最大 token 数，默认 4000
        request_timeout: 请求超时时间（秒），默认 600（10分钟，支持长报告生成）

    Returns:
        ChatOpenAI 实例
    """
    from langchain_openai import ChatOpenAI

    # 获取配置
    cfg = get_llm_config(provider=provider, model=model)
    api_key = cfg.get("api_key")
    api_base = cfg.get("api_base")
    model_name = cfg.get("model")

    if not api_key:
        raise ValueError(f"API key not found for provider '{provider}'")

    logger.info(f"[LLM Factory] Creating LLM: model={model_name}, api_base={api_base}, timeout={request_timeout}s")

    return ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=api_base,
        temperature=temperature,
        max_tokens=max_tokens,
        request_timeout=request_timeout,
    )