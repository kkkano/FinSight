"""测试市场指数识别功能"""
from backend.conversation.router import ConversationRouter

router = ConversationRouter()

test_queries = [
    '纳斯达克涨跌如何',
    '道琼斯怎么样',
    '标普500今天表现',
    '纳指走势',
    '苹果价格',
    '纳斯达克指数走势',
    '道指今天涨了吗'
]

print("=" * 60)
print("测试市场指数识别")
print("=" * 60)

for query in test_queries:
    intent, metadata = router.classify_intent(query)
    print(f"\n查询: {query}")
    print(f"  意图: {intent.value}")
    print(f"  股票代码: {metadata.get('tickers', [])}")
    print(f"  名称: {metadata.get('company_names', [])}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)

