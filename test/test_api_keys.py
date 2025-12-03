"""测试API keys是否正常工作"""
import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta

# 加载环境变量
load_dotenv()

print("=" * 60)
print("测试 API Keys")
print("=" * 60)

# 测试 Alpha Vantage
print("\n1. 测试 Alpha Vantage API...")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
if ALPHA_VANTAGE_API_KEY:
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": "AAPL",
            "apikey": ALPHA_VANTAGE_API_KEY
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "Error Message" in data:
                print(f"   ❌ 错误: {data['Error Message']}")
            elif "Note" in data:
                print(f"   ⚠️  速率限制: {data['Note']}")
            else:
                print(f"   ✅ Alpha Vantage API 工作正常")
        else:
            print(f"   ❌ HTTP错误: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 异常: {e}")
else:
    print("   ⚠️  ALPHA_VANTAGE_API_KEY 未设置")

# 测试 Tiingo
print("\n2. 测试 Tiingo API...")
TIINGO_API_KEY = os.getenv("TIINGO_API_KEY")
if TIINGO_API_KEY:
    try:
        url = "https://api.tiingo.com/tiingo/daily/AAPL/prices"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {TIINGO_API_KEY}"
        }
        params = {
            "startDate": (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
            "endDate": datetime.now().strftime('%Y-%m-%d')
        }
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                print(f"   ✅ Tiingo API 工作正常，获取到 {len(data)} 条数据")
            else:
                print(f"   ⚠️  返回空数据")
        elif response.status_code == 401:
            print(f"   ❌ 认证失败，请检查API key")
        else:
            print(f"   ❌ HTTP错误: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ 异常: {e}")
else:
    print("   ⚠️  TIINGO_API_KEY 未设置")

# 测试 Marketstack
print("\n3. 测试 Marketstack API...")
MARKETSTACK_API_KEY = os.getenv("MARKETSTACK_API_KEY")
if MARKETSTACK_API_KEY:
    try:
        url = "http://api.marketstack.com/v1/eod"
        params = {
            "access_key": MARKETSTACK_API_KEY,
            "symbols": "AAPL",
            "limit": 5
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                print(f"   ❌ 错误: {data['error']}")
            elif "data" in data and len(data["data"]) > 0:
                print(f"   ✅ Marketstack API 工作正常，获取到 {len(data['data'])} 条数据")
            else:
                print(f"   ⚠️  返回空数据")
        elif response.status_code == 401:
            print(f"   ❌ 认证失败，请检查API key")
        else:
            print(f"   ❌ HTTP错误: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ 异常: {e}")
else:
    print("   ⚠️  MARKETSTACK_API_KEY 未设置")

# 测试 Massive.com (Polygon.io)
print("\n4. 测试 Massive.com (Polygon.io) API...")
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "NnE_U49S5fwLhgGjqpgBAKCVEZQaGpLE")
if MASSIVE_API_KEY:
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=5)
        url = f"https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "apikey": MASSIVE_API_KEY
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') in ('OK', 'DELAYED') and 'results' in data:
                print(f"   ✅ Massive.com API 工作正常，获取到 {len(data['results'])} 条数据")
            else:
                print(f"   ⚠️  返回状态: {data.get('status', 'unknown')}")
        else:
            print(f"   ❌ HTTP错误: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ 异常: {e}")
else:
    print("   ⚠️  MASSIVE_API_KEY 未设置")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)

