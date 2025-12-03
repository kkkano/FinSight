"""
测试所有数据源是否能正常获取K线数据
"""
import sys
sys.path.insert(0, '.')

from backend.tools import get_stock_historical_data

def test_data_sources():
    """测试所有数据源"""
    test_tickers = ["AAPL", "TSLA", "MSFT"]
    
    print("=" * 60)
    print("测试 K 线数据获取 - 多数据源回退策略")
    print("=" * 60)
    
    for ticker in test_tickers:
        print(f"\n📊 测试股票: {ticker}")
        print("-" * 60)
        
        try:
            result = get_stock_historical_data(ticker, period="1y", interval="1d")
            
            if "error" in result:
                print(f"❌ 失败: {result['error']}")
            elif "kline_data" in result:
                data = result["kline_data"]
                print(f"✅ 成功获取 {len(data)} 条数据")
                if len(data) > 0:
                    print(f"   时间范围: {data[0]['time']} 至 {data[-1]['time']}")
                    print(f"   最新价格: ${data[-1]['close']:.2f}")
                    print(f"   数据来源: {result.get('source', 'unknown')}")
        except Exception as e:
            print(f"❌ 异常: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_data_sources()

