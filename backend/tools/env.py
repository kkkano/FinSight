import logging
import os
import finnhub
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip('"')
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip('"')
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "").strip('"')
IEX_CLOUD_API_KEY = os.getenv("IEX_CLOUD_API_KEY", "").strip('"')
TIINGO_API_KEY = os.getenv("TIINGO_API_KEY", "").strip('"')
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip('"')
MARKETSTACK_API_KEY = os.getenv("MARKETSTACK_API_KEY", "").strip('"')
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip('"')
EXA_API_KEY = os.getenv("EXA_API_KEY", "").strip('"')
OPENFIGI_API_KEY = os.getenv("OPENFIGI_API_KEY", "").strip('"')
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "").strip('"')
FRED_API_KEY = os.getenv("FRED_API_KEY", "").strip('"')

try:
    finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
except Exception as e:
    logger.info(f"Failed to initialize Finnhub client: {e}")
    finnhub_client = None
