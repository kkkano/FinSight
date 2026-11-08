import type { Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const referenceRoot = fileURLToPath(new URL('../../../docs/design/2026-11-06_claude_agent_chat/', import.meta.url));

/** 快照未附support.js；只解释仓库原稿自带的默认props、renderVals和条件/循环，不改设计文件。 */
export async function renderDesignReference(page: Page, name: string, dark = false) {
  const html = readFileSync(join(referenceRoot, `${name}.dc.html`), 'utf8')
    .replace(/<script[^>]+src="\.\/support\.js"[^>]*><\/script>/g, '')
    .replace(/<link[^>]+href="https:\/\/fonts\.[^"]+"[^>]*>/g, '');
  await page.setContent(html, { waitUntil: 'domcontentloaded' });
  await page.evaluate((dark) => {
    const script = document.querySelector<HTMLScriptElement>('script[data-dc-script]');
    if (!script) return;
    const definitions = JSON.parse(script.getAttribute('data-props') || '{}');
    const props = Object.fromEntries(Object.entries(definitions).map(([key, definition]) => [key,
      definition && typeof definition === 'object' && 'default' in definition ? (definition as { default: unknown }).default : definition]));
    class DCLogic { props = { ...props, dark }; state = {}; setState() {} }
    // 这里仅执行用户提供的本地设计稿中的渲染函数，绝不用于模型产物。
    const Component = new Function('DCLogic', `${script.textContent}; return Component;`)(DCLogic);
    const values = new Component().renderVals();
    const resolve = (expression: string, scope: Record<string, unknown>) => expression.trim() === 'true' ? true
      : expression.trim() === 'false' ? false : expression.trim().split('.').reduce<unknown>((current, key) =>
        current && typeof current === 'object' ? (current as Record<string, unknown>)[key] : undefined, scope);
    const interpolate = (value: string, scope: Record<string, unknown>) => value.replace(/\{\{\s*(.*?)\s*\}\}/g,
      (_match, expression: string) => { const result = resolve(expression, scope); return typeof result === 'function' ? '' : String(result ?? ''); });
    const walk = (node: Node, scope: Record<string, unknown>) => {
      if (node.nodeType === Node.TEXT_NODE) { node.textContent = interpolate(node.textContent || '', scope); return; }
      if (!(node instanceof Element)) return;
      if (node.tagName.toLowerCase() === 'sc-for') {
        const expression = (node.getAttribute('list') || '').replace(/[{}]/g, '').trim();
        const items = resolve(expression, scope);
        if (Array.isArray(items)) for (const item of items) {
          const clone = node.cloneNode(true) as Element;
          const next = { ...scope, [node.getAttribute('as') || 'item']: item };
          for (const child of Array.from(clone.childNodes)) { walk(child, next); node.before(child); }
        }
        node.remove(); return;
      }
      if (node.tagName.toLowerCase() === 'sc-if') {
        const value = resolve((node.getAttribute('value') || '').replace(/[{}]/g, '').trim(), scope);
        if (!value) { node.remove(); return; }
        for (const child of Array.from(node.childNodes)) walk(child, scope);
        node.replaceWith(...Array.from(node.childNodes)); return;
      }
      for (const attribute of Array.from(node.attributes)) {
        if (/^on/i.test(attribute.name)) node.removeAttribute(attribute.name);
        else node.setAttribute(attribute.name, interpolate(attribute.value, scope));
      }
      for (const child of Array.from(node.childNodes)) walk(child, scope);
    };
    const root = document.querySelector('x-dc');
    if (root) walk(root, values);
  }, dark);
}
