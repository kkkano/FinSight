# Selection Context / Context Attachments 功能实现

> 日期: 2026-02-01 | 版本: v0.7.0

---

## 功能概述

实现"上下文附件"机制，让 MiniChat 和 主 Chat 能够明确知道用户正在引用 Dashboard 中的哪条新闻或报告，彻底解决"都不知道我说哪个新闻"的问题。

### 核心设计

| 概念 | 说明 |
|-----|------|
| **Selection Context** (强约束) | 用户显式选中的对象（新闻/报告），通过"问这条"按钮触发 |
| **Active Symbol** (弱约束) | 当前 Dashboard 正在查看的股票代码 |
| **Context Attachments** | 每次请求附带的临时上下文，不写入对话历史 |

---

## 实现清单

### 前端 (Frontend)

| 文件 | 修改 | 说明 |
|------|------|------|
| `types/dashboard.ts` | 新增 | `SelectionItem` 接口 |
| `store/dashboardStore.ts` | 修改 | `activeSelection` 状态 + actions |
| `utils/hash.ts` | 新增 | DJB2 哈希函数生成新闻 ID |
| `components/dashboard/NewsFeed.tsx` | 修改 | "问这条"按钮 + 选中高亮 |
| `components/MiniChat.tsx` | 修改 | Selection Pill 显示 + context 传递 |
| `components/ChatInput.tsx` | 修改 | Selection Pill 显示 + context 传递 |
| `api/client.ts` | 修改 | `ChatContext` 类型扩展 |

### 后端 (Backend)

| 文件 | 修改 | 说明 |
|------|------|------|
| `api/schemas.py` | 修改 | `SelectionContext` Pydantic 模型 |
| `api/main.py` | 修改 | 处理 selection 组装临时 system prompt |

---

## 数据流

```
NewsFeed "问这条" → dashboardStore.activeSelection
                            ↓
Selection Pill (MiniChat / ChatInput) ← 读取显示
                            ↓
用户发送消息 → context.selection → API /chat/supervisor/stream
                                        ↓
              后端组装 [System Context] → 注入对话上下文 → AI 理解用户引用
```

---

## 类型定义

### SelectionItem (前端)

```typescript
export interface SelectionItem {
  type: 'news' | 'report';
  id: string;           // hash(title + source + ts)
  title: string;
  url?: string;
  source?: string;
  ts?: string;
  snippet?: string;     // 摘要/前100字
}
```

### SelectionContext (后端)

```python
class SelectionContext(BaseModel):
    """选中对象的上下文"""
    type: str = Field(..., description="对象类型: news/report")
    id: str = Field(..., description="对象ID（hash）")
    title: str = Field(..., description="标题")
    url: Optional[str] = None
    source: Optional[str] = None
    ts: Optional[str] = None
    snippet: Optional[str] = None
```

---

## 用户交互

1. **选择新闻**: 在 Dashboard NewsFeed 点击"问这条"按钮
2. **视觉反馈**: 新闻卡片高亮 + Selection Pill 显示在输入框上方
3. **发送消息**: 输入问题（如"分析一下这条新闻"）并发送
4. **AI 理解**: 后端接收到 selection context，AI 明确知道引用的是哪条新闻
5. **清除引用**: 点击 Selection Pill 的 X 按钮

---

## 测试验证

- [x] TypeScript 编译零错误
- [x] Python schemas 导入验证通过
- [x] SelectionContext 7 字段正确
- [x] ChatContext 包含 selection 字段
- [x] 主 Chat 和 MiniChat 都能显示 Selection Pill
- [x] 主 Chat 和 MiniChat 都能传递 context.selection

---

## 关键代码位置

- **Selection Pill UI**: `ChatInput.tsx:381-399`, `MiniChat.tsx` Selection Pill section
- **Context 构建**: `ChatInput.tsx:338-349`, `MiniChat.tsx` context building
- **后端处理**: `main.py:637-656` (selection context processing)
- **Store 状态**: `dashboardStore.ts` activeSelection/setActiveSelection/clearSelection
