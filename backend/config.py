import os
from dotenv import load_dotenv

# Load all environment variables from .env
load_dotenv()

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
    获取 LLM 配置
    
    Args:
        provider: LLM 提供商名称，默认为 "gemini_proxy"
        model: 模型名称，如果不提供则使用该提供商的第一个模型
        
    Returns:
        包含 api_key, api_base, model, temperature 的配置字典
    """
    config = LLM_CONFIGS.get(provider)
    
    if not config:
        # 如果指定的提供商不存在，使用 gemini_proxy 作为默认值
        print(f"[Config] 警告: 提供商 '{provider}' 不存在，使用默认 'gemini_proxy'")
        config = LLM_CONFIGS.get("gemini_proxy", {})
    
    # 获取模型名称（优先使用 gemini-2.5-flash 或 gemini-2.5-pro）
    if not model:
        models = config.get("models", [])
        # 优先选择 gemini-2.5-flash 或 gemini-2.5-pro
        preferred_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        for preferred in preferred_models:
            if preferred in models:
                model = preferred
                break
        # 如果没有找到优先模型，使用第一个
        if not model:
            model = models[0] if models else "gemini-2.5-flash"
    
    return {
        "api_key": config.get("api_key"),
        "api_base": config.get("api_base"),
        "model": model,
        "temperature": 0.3,
        "provider": provider,
    }