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
        "models": ["gemini-2.5-flash-preview-05-20","gemini-2.5pro","gemini-2.5-flash"]
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
