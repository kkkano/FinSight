import { renderToString } from 'react-dom/server';
import { expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({
  imports: vi.fn(), mounted: vi.fn(), release: undefined as (() => void) | undefined,
}));

vi.mock('./EChartRuntime', () => {
  state.imports();
  return new Promise<{ default: () => null }>((resolve) => {
    state.release = () => resolve({ default: () => { state.mounted(); return null; } });
  });
});

it('keeps the engine out of initial imports and renders a fallback while it loads', async () => {
  const { default: EChart } = await import('./EChart');
  expect(state.imports).not.toHaveBeenCalled();
  const html = renderToString(<EChart option={{}} />);
  expect(html).toContain('aria-busy="true"');
  await vi.waitFor(() => expect(state.imports).toHaveBeenCalledTimes(1));
  state.release?.();
  await Promise.resolve();
  expect(state.mounted).not.toHaveBeenCalled();
});
