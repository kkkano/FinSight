import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useStore } from '../store/useStore';
import type { RawSSEEvent, RawEventType } from '../types';
import {
  Terminal,
  ChevronDown,
  ChevronUp,
  Trash2,
  Search,
  X,
  Copy,
  Check,
  Zap,
  Download,
  Pause,
  Play,
  Eye,
  EyeOff,
  Maximize2,
  Minimize2,
} from 'lucide-react';

// 事件类型颜色配置
const EVENT_TYPE_CONFIG: Record<string, { color: string; bg: string; label: string; icon: string }> = {
  token:            { color: 'text-fin-muted',   bg: 'bg-fin-muted/10',  label: 'TKN',  icon: '▸' },
  thinking:         { color: 'text-cyan-400',   bg: 'bg-cyan-500/10',   label: 'THINK', icon: '◈' },
  tool_start:       { color: 'text-amber-400',  bg: 'bg-amber-500/10',  label: 'TOOL▶', icon: '⚙' },
  tool_end:         { color: 'text-amber-300',  bg: 'bg-amber-500/10',  label: 'TOOL■', icon: '✓' },
  tool_call:        { color: 'text-orange-400', bg: 'bg-orange-500/10', label: 'CALL',  icon: '⚡' },
  llm_call:         { color: 'text-purple-400', bg: 'bg-purple-500/10', label: 'LLM',   icon: '🧠' },
  // 新增: TraceEmitter 事件类型
  llm_start:        { color: 'text-purple-400', bg: 'bg-purple-500/10', label: 'LLM▶',  icon: '🧠' },
  llm_end:          { color: 'text-purple-300', bg: 'bg-purple-500/10', label: 'LLM■',  icon: '🧠' },
  cache_hit:        { color: 'text-emerald-400',bg: 'bg-emerald-500/10',label: 'CACHE✓',icon: '📦' },
  cache_miss:       { color: 'text-yellow-400', bg: 'bg-yellow-500/10', label: 'CACHE✗',icon: '📦' },
  cache_set:        { color: 'text-emerald-300',bg: 'bg-emerald-500/10',label: 'CACHE+',icon: '📦' },
  data_source:      { color: 'text-sky-400',    bg: 'bg-sky-500/10',    label: 'DATA',  icon: '📊' },
  api_call:         { color: 'text-pink-400',   bg: 'bg-pink-500/10',   label: 'API',   icon: '🌐' },
  agent_step:       { color: 'text-teal-400',   bg: 'bg-teal-500/10',   label: 'STEP',  icon: '◈' },
  system:           { color: 'text-slate-400',  bg: 'bg-slate-500/10',  label: 'SYS',   icon: '⚙' },
  // 原有事件类型
  done:             { color: 'text-green-400',  bg: 'bg-green-500/10',  label: 'DONE',  icon: '✅' },
  error:            { color: 'text-red-400',    bg: 'bg-red-500/10',    label: 'ERR',   icon: '✗' },
  supervisor_start: { color: 'text-blue-400',   bg: 'bg-blue-500/10',   label: 'SUP▶',  icon: '▶' },
  agent_start:      { color: 'text-teal-400',   bg: 'bg-teal-500/10',   label: 'AGT▶',  icon: '▶' },
  agent_done:       { color: 'text-teal-300',   bg: 'bg-teal-500/10',   label: 'AGT■',  icon: '■' },
  agent_error:      { color: 'text-red-400',    bg: 'bg-red-500/10',    label: 'AGT✗',  icon: '✗' },
  forum_start:      { color: 'text-indigo-400', bg: 'bg-indigo-500/10', label: 'FRM▶',  icon: '▶' },
  forum_done:       { color: 'text-indigo-300', bg: 'bg-indigo-500/10', label: 'FRM■',  icon: '■' },
  unknown:          { color: 'text-fin-muted',  bg: 'bg-fin-muted/10',  label: 'UNK',   icon: '?' },
};

// 格式化时间戳 - 精确到毫秒
const formatTs = (ts: string): string => {
  try {
    const d = new Date(ts);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    const ms = String(d.getMilliseconds()).padStart(3, '0');
    return `${h}:${m}:${s}.${ms}`;
  } catch {
    return ts;
  }
};

// 格式化文件大小
const formatSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
};

// 获取事件摘要
const getEventSummary = (event: RawSSEEvent): string => {
  const data = event.parsedData;
  switch (event.eventType) {
    case 'token':
      return `"${(data.content || '').slice(0, 80)}${(data.content || '').length > 80 ? '...' : ''}"`;
    case 'thinking':
      return `[${data.stage || '?'}] ${data.message || ''}`.slice(0, 120);
    case 'tool_start':
      return `→ ${data.name || 'unknown_tool'}`;
    case 'tool_end':
      return `← tool execution complete`;
    case 'tool_call':
      return `${data.name || '?'}(${JSON.stringify(data.input || {}).slice(0, 80)})`;
    case 'llm_call':
      return `model=${data.model || '?'} tokens=${data.tokens || '?'}`;
    // 新增: TraceEmitter 事件类型摘要
    case 'llm_start':
      return `🧠 LLM 调用开始${data.model ? ` (${data.model})` : ''}`;
    case 'llm_end':
      const llmStatus = data.success ? '✓' : '✗';
      const llmDuration = data.duration_ms ? ` [${data.duration_ms}ms]` : '';
      return `🧠 LLM ${llmStatus}${llmDuration}${data.error ? ` - ${data.error}` : ''}`;
    case 'cache_hit':
      return `📦 缓存命中: ${data.key || '?'}`;
    case 'cache_miss':
      return `📦 缓存未命中: ${data.key || '?'}`;
    case 'cache_set':
      return `📦 缓存写入: ${data.key || '?'}${data.ttl ? ` (TTL: ${data.ttl}s)` : ''}`;
    case 'data_source':
      const dsStatus = data.success ? '✓' : '✗';
      const dsFallback = data.fallback ? ' [回退]' : '';
      const dsDuration = data.duration_ms ? ` [${data.duration_ms}ms]` : '';
      return `📊 ${data.source || '?'}: ${data.query_type || '?'}${data.ticker ? ` (${data.ticker})` : ''} ${dsStatus}${dsFallback}${dsDuration}`;
    case 'api_call':
      const apiStatus = data.status ? ` → ${data.status}` : '';
      const apiDuration = data.duration_ms ? ` [${data.duration_ms}ms]` : '';
      return `🌐 ${data.method || 'GET'} ${data.endpoint || '?'}${apiStatus}${apiDuration}`;
    case 'agent_step':
      return `◈ ${data.agent || '?'}: ${data.step || '?'}`;
    case 'system':
      return data.message || 'System event';
    // 原有事件类型
    case 'done':
      return `report=${!!data.report} thinking_steps=${(data.thinking || []).length}`;
    case 'error':
      return data.message || 'Unknown error';
    case 'supervisor_start':
      return `Supervisor started → agents: ${JSON.stringify(data.agents || [])}`;
    case 'agent_start':
      return `${data.agent || '?'} Agent started${data.query ? ` - ${data.query.slice(0, 50)}...` : ''}`;
    case 'agent_done':
      const agentDuration = data.duration_ms ? ` [${data.duration_ms}ms]` : '';
      return `${data.agent || '?'} Agent completed${agentDuration}`;
    case 'agent_error':
      return `${data.agent || '?'} Agent error: ${data.message || ''}`;
    case 'forum_start':
      return 'Forum synthesis started';
    case 'forum_done':
      return 'Forum synthesis completed';
    default:
      // 尝试使用 message 字段
      if (data.message) return data.message.slice(0, 120);
      return JSON.stringify(data).slice(0, 100);
  }
};

// JSON 语法高亮
const SyntaxHighlight: React.FC<{ json: string }> = ({ json }) => {
  const highlighted = json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"([^"]+)"(?=\s*:)/g, '<span class="text-purple-300">"$1"</span>')       // keys
    .replace(/:\s*"([^"]*)"/g, ': <span class="text-green-300">"$1"</span>')           // string values
    .replace(/:\s*(\d+\.?\d*)/g, ': <span class="text-amber-300">$1</span>')           // numbers
    .replace(/:\s*(true|false)/g, ': <span class="text-blue-300">$1</span>')            // booleans
    .replace(/:\s*(null)/g, ': <span class="text-fin-muted">$1</span>');                 // null

  return (
    <pre
      className="text-[11px] leading-relaxed whitespace-pre-wrap break-all font-mono"
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  );
};

// 可折叠 JSON 查看器
const JsonBlock: React.FC<{ data: any; label?: string; defaultExpanded?: boolean }> = ({
  data,
  label,
  defaultExpanded = false,
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);
  const jsonStr = JSON.stringify(data, null, 2);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(jsonStr);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="border border-fin-border rounded-md overflow-hidden my-1">
      <div
        className="flex items-center justify-between px-2 py-1 bg-fin-bg cursor-pointer hover:bg-fin-hover"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 text-[10px]">
          <span className="text-fin-muted">{expanded ? '▼' : '▶'}</span>
          {label && <span className="text-fin-text-secondary font-medium">{label}</span>}
          {!expanded && (
            <span className="text-fin-muted truncate max-w-xs">
              {jsonStr.slice(0, 60)}{jsonStr.length > 60 ? '...' : ''}
            </span>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); handleCopy(); }}
          className="p-0.5 text-fin-muted hover:text-fin-text"
          title="Copy JSON"
        >
          {copied ? <Check size={10} className="text-fin-success" /> : <Copy size={10} />}
        </button>
      </div>
      {expanded && (
        <div className="p-2 bg-fin-panel max-h-[300px] overflow-auto scrollbar-thin">
          <SyntaxHighlight json={jsonStr} />
        </div>
      )}
    </div>
  );
};

// 单个事件行
const EventRow: React.FC<{
  event: RawSSEEvent;
  isSelected: boolean;
  onClick: () => void;
  showTokens: boolean;
  index: number;
}> = ({ event, isSelected, onClick, showTokens, index }) => {
  const config = EVENT_TYPE_CONFIG[event.eventType] || EVENT_TYPE_CONFIG.unknown;

  // token 事件默认隐藏
  if (event.eventType === 'token' && !showTokens) return null;

  return (
    <div
      onClick={onClick}
      className={`
        flex items-center gap-0 px-2 py-[3px] cursor-pointer border-b border-fin-border/30
        font-mono text-[11px] leading-tight transition-colors
        ${isSelected
          ? 'bg-fin-primary/10 border-l-2 border-l-fin-primary'
          : 'hover:bg-fin-hover border-l-2 border-l-transparent'
        }
      `}
    >
      {/* 序号 */}
      <span className="w-8 shrink-0 text-[10px] text-fin-muted text-right pr-2">{index}</span>

      {/* 时间戳 */}
      <span className="w-[78px] shrink-0 text-[10px] text-fin-muted font-mono">
        {formatTs(event.timestamp)}
      </span>

      {/* 事件类型标签 */}
      <span className={`w-[50px] shrink-0 text-[10px] font-bold ${config.color}`}>
        <span className={`inline-flex items-center gap-0.5 px-1 py-[1px] rounded ${config.bg}`}>
          {config.icon} {config.label}
        </span>
      </span>

      {/* 摘要 */}
      <span className="flex-1 truncate text-fin-text pl-2">
        {getEventSummary(event)}
      </span>

      {/* 大小 */}
      <span className="w-12 shrink-0 text-right text-[10px] text-fin-muted">
        {formatSize(event.size)}
      </span>
    </div>
  );
};

// 事件详情面板
const EventDetail: React.FC<{ event: RawSSEEvent; onClose: () => void }> = ({ event, onClose }) => {
  const [activeTab, setActiveTab] = useState<'parsed' | 'raw' | 'headers'>('parsed');
  const [copied, setCopied] = useState(false);
  const config = EVENT_TYPE_CONFIG[event.eventType] || EVENT_TYPE_CONFIG.unknown;

  const handleCopyAll = async () => {
    await navigator.clipboard.writeText(event.rawData);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex flex-col h-full bg-fin-card border-t border-fin-border">
      {/* 详情头部 */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-fin-bg border-b border-fin-border">
        <div className="flex items-center gap-3">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${config.bg} ${config.color}`}>
            {config.icon} {event.eventType}
          </span>
          <span className="text-[10px] text-fin-muted">{formatTs(event.timestamp)}</span>
          <span className="text-[10px] text-fin-muted">{formatSize(event.size)}</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopyAll}
            className="p-1 text-fin-muted hover:text-fin-text rounded"
            title="Copy raw JSON"
          >
            {copied ? <Check size={12} className="text-fin-success" /> : <Copy size={12} />}
          </button>
          <button onClick={onClose} className="p-1 text-fin-muted hover:text-fin-text rounded">
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex items-center gap-0 px-2 bg-fin-panel border-b border-fin-border">
        {(['parsed', 'raw', 'headers'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1.5 text-[11px] font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-fin-primary text-fin-primary'
                : 'border-transparent text-fin-muted hover:text-fin-text'
            }`}
          >
            {tab === 'parsed' ? 'Parsed' : tab === 'raw' ? 'Raw' : 'Meta'}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <div className="flex-1 overflow-auto p-2 scrollbar-thin">
        {activeTab === 'parsed' && (
          <div className="space-y-1">
            {/* 事件级别的字段逐个展示 */}
            {Object.entries(event.parsedData).map(([key, value]) => (
              <div key={key}>
                {typeof value === 'object' && value !== null ? (
                  <JsonBlock data={value} label={key} />
                ) : (
                  <div className="flex items-start gap-2 px-2 py-0.5 text-[11px] font-mono">
                    <span className="text-fin-primary shrink-0">{key}:</span>
                    <span className={
                      typeof value === 'string'
                        ? 'text-fin-success'
                        : typeof value === 'number'
                          ? 'text-amber-400'
                          : typeof value === 'boolean'
                            ? 'text-blue-400'
                            : 'text-fin-muted'
                    }>
                      {typeof value === 'string' ? `"${value}"` : String(value)}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {activeTab === 'raw' && (
          <div className="bg-fin-panel rounded p-2 border border-fin-border">
            <SyntaxHighlight json={JSON.stringify(event.parsedData, null, 2)} />
          </div>
        )}

        {activeTab === 'headers' && (
          <div className="space-y-2 text-[11px] font-mono">
            <div className="grid grid-cols-[100px_1fr] gap-1 px-2">
              <span className="text-fin-muted">Event ID:</span>
              <span className="text-fin-text">{event.id}</span>

              <span className="text-fin-muted">Timestamp:</span>
              <span className="text-fin-text">{event.timestamp}</span>

              <span className="text-fin-muted">Event Type:</span>
              <span className={config.color}>{event.eventType}</span>

              <span className="text-fin-muted">Payload Size:</span>
              <span className="text-fin-text">{event.size} bytes ({formatSize(event.size)})</span>

              {event.sessionId && (
                <>
                  <span className="text-fin-muted">Session ID:</span>
                  <span className="text-fin-text">{event.sessionId}</span>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};


// 主控制台组件
export const AgentLogPanel: React.FC = () => {
  const { rawEvents, clearRawEvents, isConsoleOpen, setConsoleOpen, agentStatuses } = useStore();

  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [showTokens, setShowTokens] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [typeFilter, setTypeFilter] = useState<Set<RawEventType>>(new Set());
  const [isPaused, setIsPaused] = useState(false);
  const [pausedEvents, setPausedEvents] = useState<RawSSEEvent[]>([]);

  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // 获取当前运行的 Agent 数量
  const runningAgents = Object.values(agentStatuses).filter(s => s.status === 'running').length;

  // 暂停时冻结事件列表
  const displayEvents = isPaused ? pausedEvents : rawEvents;

  // 应用过滤器
  const filteredEvents = useMemo(() => {
    let events = displayEvents;

    // 类型过滤
    if (typeFilter.size > 0) {
      events = events.filter(e => typeFilter.has(e.eventType));
    }

    // 搜索过滤
    if (searchText.trim()) {
      const lower = searchText.toLowerCase();
      events = events.filter(e =>
        e.rawData.toLowerCase().includes(lower) ||
        e.eventType.toLowerCase().includes(lower) ||
        getEventSummary(e).toLowerCase().includes(lower)
      );
    }

    // token 过滤
    if (!showTokens) {
      events = events.filter(e => e.eventType !== 'token');
    }

    return events;
  }, [displayEvents, typeFilter, searchText, showTokens]);

  // 统计信息
  const stats = useMemo(() => {
    const totalBytes = rawEvents.reduce((sum, e) => sum + e.size, 0);
    const typeCounts: Record<string, number> = {};
    rawEvents.forEach(e => {
      typeCounts[e.eventType] = (typeCounts[e.eventType] || 0) + 1;
    });
    return { total: rawEvents.length, totalBytes, typeCounts, filtered: filteredEvents.length };
  }, [rawEvents, filteredEvents]);

  // 选中的事件
  const selectedEvent = useMemo(
    () => filteredEvents.find(e => e.id === selectedEventId) || null,
    [filteredEvents, selectedEventId]
  );

  // 自动滚动
  useEffect(() => {
    if (autoScroll && !isPaused && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [filteredEvents, autoScroll, isPaused]);

  // 暂停/恢复
  const togglePause = useCallback(() => {
    if (!isPaused) {
      setPausedEvents([...rawEvents]);
    }
    setIsPaused(!isPaused);
  }, [isPaused, rawEvents]);

  // 导出日志
  const handleExport = useCallback(() => {
    const exportData = filteredEvents.map(e => ({
      timestamp: e.timestamp,
      type: e.eventType,
      data: e.parsedData,
      size: e.size,
    }));
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `finsight-console-${new Date().toISOString().slice(0, 19)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredEvents]);

  // 切换类型过滤
  const toggleTypeFilter = (type: RawEventType) => {
    setTypeFilter(prev => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  // 快捷键
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isMaximized) {
        setIsMaximized(false);
      }
      // Ctrl+F 聚焦搜索
      if ((e.ctrlKey || e.metaKey) && e.key === 'f' && isConsoleOpen) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMaximized, isConsoleOpen]);

  // 折叠状态
  if (!isConsoleOpen) {
    return (
      <button
        onClick={() => setConsoleOpen(true)}
        className="w-full p-2.5 bg-fin-card border border-fin-border rounded-xl hover:bg-fin-hover transition-colors flex items-center justify-between group"
      >
        <div className="flex items-center gap-2">
          <Terminal size={13} className="text-fin-primary" />
          <span className="text-[11px] font-mono font-bold text-fin-text-secondary uppercase tracking-wider">Console</span>
        </div>
        <div className="flex items-center gap-2">
          {runningAgents > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 animate-pulse font-mono">
              {runningAgents} active
            </span>
          )}
          <span className="text-[10px] text-fin-muted font-mono">{rawEvents.length} events</span>
          <ChevronDown size={12} className="text-fin-muted group-hover:text-fin-text" />
        </div>
      </button>
    );
  }

  const consoleContent = (
    <div className={`flex flex-col bg-fin-card overflow-hidden font-mono shadow-sm ${isMaximized ? 'h-full' : 'border border-fin-border rounded-xl'}`}
      style={isMaximized ? {} : { maxHeight: '50vh' }}
    >
      {/* ═══════ 顶部工具栏 ═══════ */}
      <div className="flex items-center justify-between px-2 py-1.5 bg-fin-bg border-b border-fin-border">
        {/* 左侧 */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setConsoleOpen(false)}
            className="flex items-center gap-1.5 hover:opacity-80"
          >
            <Terminal size={13} className="text-fin-primary" />
            <span className="text-[11px] font-bold text-fin-text-secondary uppercase tracking-wider">Console</span>
            <ChevronUp size={12} className="text-fin-muted" />
          </button>

          {isPaused && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-fin-danger/15 text-fin-danger font-bold animate-pulse">
              PAUSED
            </span>
          )}

          {runningAgents > 0 && !isPaused && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-fin-success/15 text-fin-success flex items-center gap-1">
              <Zap size={9} className="animate-pulse" />
              {runningAgents} active
            </span>
          )}
        </div>

        {/* 右侧工具按钮 */}
        <div className="flex items-center gap-1">
          {/* 搜索框 */}
          <div className="relative flex items-center">
            <Search size={10} className="absolute left-1.5 text-fin-muted" />
            <input
              ref={searchRef}
              type="text"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Filter..."
              className="w-24 focus:w-36 transition-all bg-fin-panel border border-fin-border rounded text-[10px] text-fin-text pl-5 pr-1.5 py-0.5 focus:outline-none focus:border-fin-primary/50 placeholder-fin-muted"
            />
            {searchText && (
              <button
                onClick={() => setSearchText('')}
                className="absolute right-1 text-fin-muted hover:text-fin-text"
              >
                <X size={9} />
              </button>
            )}
          </div>

          {/* Token 开关 */}
          <button
            onClick={() => setShowTokens(!showTokens)}
            className={`p-1 rounded text-[10px] transition-colors ${showTokens ? 'text-fin-text bg-fin-hover' : 'text-fin-muted hover:text-fin-text'}`}
            title={showTokens ? 'Hide token events' : 'Show token events'}
          >
            {showTokens ? <Eye size={11} /> : <EyeOff size={11} />}
          </button>

          {/* 暂停/继续 */}
          <button
            onClick={togglePause}
            className={`p-1 rounded transition-colors ${isPaused ? 'text-fin-danger bg-fin-danger/10' : 'text-fin-muted hover:text-fin-text'}`}
            title={isPaused ? 'Resume' : 'Pause'}
          >
            {isPaused ? <Play size={11} /> : <Pause size={11} />}
          </button>

          {/* 自动滚动 */}
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`p-1 rounded text-[10px] font-bold transition-colors ${autoScroll ? 'text-fin-primary bg-fin-primary/10' : 'text-fin-muted hover:text-fin-text'}`}
            title={autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
          >
            ↓
          </button>

          {/* 导出 */}
          <button
            onClick={handleExport}
            className="p-1 rounded text-fin-muted hover:text-fin-text transition-colors"
            title="Export logs"
          >
            <Download size={11} />
          </button>

          {/* 全屏 */}
          <button
            onClick={() => setIsMaximized(!isMaximized)}
            className="p-1 rounded text-fin-muted hover:text-fin-text transition-colors"
            title={isMaximized ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {isMaximized ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
          </button>

          {/* 清空 */}
          <button
            onClick={() => { clearRawEvents(); setSelectedEventId(null); }}
            className="p-1 rounded text-fin-muted hover:text-fin-danger transition-colors"
            title="Clear console"
          >
            <Trash2 size={11} />
          </button>
        </div>
      </div>

      {/* ═══════ 事件类型快速过滤 ═══════ */}
      <div className="flex items-center gap-1 px-2 py-1 bg-fin-panel border-b border-fin-border/50 overflow-x-auto scrollbar-none">
        <span className="text-[9px] text-fin-muted shrink-0">TYPE:</span>
        {Object.entries(EVENT_TYPE_CONFIG)
          .filter(([key]) => key !== 'unknown')
          .map(([key, cfg]) => {
            const count = stats.typeCounts[key] || 0;
            const isActive = typeFilter.size === 0 || typeFilter.has(key as RawEventType);
            return (
              <button
                key={key}
                onClick={() => toggleTypeFilter(key as RawEventType)}
                className={`flex items-center gap-0.5 px-1.5 py-[1px] rounded text-[9px] whitespace-nowrap transition-all ${
                  isActive
                    ? `${cfg.bg} ${cfg.color}`
                    : 'text-fin-muted/50 hover:text-fin-muted'
                }`}
              >
                {cfg.icon} {cfg.label}
                {count > 0 && <span className="text-[8px] opacity-60 ml-0.5">{count}</span>}
              </button>
            );
          })}
        {typeFilter.size > 0 && (
          <button
            onClick={() => setTypeFilter(new Set())}
            className="text-[9px] text-fin-muted hover:text-fin-text px-1"
          >
            ✕ clear
          </button>
        )}
      </div>

      {/* ═══════ 事件列表 + 详情面板 ═══════ */}
      <div className={`flex flex-1 min-h-0 ${isMaximized ? '' : 'max-h-[35vh]'}`}>
        {/* 左侧事件列表 */}
        <div
          ref={listRef}
          className={`overflow-y-auto overflow-x-hidden scrollbar-thin ${
            selectedEvent ? 'w-1/2 border-r border-fin-border' : 'w-full'
          }`}
        >
          {filteredEvents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-fin-muted">
              <Terminal size={24} className="mb-2 opacity-30" />
              <p className="text-[11px]">
                {rawEvents.length === 0
                  ? 'Waiting for events...'
                  : 'No matching events'
                }
              </p>
              <p className="text-[10px] text-fin-muted/70">
                {rawEvents.length === 0
                  ? 'Send a message to see raw SSE event stream'
                  : `${rawEvents.length} events hidden by filters`
                }
              </p>
            </div>
          ) : (
            filteredEvents.map((event, idx) => (
              <EventRow
                key={event.id}
                event={event}
                index={idx + 1}
                isSelected={event.id === selectedEventId}
                onClick={() => setSelectedEventId(event.id === selectedEventId ? null : event.id)}
                showTokens={showTokens}
              />
            ))
          )}
        </div>

        {/* 右侧详情面板 */}
        {selectedEvent && (
          <div className="w-1/2 overflow-hidden">
            <EventDetail event={selectedEvent} onClose={() => setSelectedEventId(null)} />
          </div>
        )}
      </div>

      {/* ═══════ 底部状态栏 ═══════ */}
      <div className="flex items-center justify-between px-2 py-1 bg-fin-bg border-t border-fin-border text-[10px] text-fin-muted">
        <div className="flex items-center gap-3">
          <span>{stats.filtered}/{stats.total} events</span>
          <span>{formatSize(stats.totalBytes)}</span>
          {!showTokens && stats.typeCounts['token'] > 0 && (
            <span className="text-fin-muted/70">({stats.typeCounts['token']} tokens hidden)</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {Object.entries(agentStatuses)
            .filter(([, s]) => s.status === 'running')
            .map(([key]) => (
              <span key={key} className="px-1 py-0.5 rounded bg-fin-success/10 text-fin-success text-[9px]">
                {key}
              </span>
            ))
          }
        </div>
      </div>
    </div>
  );

  // 全屏模式 - 真正的全屏覆盖
  if (isMaximized) {
    return (
      <div className="fixed inset-0 z-[200] bg-fin-bg/95 backdrop-blur-sm flex flex-col">
        {consoleContent}
      </div>
    );
  }

  return consoleContent;
};
