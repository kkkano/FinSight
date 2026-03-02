import logging
import os
import finnhub
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env
load_dotenv()

# Proxy configuration for bypassing GFW (used on China servers)
# Set YFINANCE_PROXY=socks5h://127.0.0.1:10808 in .env to enable
YFINANCE_PROXY = os.getenv("YFINANCE_PROXY", "").strip('"')
if YFINANCE_PROXY:
    # Set environment variables for requests/yfinance to use proxy
    os.environ["HTTP_PROXY"] = YFINANCE_PROXY
    os.environ["HTTPS_PROXY"] = YFINANCE_PROXY
    logger.info(f"Proxy configured for yfinance: {YFINANCE_PROXY}")

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
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip('"')  # Financial Modeling Prep

try:
    finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
except Exception as e:
    logger.info(f"Failed to initialize Finnhub client: {e}")
    finnhub_client = None
