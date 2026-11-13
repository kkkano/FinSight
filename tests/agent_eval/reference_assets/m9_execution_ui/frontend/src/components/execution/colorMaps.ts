/**
 * colorMaps — 瀑布图 / agent 矩阵的状态配色。
 *
 * ⚠️ alpha 陷阱：fin-* 中只有 fin-primary 是 rgb 通道格式支持 Tailwind alpha，
 * 其余 fin-panel/card/bg/border/hover 是 hex 变量，加 /alpha 会失效（暗色变白）。
 * 因此 bar / badge 填充一律使用 Tailwind 原生调色板（amber/violet/emerald/...），
 * 它们原生支持 /alpha。
 */
import type { WaterfallStatus } from './waterfallLayout';

/** bar 填充 class：按 kind(tool/agent) + status 区分。 */
export function waterfallBarClass(kind: string, status: WaterfallStatus): string {
  if (status === 'error') return 'bg-red-500/70 border-red-400';
  if (status === 'cached') return 'bg-emerald-500/55 border-emerald-400/70';
  if (status === 'skipped') return 'bg-slate-500/35 border-slate-400/50 border-dashed';
  if (status === 'running') return 'bg-blue-500/55 border-blue-400 animate-pulse';
  // done：按 kind 区分 tool(amber) / agent(violet)
  if (kind === 'agent') return 'bg-violet-500/65 border-violet-400';
  return 'bg-amber-500/65 border-amber-400';
}

/** 状态点颜色（小圆点 / 图标）。 */
export function waterfallDotClass(status: WaterfallStatus): string {
  switch (status) {
    case 'done':
      return 'bg-emerald-400';
    case 'cached':
      return 'bg-emerald-300';
    case 'skipped':
      return 'bg-slate-400';
    case 'running':
      return 'bg-blue-400 animate-pulse';
    case 'error':
      return 'bg-red-400';
    default:
      return 'bg-slate-500';
  }
}

export function waterfallStatusLabel(status: WaterfallStatus): string {
  switch (status) {
    case 'done':
      return '完成';
    case 'cached':
      return '缓存命中';
    case 'skipped':
      return '已跳过';
    case 'running':
      return '执行中';
    case 'error':
      return '失败';
    default:
      return '待执行';
  }
}

export function waterfallKindLabel(kind: string): string {
  if (kind === 'agent') return 'Agent';
  if (kind === 'tool') return '工具';
  return kind || 'step';
}

/** 把毫秒格式化为人类可读（1234ms → 1.23s）。 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}
