import sys
import os
# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from backend.tools import get_stock_historical_data

def test_get_kline_data():
    ticker = "AAPL"
    print(f"Fetching K-line data for {ticker}...")
    result = get_stock_historical_data(ticker)

    assert "error" not in result, f"K-line tool returned error: {result.get('error')}"

    data = result.get("kline_data")
    assert data, "No 'kline_data' key in response"

    print(f"Successfully fetched {len(data)} data points.")

    if len(data) > 0:
        first_point = data[0]
        print("Sample data point:", first_point)
        # Verify structure
        required_keys = ["time", "open", "high", "low", "close"]
        for key in required_keys:
            assert key in first_point, f"Missing key '{key}' in data point"

if __name__ == "__main__":
    try:
        test_get_kline_data()
        print("✅ K-line data test passed!")
    except Exception as exc:
        print(f"❌ K-line data test failed! {exc}")


