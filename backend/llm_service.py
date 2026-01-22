import logging
import litellm
from backend.llm_config import LLM_CONFIGS

logger = logging.getLogger(__name__)



def call_llm(provider: str, model: str, messages: list, **kwargs):
    """
    
    A flexible function to call any configured LLM provider.
    
    """
    
    logger.info(f"\n--- Calling Provider: {provider}, Model: {model} ---")

    config = LLM_CONFIGS.get(provider)
    if not config:
        logger.info(f"Error: Provider '{provider}' not found in LLM_CONFIGS.")
        return

    api_key = config.get("api_key")
    if not api_key:
        logger.info(f"Error: API key for '{provider}' not found. Please check your .env file for the correct environment variable.")
        return

    # LiteLLM can intelligently handle different providers.
    # For OpenAI-compatible endpoints, we just need to pass the api_base.
    try:
        response = litellm.completion(
            model=f"openai/{model}",
            messages=messages,
            api_key=api_key,
            api_base=config.get("api_base"), # Pass api_base if it exists
            **kwargs # Pass other arguments like temperature, max_tokens
        )
        
        if response and response.choices:
            content = response.choices[0].message.content
            logger.info("Model Response:")
            logger.info(content)
            return content
        else:
            logger.info("Error: Received an empty response from the API.")
            return None

    except Exception as e:
        logger.info(f"An error occurred during the call to {provider}: {e}")
        return None