/**
 * 统一断点常量 — CSS (Tailwind) 和 JS 共用
 *
 * Tailwind 默认断点: sm=640, md=768, lg=1024, xl=1280, 2xl=1536
 * 本项目仅覆盖需要自定义的断点, 其余保持 Tailwind 默认值。
 */

export const BREAKPOINTS = {
  /** 手机竖屏上限 */
  sm: 640,
  /** 平板竖屏上限 */
  md: 768,
  /** 平板横屏 / 小桌面 — 侧边栏折叠阈值 */
  lg: 1024,
  /** 桌面 — 右侧面板显示阈值 */
  xl: 1280,
  /** 大桌面 */
  '2xl': 1536,
} as const;

export type BreakpointKey = keyof typeof BREAKPOINTS;
