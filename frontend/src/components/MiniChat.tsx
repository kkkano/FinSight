/**
 * Mini Chat 组件 - 右侧面板的快捷输入窗口
 *
 * 与主 Chat 共享同一份 messages 列表（统一上下文）。
 * 发送时通过 via: 'mini' 标记来源，通过 context 参数向后端传递
 * 临时上下文（如当前关注的 symbol 和选中的新闻），不会注入到消息内容中。
 */
import { useRef, useEffect, useState } from 'react';
import { Send, Loader2, X, Paperclip } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { apiClient, type ChatContext } from '../api/client';
import { useStore } from '../store/useStore';
import { useDashboardStore } from '../store/dashboardStore';

export const MiniChat: React.FC = () => {
  // 共享主 Chat 的 messages（统一上下文）
  const { messages, addMessage, updateMessage, currentTicker } = useStore();
  const { activeAsset, activeSelections, clearSelection } = useDashboardStore();
  const [input, setInput] = useState('');
  // 本地 loading 状态（不影响主 Chat 的全局 loading）
  const [isLoading, setIsLoading] = useState(false);
  // 用户是否关闭了 context pill
  const [contextEnabled, setContextEnabled] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 流式内容累积 ref（避免闭包问题）
  const accumulatedContentRef = useRef<string>('');
  const accumulatedThinkingRef = useRef<any[]>([]);

  // 当前 symbol（优先 dashboardStore，兜底 useStore）
  const currentSymbol = activeAsset?.symbol || currentTicker || null;

  // 是否展示 context pill
  const showContextPill = contextEnabled && !!currentSymbol;

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 当 symbol 变化时自动重新启用 context
  useEffect(() => {
    setContextEnabled(true);
  }, [currentSymbol]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    const userMsgId = uuidv4();
    const aiMsgId = uuidv4();

    // 添加用户消息（带 via: 'mini' 标记，内容不注入 symbol）
    addMessage({
      id: userMsgId,
      role: 'user',
      content: text,
      timestamp: Date.now(),
      via: 'mini',
    });

    // 添加 AI 加载占位消息
    addMessage({
      id: aiMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isLoading: true,
      via: 'mini',
    });

    setInput('');
    setIsLoading(true);

    // 重置累积 ref
    accumulatedContentRef.current = '';
    accumulatedThinkingRef.current = [];

    try {
      // 构建统一的历史记录（取 messages，排除 welcome 和 loading）
      const history = messages
        .filter(m => m.id !== 'welcome' && !m.isLoading)
        .slice(-12)
        .map(m => ({ role: m.role, content: m.content }));

      // 构建临时上下文（仅在 context pill 启用时传递）
      // 包括 active_symbol 和 selection（如果有选中的新闻/报告）
      const context: ChatContext = {};

      if (showContextPill && currentSymbol) {
        context.active_symbol = currentSymbol;
        context.view = 'dashboard';
      }

      if (activeSelections.length === 1) context.selection = activeSelections[0];
      if (activeSelections.length > 1) context.selections = activeSelections;

      // 如果有任何上下文，才传递
      const contextToSend = Object.keys(context).length > 0 ? context : undefined;

      // SSE 流式获取响应
      await apiClient.sendMessageStream(
        text,
        (token: string) => {
          accumulatedContentRef.current += token;
          updateMessage(aiMsgId, {
            content: accumulatedContentRef.current,
            isLoading: false,
          });
        },
        undefined, // onToolStart
        undefined, // onToolEnd
        (report, thinking) => {
          // onDone
          updateMessage(aiMsgId, {
            isLoading: false,
            report,
            thinking,
          });
        },
        (error: string) => {
          updateMessage(aiMsgId, {
            content: `Error: ${error}`,
            isLoading: false,
          });
        },
        (step) => {
          // onThinking
          accumulatedThinkingRef.current = [...accumulatedThinkingRef.current, step];
          updateMessage(aiMsgId, {
            thinking: accumulatedThinkingRef.current,
          });
        },
        history,
        undefined, // onRawEvent
        contextToSend,   // 临时上下文（symbol + selection）
      );
    } catch (error) {
      updateMessage(aiMsgId, {
        content: `发送失败: ${error}`,
        isLoading: false,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 显示最近的消息（从统一 messages 取最近 20 条）
  const recentMessages = messages.slice(-20);

  return (
    <div className="flex flex-col h-full">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto space-y-3 p-2">
        {recentMessages.length <= 1 ? (
          <div className="text-center text-fin-muted text-xs py-8">
            <p>👋 Hi! 有什么可以帮你的？</p>
            <p className="mt-2 text-[10px]">
              {currentSymbol
                ? `当前关注 ${currentSymbol}，可以直接问问题`
                : '在这里快速提问关于股票、市场的问题'}
            </p>
          </div>
        ) : (
          recentMessages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[85%] px-3 py-2 rounded-xl text-xs ${
                  msg.role === 'user'
                    ? 'bg-fin-primary text-white'
                    : 'bg-fin-bg border border-fin-border text-fin-text'
                }`}
              >
                {msg.isLoading ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 size={12} className="animate-spin" />
                    <span className="text-fin-muted">思考中...</span>
                  </span>
                ) : msg.role === 'user' ? (
                  // 用户消息：纯文本
                  <span className="whitespace-pre-wrap break-words">{msg.content}</span>
                ) : (
                  // AI 回复：Markdown 渲染
                  <div className="prose prose-sm prose-invert max-w-none text-fin-text prose-p:my-1 prose-headings:my-1.5 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-pre:my-1 prose-code:text-fin-primary prose-code:bg-fin-bg/50 prose-code:px-1 prose-code:rounded">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-fin-border p-2 space-y-1.5">
        {/* Context Pills - Symbol 和 Selection */}
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Symbol Context Pill */}
          {showContextPill && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-fin-primary/10 text-fin-primary text-[10px] font-medium">
              <span>📌 {currentSymbol}</span>
              <button
                onClick={() => setContextEnabled(false)}
                className="ml-0.5 hover:bg-fin-primary/20 rounded-full p-0.5 transition-colors"
                title="关闭上下文注入"
              >
                <X size={10} />
              </button>
            </span>
          )}

          {/* Selection Pill - 选中的新闻/报告 */}
          {activeSelections.length > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-500 text-[10px] font-medium max-w-[200px]">
              <Paperclip size={10} className="shrink-0" />
              <span className="truncate">
                {activeSelections[0].type === 'news' ? '📰' : '📊'}{' '}
                {activeSelections.length === 1
                  ? `${activeSelections[0].title.slice(0, 25)}${activeSelections[0].title.length > 25 ? '...' : ''}`
                  : `${activeSelections.length}条${activeSelections[0].type === 'news' ? '新闻' : '报告'}`}
              </span>
              <button
                onClick={clearSelection}
                className="ml-0.5 hover:bg-amber-500/20 rounded-full p-0.5 transition-colors shrink-0"
                title="取消引用"
              >
                <X size={10} />
              </button>
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={currentSymbol ? `问关于 ${currentSymbol} 的问题...` : '输入问题...'}
            disabled={isLoading}
            className="flex-1 px-3 py-2 text-xs bg-fin-bg border border-fin-border rounded-lg text-fin-text placeholder:text-fin-muted focus:outline-none focus:border-fin-primary disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            className="p-2 bg-fin-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            {isLoading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Send size={14} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
