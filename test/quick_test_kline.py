"""快速测试K线数据获取"""
from backend.tools import get_stock_historical_data

result = get_stock_historical_data('AAPL', '1mo', '1d')
if 'kline_data' in result:
    print(f"✅ 成功获取 {len(result['kline_data'])} 条数据")
    print(f"   时间范围: {result['kline_data'][0]['time']} 至 {result['kline_data'][-1]['time']}")
else:
    print(f"❌ 失败: {result.get('error', 'unknown')}")

