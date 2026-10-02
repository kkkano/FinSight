import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModelSettings } from './ModelSettings';
import type { CatalogModel, ModelSelection } from '../../store/modelSelection';

const state = vi.hoisted(() => ({
  selection: null as ModelSelection | null,
  metadata: null,
  catalog: [] as CatalogModel[],
  setCatalog: vi.fn(),
  applySelection: vi.fn(),
  clearSelection: vi.fn(),
}));

vi.mock('../../store/modelSelection', async () => {
  const actual = await vi.importActual<typeof import('../../store/modelSelection')>('../../store/modelSelection');
  return { ...actual, useModelSelectionStore: () => state };
});

beforeEach(() => {
  state.selection = null;
  state.catalog = [{
    id: 'stepfun:step-5-preview', label: 'Step 5 Preview', model: 'step-5-preview', provider: 'stepfun',
    icon_url: '/model-icons/stepfun.png', effort_options: ['low', 'medium', 'high'],
    default_effort: 'medium', available: true, docs_url: 'https://platform.stepfun.com/docs/zh/guides/models/step-5-preview',
  }];
});

describe('ModelSettings', () => {
  it('renders only the declared built-in effort values and official metadata without key controls', () => {
    const markup = renderToStaticMarkup(<ModelSettings />);
    expect(markup).toContain('Step 5 Preview');
    expect(markup).toContain('/model-icons/stepfun.png');
    expect(markup).toContain('https://platform.stepfun.com/docs/zh/guides/models/step-5-preview');
    expect(markup).toContain('value="low"');
    expect(markup).toContain('value="medium" selected');
    expect(markup).toContain('value="high"');
    expect(markup).not.toContain('xhigh');
    expect(markup).not.toContain('API Key');
    expect(markup).not.toContain('type="password"');
  });

  it('uses a password input only for custom models and explains the memory-only lifetime', () => {
    state.selection = { source: 'custom', base_url: 'https://api.example.com/v1', model: 'unknown-model', api_key: '', context_acknowledged: true };
    const markup = renderToStaticMarkup(<ModelSettings />);
    expect(markup).toContain('type="password"');
    expect(markup).toContain('当前页面内存');
    expect(markup).toContain('刷新页面后需重新填写并测试');
    expect(markup).toContain('推理强度：供应商默认');
    expect(markup).not.toContain('aria-label="推理强度"');
    expect(markup).toContain('系统提示词');
    expect(markup).toContain('RAG 检索上下文');
    expect(markup).toContain('付费数据源');
    expect(markup).toContain('对应的外部服务');
    expect(markup).not.toContain('checked=""');
  });

  it('gives anonymous users a login entry and disables explicit model test and application', () => {
    const markup = renderToStaticMarkup(<ModelSettings />);
    expect(markup).toContain('登录后才能测试或切换模型');
    expect(markup).toContain('href="/welcome?from=%2Fchat"');
    expect(markup).toMatch(/<button[^>]+disabled=""[^>]*>测试连接<\/button>/);
    expect(markup).toMatch(/<button[^>]+disabled=""[^>]*>应用模型<\/button>/);
  });
});
