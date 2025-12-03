"""测试 Massive.com API"""
import requests
from datetime import datetime, timedelta

ticker = 'AAPL'
api_key = 'NnE_U49S5fwLhgGjqpgBAKCVEZQaGpLE'
end = datetime.now()
start = end - timedelta(days=30)

# 方法1: 日期作为查询参数
url1 = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day'
params1 = {
    'from': start.strftime('%Y-%m-%d'),
    'to': end.strftime('%Y-%m-%d'),
    'adjusted': 'true',
    'sort': 'asc',
    'apikey': api_key
}

# 方法2: 日期作为路径参数
url2 = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start.strftime("%Y-%m-%d")}/{end.strftime("%Y-%m-%d")}'
params2 = {
    'adjusted': 'true',
    'sort': 'asc',
    'apikey': api_key
}

print("测试方法1 (日期作为查询参数):")
r1 = requests.get(url1, params=params1, timeout=10)
print(f"Status: {r1.status_code}")
if r1.status_code == 200:
    data = r1.json()
    print(f"Status: {data.get('status')}, Results: {len(data.get('results', []))}")
else:
    print(f"Error: {r1.text[:200]}")

print("\n测试方法2 (日期作为路径参数):")
r2 = requests.get(url2, params=params2, timeout=10)
print(f"Status: {r2.status_code}")
if r2.status_code == 200:
    data = r2.json()
    print(f"Status: {data.get('status')}, Results: {len(data.get('results', []))}")
else:
    print(f"Error: {r2.text[:200]}")

