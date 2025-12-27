# 投资建议查询问题修复

## 问题描述

当用户询问投资建议时（如"现在我投资了5000元。接下来你推荐我这几天怎么做呢"），系统错误地尝试获取股票价格，导致以下错误：

```
无法获取 ^GSPC 的价格信息: 所有数据源均失败: None
```

## 问题分析

### 1. 逻辑问题
- 用户问投资建议时，系统从上下文（`context.current_focus`）获取了之前的股票代码（如 `^GSPC`）
- 系统判断这不是价格查询、新闻查询或信息查询，所以走到了 `else` 分支
- `else` 分支默认尝试获取价格，但这不是用户想要的

### 2. API问题（次要）
- 虽然 `^GSPC` 可以通过 yfinance 成功获取数据（测试通过）
- 但通过 orchestrator 获取时可能因为数据源配置或验证问题而失败

## 解决方案

### 1. 添加投资建议查询识别
在 `ChatHandler` 中添加 `_is_advice_query` 方法，识别投资建议相关的关键词：

```python
def _is_advice_query(self, query: str) -> bool:
    """判断是否为投资建议查询"""
    keywords = ['推荐', '建议', '怎么做', '如何', '应该', '投资', '买入', '卖出', '持有', 'advice', 'recommend', 'should']
    return any(kw in query for kw in keywords)
```

### 2. 添加投资建议处理器
添加 `_handle_advice_query` 方法，直接使用 LLM 生成投资建议，不需要获取价格数据：

```python
def _handle_advice_query(self, ticker: str, query: str, context: Optional[Any] = None) -> Dict[str, Any]:
    """处理投资建议查询（不需要获取价格数据）"""
    # 使用 LLM 生成建议，不获取价格
```

### 3. 优化查询路由逻辑
更新 `handle` 方法，优先检查是否为投资建议查询：

```python
if self._is_advice_query(query_lower):
    # 投资建议查询：不需要获取价格，直接使用LLM回答
    return self._handle_advice_query(ticker, query, context)
elif self._is_price_query(query_lower):
    return self._handle_price_query(ticker, query, context)
# ...
```

## 修复效果

- ✅ 投资建议查询不再尝试获取价格
- ✅ 直接使用 LLM 生成专业的投资建议
- ✅ 避免了不必要的 API 调用
- ✅ 提高了响应速度和用户体验

## 测试建议

测试以下场景：
1. "现在我投资了5000元。接下来你推荐我这几天怎么做呢" → 应该直接给出投资建议
2. "标普500现在怎么样" → 应该获取价格并显示
3. "我应该买入还是卖出？" → 应该给出投资建议，不获取价格

