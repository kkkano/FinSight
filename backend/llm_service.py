import litellm
from config import LLM_CONFIGS

def call_llm(provider: str, model: str, messages: list, **kwargs):
    """
    A flexible function to call any configured LLM provider.
    """
    print(f"\n--- Calling Provider: {provider}, Model: {model} ---")

    config = LLM_CONFIGS.get(provider)
    if not config:
        print(f"Error: Provider '{provider}' not found in LLM_CONFIGS.")
        return

    api_key = config.get("api_key")
    if not api_key:
        print(f"Error: API key for '{provider}' not found. Please check your .env file for the correct environment variable.")
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
            print("Model Response:")
            print(content)
            return content
        else:
            print("Error: Received an empty response from the API.")
            return None

    except Exception as e:
        print(f"An error occurred during the call to {provider}: {e}")
        return None
