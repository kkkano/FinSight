import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Paperclip, SendHorizontal, Square, X } from 'lucide-react';

import { useAgentMention } from '../hooks/useAgentMention';
import { useChatStream } from '../hooks/useChatStream';
import { useSkillAutocomplete } from '../hooks/useSkillAutocomplete';
import { zh } from '../locales/zh';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { TICKER_PATTERN } from '../utils/ticker';
import { AgentMention } from './AgentMention';
import { AiDisclaimer } from './common/AiDisclaimer';
import { buildChatSuggestions } from './chatSuggestions';
import { SkillAutocomplete } from './SkillAutocomplete';
import { SkillLibraryDrawer } from './SkillLibraryDrawer';

const EMPTY_RESEARCH_PROMPTS = new Set([
  'hi', 'hello', 'hey', '你好', '您好', '嗨', '哈喽', '在吗', '在么',
]);

const hasActionableResearchInput = (text: string): boolean => {
  const trimmed = text.trim();
  if (!trimmed) return false;
  const compact = trimmed.replace(/\s+/g, '').toLowerCase();
  const withoutPunctuation = compact.replace(/[?!,.，。！？、；;:：'"“”‘’()[\]{}<>《》]/g, '');
  if (!withoutPunctuation || EMPTY_RESEARCH_PROMPTS.has(withoutPunctuation)) return false;
  if (!/[A-Za-z0-9\u3400-\u9FFF]/.test(trimmed)) return false;
  return withoutPunctuation.length >= 2 || TICKER_PATTERN.test(trimmed.toUpperCase());
};

const selectionKindLabel = (type: string): string => {
  if (type === 'news') return zh.chat.selectionKinds.news;
  if (type === 'risk') return zh.chat.selectionKinds.risk;
  if (type === 'insight') return zh.chat.selectionKinds.insight;
  return zh.chat.selectionKinds.report;
};

interface ChatInputProps {
  onDashboardRequest?: (symbol: string) => void;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const ChatInput: React.FC<ChatInputProps> = ({ onDashboardRequest: _onDashboardRequest }) => {
  const [input, setInput] = useState('');
  const [outputMode, setOutputMode] = useState<'chat' | 'investment_report'>('chat');
  const [skillLibraryOpen, setSkillLibraryOpen] = useState(false);
  const isChatLoading = useStore((state) => state.isChatLoading);
  const draft = useStore((state) => state.draft);
  const setDraft = useStore((state) => state.setDraft);
  const currentTicker = useStore((state) => state.currentTicker);
  const sessionId = useStore((state) => state.sessionId);
  const { activeAsset, activeSelections, clearSelection, watchlist } = useDashboardStore();
  const suggestions = buildChatSuggestions(watchlist);
  const chatStream = useChatStream(sessionId);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const lastSessionIdRef = useRef(sessionId);

  const setComposerText = (text: string) => {
    setInput(text);
    setDraft(text);
  };

  const skillAutocomplete = useSkillAutocomplete(input, setComposerText);
  const agentMention = useAgentMention(input, setComposerText);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isChatLoading) return;
    void chatStream.send(text, { outputMode });
  };

  useEffect(() => {
    setInput(draft || '');
    if (inputRef.current && !draft) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.overflowY = 'hidden';
    }
    if (draft && inputRef.current) inputRef.current.focus();
  }, [draft]);

  useEffect(() => {
    if (lastSessionIdRef.current !== sessionId) {
      lastSessionIdRef.current = sessionId;
      setInput(useStore.getState().draft || '');
    }
    setOutputMode('chat');
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.overflowY = 'hidden';
    }
  }, [sessionId]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (skillAutocomplete.handleKeyDown(event) || agentMention.handleKeyDown(event)) return;
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const canGenerateReport = Boolean(
    activeAsset?.symbol
    || currentTicker
    || activeSelections.length > 0
    || hasActionableResearchInput(input),
  );

  useEffect(() => {
    if (!canGenerateReport && outputMode === 'investment_report') setOutputMode('chat');
  }, [canGenerateReport, outputMode]);

  return (
    <div className="p-4 bg-fin-bg border-t border-fin-border">
      {activeSelections.length > 0 && (
        <div className="max-w-5xl mx-auto mb-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/10 text-amber-500 text-xs font-medium max-w-[400px] border border-amber-500/20">
            <Paperclip size={12} className="shrink-0" />
            <span className="truncate">
              {selectionKindLabel(activeSelections[0].type)}{' '}
              {zh.chat.selectedPrefix}: {activeSelections.length === 1
                ? `${activeSelections[0].title.slice(0, 40)}${activeSelections[0].title.length > 40 ? '...' : ''}`
                : zh.chat.selectedCount(activeSelections.length, selectionKindLabel(activeSelections[0].type))}
            </span>
            <button
              onClick={clearSelection}
              className="shrink-0 p-0.5 rounded-full hover:bg-amber-500/20 transition-colors"
              title={zh.chat.clearSelection}
              aria-label={zh.chat.clearSelection}
            >
              <X size={12} />
            </button>
          </span>
        </div>
      )}
      <div className="max-w-5xl mx-auto mb-2 flex items-center justify-end gap-2 text-xs">
        <button
          type="button"
          data-testid="chat-report-toggle-btn"
          onClick={() => setOutputMode(outputMode === 'investment_report' ? 'chat' : 'investment_report')}
          disabled={isChatLoading || !canGenerateReport}
          className={`px-2 py-1 rounded border transition-colors ${
            outputMode === 'investment_report'
              ? 'border-amber-500 text-amber-500 bg-amber-500/10'
              : 'border-fin-border text-fin-text-secondary hover:border-amber-500/50'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
          title={canGenerateReport ? zh.chat.reportEnabledTitle : zh.chat.reportDisabledTitle}
        >
          {zh.chat.report}
        </button>
      </div>
      <div className="relative flex items-end max-w-5xl mx-auto">
        {skillAutocomplete.isOpen && (
          <SkillAutocomplete
            skills={skillAutocomplete.filteredSkills}
            selectedIndex={skillAutocomplete.selectedIndex}
            onSelect={skillAutocomplete.selectSkill}
            onOpenLibrary={() => setSkillLibraryOpen(true)}
          />
        )}
        {agentMention.isOpen && (
          <AgentMention
            agents={agentMention.filteredAgents}
            selectedIndex={agentMention.selectedIndex}
            onSelect={agentMention.selectAgent}
          />
        )}
        <textarea
          ref={inputRef}
          id="chat-input"
          value={input}
          onChange={(event) => {
            setComposerText(event.target.value);
            const element = event.target;
            element.style.height = 'auto';
            element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
            element.style.overflowY = element.scrollHeight > 160 ? 'auto' : 'hidden';
          }}
          onKeyDown={handleKeyDown}
          placeholder={isChatLoading
            ? zh.chat.inputWhileStreaming
            : zh.chat.inputPlaceholder}
          aria-label={zh.chat.inputLabel}
          rows={1}
          className="w-full bg-t-surface text-t-text border border-t-border rounded-lg py-3 pl-4 pr-28 focus:outline-none focus:ring-1 focus:ring-t-accent/30 focus:border-t-accent/70 transition-all placeholder-t-text3 resize-none overflow-y-hidden min-h-[44px] max-h-[160px]"
        />

        <div className="absolute right-2 flex items-center gap-2">
          {isChatLoading ? (
            <button
              data-testid="chat-stop-btn"
              onClick={chatStream.stop}
              aria-label={zh.chat.stop}
              className="p-2 max-lg:min-h-[44px] max-lg:min-w-[44px] flex items-center justify-center bg-fin-danger text-white rounded-lg hover:bg-red-600 transition-colors"
              title={zh.chat.stop}
            >
              <Square size={16} fill="currentColor" />
            </button>
          ) : (
            <button
              data-testid="chat-send-btn"
              onClick={handleSend}
              disabled={!input.trim()}
              aria-label={outputMode === 'investment_report' ? zh.chat.sendReport : zh.chat.sendMessage}
              className="p-2 max-lg:min-h-[44px] max-lg:min-w-[44px] flex items-center justify-center bg-fin-primary text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title={outputMode === 'investment_report' ? zh.chat.sendReport : zh.chat.send}
            >
              <SendHorizontal size={18} />
            </button>
          )}
        </div>
      </div>
      <SkillLibraryDrawer
        open={skillLibraryOpen}
        onClose={() => setSkillLibraryOpen(false)}
        onSelectSkill={(text) => {
          setComposerText(text);
          inputRef.current?.focus();
        }}
      />
      <div className="text-center mt-2">
        <AiDisclaimer variant="compact" />
        <div className="mt-2 flex flex-wrap justify-center gap-2 text-[11px]">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion.label}
              className="min-h-11 px-3 py-2 rounded font-mono text-2xs border border-t-border text-t-text2 hover:border-t-accent/60 hover:text-t-accent transition-colors"
              onClick={() => {
                if (suggestion.report) setOutputMode('investment_report');
                setComposerText(suggestion.prompt);
              }}
              disabled={isChatLoading}
            >
              {suggestion.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
