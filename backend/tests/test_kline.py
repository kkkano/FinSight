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
    
    if "error" in result:
        print(f"Error: {result['error']}")
        return False
        
    data = result.get("kline_data")
    if not data:
        print("Error: No 'kline_data' key in response")
        return False
        
    print(f"Successfully fetched {len(data)} data points.")
    
    if len(data) > 0:
        first_point = data[0]
        print("Sample data point:", first_point)
        # Verify structure
        required_keys = ["time", "open", "high", "low", "close"]
        for key in required_keys:
            if key not in first_point:
                print(f"Error: Missing key '{key}' in data point")
                return False
                
    return True

if __name__ == "__main__":
    if test_get_kline_data():
        print("✅ K-line data test passed!")
    else:
        print("❌ K-line data test failed!")


