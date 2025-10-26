import requests
import re

def get_market_sentiment() -> str:
    """获取市场情绪指标 - CNN Fear & Greed Index"""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        
        # 模拟更真实的浏览器请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Referer': 'https://www.cnn.com/markets/fear-and-greed', # 告诉服务器你是从哪个页面过来的
            'Origin': 'https://www.cnn.com',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() 
        
        data = response.json()
        score = float(data['fear_and_greed']['score'])
        rating = data['fear_and_greed']['rating']
        return f"CNN Fear & Greed Index: {score:.1f} ({rating})"
    
    except requests.exceptions.HTTPError as http_err:
        print(f"CNN API failed with HTTP error: {http_err}. Trying fallback search...")
    except Exception as e:
        print(f"CNN API failed with other error: {e}. Trying fallback search...")

    # 你的回退逻辑可以保持不变
    return "Fear & Greed Index: Unable to fetch. Please check manually."
def main():
    result = get_market_sentiment()
    print(f"Result: {result}")
# 注意: 即便添加了更多头信息，这个方法也可能随时失效，因为服务器策略会变。
if __name__ == "__main__":
    main()