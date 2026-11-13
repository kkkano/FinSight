import { useEffect, useRef, useState } from 'react';
import { ModelPickerButton } from './settings/ModelPickerButton';
import type { KeyboardEvent } from 'react';
import { ArrowUp, Paperclip, Square, X, Plus, ImagePlus, Loader2 } from 'lucide-react';

import { useChatStream } from '../hooks/useChatStream';
import { usePngAttachments } from '../hooks/usePngAttachments';
import { MAX_PNG_ATTACHMENTS } from '../utils/pngAttachments';
import { useWatchlist } from '../hooks/useWatchlist';
import { zh } from '../locales/zh';
import { researchFailureMessage } from '../store/researchStream';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { useModelSelectionStore } from '../store/modelSelection';
import { TICKER_PATTERN } from '../utils/ticker';
import { AiDisclaimer } from './common/AiDisclaimer';
import { buildChatSuggestions } from './chatSuggestions';
import { SelectedSkills, SkillPicker } from "./chat/SkillPicker";
import { useSkillPicker } from "./chat/SkillPicker.utils";
import { hasUnselectedSkillCommand, removeSkillCommand } from '../utils/skillCommands';
import type { ResearchSkill } from '../types/runtime';
import styles from './chat/ChatDesign.module.css';

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
  const [sendingInstruction, setSendingInstruction] = useState(false);
  const [outputMode, setOutputMode] = useState<'chat' | 'investment_report'>('chat');
  const isChatLoading = useStore((state) => state.isChatLoading);
  const modelMetadata = useModelSelectionStore((state) => state.metadata);
  const unsupportedModel = modelMetadata?.native_tool_calls === false || modelMetadata?.supports_tools === false || modelMetadata?.capability_status === 'unsupported';
  const draft = useStore((state) => state.draft);
  const setDraft = useStore((state) => state.setDraft);
  const currentTicker = useStore((state) => state.currentTicker);
  const sessionId = useStore((state) => state.sessionId);
  const ownerId = useStore((state) => state.authIdentity?.userId);
  const png = usePngAttachments(sessionId, ownerId);
  const skills = useSkillPicker(sessionId, ownerId, isChatLoading);
  const hasSkillCommand = hasUnselectedSkillCommand(input);
  const unsupportedVision = png.attachments.length > 0 && modelMetadata?.vision === false;
  const { activeAsset, activeSelections, clearSelection } = useDashboardStore();
  const { watchlist } = useWatchlist();
  const suggestions = buildChatSuggestions(watchlist);
  const chatStream = useChatStream(sessionId);
  const hasUserMessages = useStore((state) => state.messages.some((message) => message.role === 'user'));
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastSessionIdRef = useRef(sessionId);

  const setComposerText = (text: string, caret = text.length) => {
    setInput(text);
    setDraft(text);
    skills.updateCommand(text, caret);
  };

  const handleSkillSelect = (skill: ResearchSkill) => {
    const next = removeSkillCommand(input, skills.command);
    if (!skills.select(skill)) return;
    setComposerText(next);
    inputRef.current?.focus();
  };

  const handleSend = () => {
    const text = input.trim() || (png.attachments.length ? '请分析我附上的图片，说明可读信息与不确定性。' : '');
    if (!text || hasSkillCommand || sendingInstruction || unsupportedModel || unsupportedVision || png.reading) return;
    if (isChatLoading) {
      setSendingInstruction(true);
      void chatStream.steer(text).then((accepted) => { if (accepted) setComposerText(''); }).finally(() => setSendingInstruction(false));
      return;
    }
    const images = png.attachments.map(({ data_url, name }) => ({ data_url, name }));
    const skillIds = skills.selected.map((skill) => skill.id);
    png.clear();
    skills.clear();
    void chatStream.send(text, { outputMode, ...(images.length ? { images } : {}), ...(skillIds.length ? { skillIds } : {}) });
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
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (skills.open) {
      if (event.key === 'Escape') { event.preventDefault(); skills.close(); return; }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault(); skills.move(event.key === 'ArrowDown' ? 1 : -1); return;
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        const selected = skills.rows[skills.activeIndex];
        if (selected && !skills.loading && !skills.error) handleSkillSelect(selected);
        return;
      }
    }
    if (event.key === 'Escape' && isChatLoading) { event.preventDefault(); chatStream.stop(); return; }
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
    <div className={`chat-composer ${styles.composerOuter}`}>
      {!skills.open && <SelectedSkills skills={skills.selected} onRemove={skills.remove} />}
      {unsupportedModel && <div className="mx-auto mb-2 max-w-[760px] text-sm text-fin-danger" role="alert">
        <span>{zh.chat.unsupportedModel}</span><ModelPickerButton label={zh.chat.changeModel} />
      </div>}
      {png.error && <p className="mx-auto mb-2 max-w-[760px] text-sm text-fin-danger" role="alert">{researchFailureMessage({ error_code: png.errorCode })}</p>}
      {png.attachments.length > 0 && <div className="mx-auto mb-3 max-w-[760px]" data-testid="chat-image-attachments">
        <div className="flex flex-wrap gap-3">{png.attachments.map((attachment) => <div key={attachment.id} className="relative rounded-lg border border-t-border bg-t-card p-1.5">
          <img src={attachment.data_url} alt={'附件：' + attachment.name} className="h-20 w-24 rounded object-contain" />
          <p className="mt-1 max-w-24 truncate text-[11px] text-t-text3" title={attachment.name}>{attachment.name}</p>
          <button type="button" onClick={() => png.remove(attachment.id)} aria-label={'移除图片 ' + attachment.name}
            className="absolute -right-2 -top-2 flex h-7 w-7 items-center justify-center rounded-full border border-t-border bg-t-card text-t-text2"><X size={13} /></button>
        </div>)}</div>
        <p className="mt-2 text-xs leading-5 text-t-text3">PNG 会发送给你选的模型，发送后清空，不保存在聊天记录里。最多3张，每张2 MiB、800万像素以内。</p>
        {modelMetadata?.vision !== true && <p className={'mt-1 text-xs ' + (unsupportedVision ? 'text-fin-danger' : 'text-t-text3')} role="status">
          {unsupportedVision ? '当前模型不支持图片，请更换模型或移除附件。' : '此模型的图像能力尚未确认，发送时由服务器校验。'}
        </p>}
      </div>}
      {activeSelections.length > 0 && (
        <div className="max-w-[760px] mx-auto mb-2">
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
      <div className={styles.composer}>
        {skills.open && <SkillPicker rows={skills.rows} selected={skills.selected} activeIndex={skills.activeIndex}
          loading={skills.loading} error={skills.error} onSelect={handleSkillSelect} onRemove={skills.remove} onClose={skills.close} onRetry={skills.retry} />}
        <textarea
          ref={inputRef}
          id="chat-input"
          value={input}
          onChange={(event) => {
            setComposerText(event.target.value, event.target.selectionStart);
            const element = event.target;
            element.style.height = 'auto';
            element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
            element.style.overflowY = element.scrollHeight > 160 ? 'auto' : 'hidden';
          }}
          onKeyDown={handleKeyDown}
          onClick={(event) => skills.updateCommand(input, event.currentTarget.selectionStart)}
          onPaste={(event) => {
            const files = Array.from(event.clipboardData.files);
            if (!files.length) return;
            event.preventDefault();
            if (!isChatLoading) void png.add(files);
          }}
          placeholder={isChatLoading ? '补充要求，按 Enter 发送…' : '输入问题，或用 / 选择技能…'}
          aria-label={zh.chat.inputLabel}
          aria-expanded={skills.open}
          aria-controls={skills.open ? 'chat-skill-listbox' : undefined}
          aria-activedescendant={skills.open && skills.rows[skills.activeIndex] ? `chat-skill-option-${skills.activeIndex}` : undefined}
          rows={2}
        />

        <input ref={fileInputRef} id="chat-image-input" type="file" accept="image/png" multiple className="hidden" aria-label="添加PNG图片"
          disabled={isChatLoading || png.reading || png.attachments.length >= MAX_PNG_ATTACHMENTS}
          onChange={(event) => { const files = Array.from(event.target.files || []); event.target.value = ''; void png.add(files); }} />
        <div className={styles.composerToolbar}>
          {!isChatLoading && <button type="button" onClick={() => fileInputRef.current?.click()}
            disabled={png.reading || png.attachments.length >= MAX_PNG_ATTACHMENTS} aria-label="添加PNG图片" title="添加PNG图片（最多3张，每张2 MiB以内）"
            className={styles.composerAction}>
            {png.reading ? <Loader2 size={17} className="animate-spin" /> : <ImagePlus size={17} />}
          </button>}
          {!isChatLoading && <button type="button" data-testid="chat-report-toggle-btn"
            onClick={() => setOutputMode(outputMode === 'investment_report' ? 'chat' : 'investment_report')}
            disabled={!canGenerateReport} aria-pressed={outputMode === 'investment_report'}
            className={`${styles.composerAction} disabled:opacity-50`}
            style={outputMode === 'investment_report' ? { color: 'rgb(var(--t-accent))', background: 'var(--t-accent-soft)' } : undefined}
            title={canGenerateReport ? zh.chat.reportEnabledTitle : zh.chat.reportDisabledTitle}>深度研究</button>}
          <div className={styles.composerModel}><ModelPickerButton /></div>
          {isChatLoading && input.trim() && <button type="button" onClick={handleSend} disabled={sendingInstruction}
            data-testid="chat-steer-btn" className="flex h-9 w-9 items-center justify-center rounded-lg bg-t-accent text-white dark:text-[#0e1014] disabled:opacity-50"
            aria-label="追加要求" title="追加要求"><Plus size={18} /></button>}
          {isChatLoading ? (
            <button
              data-testid="chat-stop-btn"
              onClick={chatStream.stop}
              aria-label={zh.chat.stop}
              className={`${styles.composerSend} ${styles.composerStop}`}
              title={zh.chat.stop}
            >
              <Square size={16} fill="currentColor" />
            </button>
          ) : (
            <button
              data-testid="chat-send-btn"
              onClick={handleSend}
              disabled={(!input.trim() && !png.attachments.length) || hasSkillCommand || unsupportedModel || unsupportedVision || png.reading}
              aria-label={outputMode === 'investment_report' ? zh.chat.sendReport : zh.chat.sendMessage}
              className={styles.composerSend}
              title={outputMode === 'investment_report' ? zh.chat.sendReport : zh.chat.send}
            >
              <ArrowUp size={16} />
            </button>
          )}
        </div>
      </div>
      <div className={styles.composerFootnote}>
        <span>{isChatLoading ? 'Enter 追加要求 · Esc 停止' : 'Enter 发送 · Shift + Enter 换行 · / 选择技能'}</span>
        <AiDisclaimer variant="compact" />
      </div>
      {!hasUserMessages && !isChatLoading && <div className="mx-auto mt-2 flex max-w-[760px] flex-wrap justify-center gap-2 text-[11px]">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion.label}
              className="min-h-9 px-3 py-1.5 rounded-full text-xs border border-t-border/60 text-t-text2 hover:border-t-accent/60 hover:text-t-accent transition-colors"
              onClick={() => {
                if (suggestion.report) setOutputMode('investment_report');
                setComposerText(suggestion.prompt);
              }}
              disabled={isChatLoading}
            >
              {suggestion.label}
            </button>
          ))}
        </div>}
    </div>
  );
};
