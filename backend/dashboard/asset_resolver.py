"""
资产类型解析器 - 根据 symbol 判断资产类型

通过符号特征和已知映射表来推断资产类型，支持：
- equity: 股票
- index: 指数
- etf: 交易所交易基金
- crypto: 加密货币
- portfolio: 投资组合（需显式指定）
"""
from backend.dashboard.schemas import ActiveAsset


# ── 常见指数映射 ──────────────────────────────────────────
_INDEX_SYMBOLS = {
    # 美股指数
    "^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX", "^FTSE", "^N225", "^HSI",
    "^STOXX50E", "^GDAXI", "^FCHI", "^BSESN", "^NSEI",
    # 美股指数别名
    "SPX", "DJI", "COMP", "RUT",
    # A股指数
    "000001.SS", "000300.SS", "399001.SZ", "399006.SZ",
    "000016.SS", "000905.SS", "000852.SS",
}

# ── 常见 ETF 映射 ──────────────────────────────────────────
_ETF_SYMBOLS = {
    # 大盘 ETF
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "IVV", "VT",
    # 国际市场 ETF
    "EEM", "IEMG", "VWO", "VEA", "EFA", "VNQ",
    # 债券 ETF
    "TLT", "IEF", "LQD", "HYG", "BND", "AGG",
    # 商品 ETF
    "GLD", "SLV", "USO", "UNG", "DBC",
    # 行业 ETF
    "XLF", "XLK", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB", "XLU", "XLRE",
    # 主题 ETF
    "ARKK", "ARKG", "ARKW", "ARKF", "ARKQ",
    # 杠杆 ETF
    "TQQQ", "SQQQ", "SPXL", "SPXS",
}

# ── 加密货币后缀 ──────────────────────────────────────────
_CRYPTO_SUFFIXES = ("-USD", "-USDT", "-BTC", "-ETH", "-BUSD")

# ── 显示名称映射（常用） ──────────────────────────────────
_DISPLAY_NAMES: dict[str, str] = {
    # 指数
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "NASDAQ Composite",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
    "^FTSE": "FTSE 100",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
    "000001.SS": "上证指数",
    "000300.SS": "沪深300",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    # ETF
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco QQQ Trust",
    "IWM": "iShares Russell 2000",
    "DIA": "SPDR Dow Jones",
    "VOO": "Vanguard S&P 500",
    "GLD": "SPDR Gold Shares",
    "TLT": "iShares 20+ Year Treasury",
    "ARKK": "ARK Innovation ETF",
    # 加密货币
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin",
    "XRP-USD": "Ripple",
    "ADA-USD": "Cardano",
    "DOGE-USD": "Dogecoin",
    # 知名股票
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "NVDA": "NVIDIA Corp.",
    "TSLA": "Tesla Inc.",
    "META": "Meta Platforms",
}


def resolve_asset(symbol: str) -> ActiveAsset:
    """
    解析 symbol 返回 ActiveAsset。

    优先级：
    1. 精确匹配指数集合
    2. 以 ^ 开头判定为指数
    3. 精确匹配 ETF 集合
    4. 加密货币后缀匹配
    5. 默认为 equity

    Args:
        symbol: 资产代码（如 AAPL, ^GSPC, SPY, BTC-USD）

    Returns:
        ActiveAsset: 包含 symbol, type, display_name 的资产对象

    Examples:
        >>> resolve_asset("AAPL").type
        "equity"
        >>> resolve_asset("^GSPC").type
        "index"
        >>> resolve_asset("SPY").type
        "etf"
        >>> resolve_asset("BTC-USD").type
        "crypto"
    """
    upper = symbol.upper().strip()

    # 1. 精确匹配指数 或 以 ^ 开头
    if upper in _INDEX_SYMBOLS or upper.startswith("^"):
        asset_type = "index"
    # 2. 精确匹配 ETF
    elif upper in _ETF_SYMBOLS:
        asset_type = "etf"
    # 3. 加密货币后缀
    elif any(upper.endswith(suffix) for suffix in _CRYPTO_SUFFIXES):
        asset_type = "crypto"
    # 4. 默认为股票
    else:
        asset_type = "equity"

    # 获取显示名称，优先使用映射表，否则使用 symbol 本身
    display_name = _DISPLAY_NAMES.get(upper, upper)

    return ActiveAsset(
        symbol=upper,
        type=asset_type,
        display_name=display_name,
    )


def is_valid_symbol(symbol: str) -> bool:
    """
    验证 symbol 格式是否有效。

    基础验证规则：
    - 非空
    - 长度 1-20
    - 仅包含字母、数字、^、-、.

    Args:
        symbol: 待验证的资产代码

    Returns:
        bool: 是否有效
    """
    if not symbol or not symbol.strip():
        return False

    s = symbol.strip()

    if len(s) > 20:
        return False

    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789^-.")
    return all(c in allowed_chars for c in s)
