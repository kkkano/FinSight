import { useEffect, useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import { CheckCircle, Cpu, LoaderCircle, RefreshCw } from 'lucide-react';
import { apiClient } from '../../api/client';
import { useModelSelectionStore, validateCustomModelSelection } from '../../store/modelSelection';
import type { ModelCapabilities, ModelTestSelection } from '../../store/modelSelection';
import { useStore } from '../../store/useStore';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Input } from '../ui/Input';

const selectClassName = 'w-full bg-fin-bg border border-fin-border rounded-lg px-3 py-2 text-fin-text text-sm focus:border-fin-primary outline-none';

export function ModelSettings() {
  const { selection, pendingCustom, metadata, catalog, defaultModelId, setCatalog, applySelection, clearSelection } = useModelSelectionStore();
  const authUserId = useStore((state) => state.authIdentity?.userId);
  const isAuthenticated = Boolean(authUserId);
  const previousUserId = useRef(authUserId);
  const testVersion = useRef(0);
  const [source, setSource] = useState<'system' | 'custom'>(selection?.source || pendingCustom?.source || 'system');
  const [systemId, setSystemId] = useState(selection?.source === 'system' ? selection.model_id : '');
  const [systemEffort, setSystemEffort] = useState(selection?.source === 'system' ? selection.effort || '' : '');
  const [custom, setCustom] = useState({
    base_url: selection?.source === 'custom' ? selection.base_url : pendingCustom?.base_url || '',
    model: selection?.source === 'custom' ? selection.model : pendingCustom?.model || '',
    api_key: isAuthenticated && selection?.source === 'custom' ? selection.api_key : '',
  });
  const [customEffort, setCustomEffort] = useState(selection?.source === 'custom' ? selection.effort || '' : pendingCustom?.effort || '');
  const [capabilities, setCapabilities] = useState<ModelCapabilities | null>(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(false);
  const [capabilitiesError, setCapabilitiesError] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(catalog.length === 0);
  const [catalogError, setCatalogError] = useState(false);
  const [reload, setReload] = useState(0);
  const [testing, setTesting] = useState(false);
  const [testedSignature, setTestedSignature] = useState<string | null>(null);
  const [status, setStatus] = useState<{ success: boolean; message: string } | null>(null);
  const [contextAcknowledged, setContextAcknowledged] = useState(false);

  useEffect(() => {
    setSource(selection?.source || pendingCustom?.source || 'system');
    setSystemId(selection?.source === 'system' ? selection.model_id : '');
    setSystemEffort(selection?.source === 'system' ? selection.effort || '' : '');
    const draft = selection?.source === 'custom' ? selection : pendingCustom;
    setCustom({ base_url: draft?.base_url || '', model: draft?.model || '', api_key: selection?.source === 'custom' ? selection.api_key : '' });
    setCustomEffort(draft?.effort || '');
    setContextAcknowledged(false);
    setTestedSignature(null);
  }, [selection, pendingCustom]);

  useEffect(() => {
    if (previousUserId.current === authUserId) return;
    previousUserId.current = authUserId;
    testVersion.current += 1;
    setCustom((previous) => ({ ...previous, api_key: '' }));
    setContextAcknowledged(false);
    setTestedSignature(null);
    setStatus(null);
    setTesting(false);
  }, [authUserId]);

  useEffect(() => {
    let active = true;
    setCatalogLoading(true);
    setCatalogError(false);
    apiClient.getModels().then(({ models, default_model_id }) => {
      if (active) setCatalog(models, default_model_id);
    }).catch(() => {
      if (active) setCatalogError(true);
    }).finally(() => {
      if (active) setCatalogLoading(false);
    });
    return () => { active = false; };
  }, [reload, setCatalog]);

  useEffect(() => {
    setCapabilities(null);
    setCapabilitiesError(false);
    const input = {
      source: 'custom' as const,
      base_url: custom.base_url,
      model: custom.model,
      api_key: 'capability-check',
    };
    if (source !== 'custom' || validateCustomModelSelection(input)) {
      setCapabilitiesLoading(false);
      return;
    }
    let active = true;
    setCapabilitiesLoading(true);
    const timer = setTimeout(() => {
      apiClient.getModelCapabilities(custom.model.trim(), custom.base_url.trim()).then((result) => {
        if (!active) return;
        setCapabilities(result);
        setCustomEffort((value) => result.effort_options.includes(value)
          ? value
          : result.default_effort || '');
      }).catch(() => {
        if (active) setCapabilitiesError(true);
      }).finally(() => {
        if (active) setCapabilitiesLoading(false);
      });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [source, custom.base_url, custom.model, reload]);

  const systemModel = catalog.find((item) => item.id === (systemId || defaultModelId))
    || (!systemId && !defaultModelId ? catalog.find((item) => item.available) || catalog[0] : undefined);
  const selectedCapabilities = source === 'system' ? systemModel : capabilities;
  const effortOptions = selectedCapabilities?.effort_options || [];
  const draftEffort = source === 'system' ? systemEffort : customEffort;
  const effort = effortOptions.includes(draftEffort)
    ? draftEffort
    : selectedCapabilities?.default_effort || '';
  const candidate: ModelTestSelection | null = source === 'system'
    ? systemModel ? {
      source: 'system', model_id: systemModel.id, ...(effort ? { effort } : {}),
    } : null
    : {
      source: 'custom',
      base_url: custom.base_url.trim(),
      model: custom.model.trim(),
      api_key: custom.api_key.trim(),
      ...(effort ? { effort } : {}),
    };
  const signature = candidate ? JSON.stringify(candidate) : '';
  const customReady = source === 'custom' && testedSignature === signature;
  const currentLabel = pendingCustom ? `${pendingCustom.model}（待补填密钥）` : selection?.source === 'custom'
    ? selection.model
    : selection?.source === 'system' ? metadata?.label || selection.model_id
      : metadata?.label || catalog.find((model) => model.id === defaultModelId)?.label || '正在读取默认模型…';

  const resetTest = () => {
    setTestedSignature(null);
    setStatus(null);
  };

  const updateCustom = (key: keyof typeof custom, value: string) => {
    setCustom((previous) => ({ ...previous, [key]: value }));
    setContextAcknowledged(false);
    resetTest();
  };

  const testConnection = async () => {
    if (!candidate || !isAuthenticated) return;
    if (candidate.source === 'custom') {
      const validationError = validateCustomModelSelection(candidate);
      if (validationError) {
        setStatus({ success: false, message: validationError });
        return;
      }
      if (!capabilities) {
        setStatus({ success: false, message: '请先等待模型能力加载完成，再测试连接。' });
        return;
      }
    }
    setTesting(true);
    const version = ++testVersion.current;
    setTestedSignature(null);
    setStatus(null);
    try {
      const result = await apiClient.testModel(candidate);
      if (version !== testVersion.current) return;
      if (result.success) setTestedSignature(signature);
      setStatus({
        success: result.success,
        message: result.success
          ? `连接成功 · ${Math.round(result.latency_ms)} ms，可应用此模型。`
          : result.message || '连接测试失败，请检查配置后重试。',
      });
    } catch (error) {
      if (version !== testVersion.current) return;
      setStatus({
        success: false,
        message: isAxiosError(error) && error.response?.status === 429
          ? '测试请求过于频繁，请稍后重试。'
          : '连接测试失败，请检查登录状态、地址、密钥和模型后重试。',
      });
    } finally {
      if (version === testVersion.current) setTesting(false);
    }
  };

  const applyModel = () => {
    if (!candidate || !selectedCapabilities || !isAuthenticated) return;
    if (candidate.source === 'custom' && (!customReady || !contextAcknowledged)) return;
    if (candidate.source === 'system' && !systemModel?.available) return;
    applySelection(candidate.source === 'custom' ? { ...candidate, context_acknowledged: true } : candidate, selectedCapabilities);
    if (candidate.source === 'system') {
      setCustom((previous) => ({ ...previous, api_key: '' }));
      setTestedSignature(null);
      setContextAcknowledged(false);
    }
    setStatus({ success: true, message: '已应用，聊天、报告和个股 AI 判断将统一使用此模型。' });
  };

  return (
    <Card className="p-4 bg-fin-bg/40 space-y-4" data-testid="model-settings">
      <div>
        <h3 className="text-sm font-medium text-fin-text">模型选择</h3>
        <p className="mt-1 text-xs text-fin-muted">聊天、报告和个股 AI 判断统一使用此模型。</p>
        <div className="mt-2 flex items-center gap-2 text-xs text-fin-muted" data-testid="current-model">
          {metadata?.icon_url ? (
            <img src={metadata.icon_url} alt="" className="h-5 w-5 rounded object-contain" />
          ) : <Cpu size={16} aria-hidden="true" />}
          <span>当前使用：<span className="text-fin-text">{currentLabel}</span></span>
          {selection?.effort ? <span>· {selection.effort}</span> : null}
        </div>
      </div>

      {pendingCustom ? <p role="alert" className="text-sm leading-relaxed text-fin-warning">自带模型的密钥未保存，请重新填写、测试并应用，或选择内置模型。恢复前不会自动改用其他模型。</p> : null}

      {!isAuthenticated ? (
        <div className="rounded-lg border border-fin-border bg-fin-panel p-3 text-xs leading-relaxed text-fin-muted" role="note">
          <p>登录后才能测试或切换模型。未登录可查看行情和公开预测战绩。</p>
          <a href="/welcome?from=%2Fchat" className="mt-2 inline-flex min-h-9 items-center text-fin-primary hover:underline">前往登录</a>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2" aria-label="模型来源">
        {([{ id: 'system', label: '系统内置' }, { id: 'custom', label: '自带模型' }] as const).map((item) => (
          <button
            key={item.id}
            type="button"
            disabled={testing}
            aria-pressed={source === item.id}
            onClick={() => { setSource(item.id); setContextAcknowledged(false); resetTest(); }}
            className={`rounded-lg border px-3 py-2 text-sm transition-colors disabled:opacity-50 ${source === item.id
              ? 'border-fin-primary bg-fin-primary/10 text-fin-primary'
              : 'border-fin-border text-fin-text-secondary hover:border-fin-primary/50'}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {source === 'system' ? (
        <div className="space-y-3" data-testid="system-model-section">
          {catalogError ? (
            <div className="flex items-center justify-between gap-2 text-xs text-fin-muted" role="alert">
              <span>模型列表加载失败，请重试。</span>
              <Button size="sm" onClick={() => setReload((value) => value + 1)}><RefreshCw size={12} />重试</Button>
            </div>
          ) : null}
          <label className="block space-y-1 text-xs text-fin-muted">
            <span>内置模型</span>
            <select
              aria-label="内置模型"
              value={systemModel?.id || ''}
              disabled={catalogLoading || testing || !catalog.length}
              onChange={(event) => {
                setSystemId(event.target.value);
                setSystemEffort('');
                resetTest();
              }}
              className={selectClassName}
            >
              {!catalog.length ? <option value="">{catalogLoading ? '正在加载模型…' : '暂无内置模型'}</option> : null}
              {catalog.map((item) => (
                <option key={item.id} value={item.id}>{item.label}{item.available ? '' : '（暂不可用）'}</option>
              ))}
            </select>
          </label>
          <p className="text-xs text-fin-muted">
            {systemModel && !systemModel.available ? '此模型暂不可用，可稍后重试或使用自带模型。' : '选择后即可应用，也可以先测试连接。'}
          </p>
        </div>
      ) : (
        <div className="space-y-3" data-testid="custom-model-section">
          <Input label="API 地址" id="custom-model-base-url" type="url" value={custom.base_url}
            onChange={(event) => updateCustom('base_url', event.target.value)} disabled={testing || !isAuthenticated}
            placeholder="https://api.example.com/v1" maxLength={2048} autoComplete="off" spellCheck={false} />
          <p className="text-xs text-fin-muted">支持公共 HTTPS API 地址，使用默认端口或 443。</p>
          <Input label="模型 ID" id="custom-model-id" value={custom.model}
            onChange={(event) => updateCustom('model', event.target.value)} disabled={testing || !isAuthenticated}
            placeholder="供应商提供的模型名称" maxLength={200} autoComplete="off" spellCheck={false} />
          <Input label="API Key" id="custom-model-api-key" type="password" value={custom.api_key}
            onChange={(event) => updateCustom('api_key', event.target.value)} disabled={testing || !isAuthenticated}
            placeholder="输入你自己的 API Key" maxLength={4096} autoComplete="new-password" spellCheck={false} />
          <p className="text-xs text-fin-muted leading-relaxed">
            密钥仅保存在当前页面内存中；测试和使用时会发送至 FinSight 后端以调用你的服务。刷新页面后需重新填写并测试。
          </p>
          <div className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-relaxed text-fin-text-secondary">
            <p>应用后，FinSight 会把你的请求、系统提示词、RAG 检索上下文及可能来自付费数据源的内容发送到上方 API 地址对应的外部服务，由该服务处理。连接测试仅发送固定测试消息。</p>
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={contextAcknowledged} disabled={testing || !isAuthenticated}
                onChange={(event) => setContextAcknowledged(event.target.checked)} className="mt-0.5 accent-fin-primary" />
              <span>我已了解并同意将上述内容发送到填写的外部服务</span>
            </label>
          </div>
          {capabilitiesError ? (
            <div className="flex items-center justify-between gap-2 text-xs text-fin-muted" role="alert">
              <span>模型能力加载失败，请重试。</span>
              <Button size="sm" onClick={() => setReload((value) => value + 1)}>重试</Button>
            </div>
          ) : null}
        </div>
      )}

      {selectedCapabilities ? (
        <div className="flex items-center gap-2 text-xs text-fin-muted">
          {selectedCapabilities.icon_url ? (
            <img src={selectedCapabilities.icon_url} alt="" className="h-5 w-5 rounded object-contain" />
          ) : <Cpu size={16} aria-hidden="true" />}
          <span>{selectedCapabilities.provider}</span>
          {selectedCapabilities.docs_url ? (
            <a href={selectedCapabilities.docs_url} target="_blank" rel="noopener noreferrer" className="text-fin-primary hover:underline">官方文档</a>
          ) : null}
        </div>
      ) : null}

      {capabilitiesLoading && source === 'custom' ? <p className="text-xs text-fin-muted" role="status">正在读取模型能力…</p> : (
        effortOptions.length ? (
          <label className="block space-y-1 text-xs text-fin-muted">
            <span>推理强度</span>
            <select aria-label="推理强度" value={effort} disabled={testing} className={selectClassName}
              onChange={(event) => {
                if (source === 'system') setSystemEffort(event.target.value);
                else setCustomEffort(event.target.value);
                resetTest();
              }}>
              {!selectedCapabilities?.default_effort ? <option value="">供应商默认</option> : null}
              {effortOptions.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
        ) : <p className="text-xs text-fin-muted">推理强度：供应商默认</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" onClick={testConnection}
          disabled={!isAuthenticated || testing || (source === 'system' ? !systemModel?.available || catalogLoading : capabilitiesLoading)}>
          {testing ? <LoaderCircle size={14} className="animate-spin" /> : null}
          {testing ? '测试中…' : '测试连接'}
        </Button>
        <Button type="button" variant="primary" size="sm" onClick={applyModel}
          disabled={!isAuthenticated || testing || (source === 'system' ? !systemModel?.available || catalogLoading : !customReady || !contextAcknowledged)}>
          应用模型
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={testing || (!selection && !pendingCustom && !custom.api_key)} onClick={() => {
          clearSelection();
          setCustom((previous) => ({ ...previous, api_key: '' }));
          setContextAcknowledged(false);
          setTestedSignature(null);
          setSource('system');
          setStatus({ success: true, message: `已恢复默认模型${catalog.find((model) => model.id === defaultModelId)?.label ? `：${catalog.find((model) => model.id === defaultModelId)?.label}` : ''}。` });
        }}>恢复默认模型</Button>
      </div>
      {source === 'custom' && !customReady ? <p className="text-xs text-fin-muted">测试连接成功后即可应用；修改配置后需要重新测试。</p> : null}
      {status ? (
        <p role="status" aria-live="polite" className={`flex items-start gap-1.5 text-xs ${status.success ? 'text-fin-success' : 'text-fin-danger'}`}>
          {status.success ? <CheckCircle size={14} className="shrink-0" /> : null}{status.message}
        </p>
      ) : null}
    </Card>
  );
}
