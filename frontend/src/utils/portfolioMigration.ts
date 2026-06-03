/**
 * portfolioMigration.ts —— 旧版 localStorage 持仓 → 后端一次性迁移
 *
 * 背景：历史上持仓存在 localStorage `finsight-portfolio-positions`（{ticker: shares} 字典），
 * 现已统一到后端 portfolio.db。本工具负责把老用户残留的本地持仓搬到后端，
 * 然后彻底删除本地 key，告别双真相源。
 *
 * 安全原则（绝不覆盖后端已有数据）：
 *   - 仅当「本地有数据」且「后端持仓为空」时才迁移
 *   - 后端非空 → 直接清除本地（后端为准，旧数据丢弃，避免脏数据复活）
 */
import { apiClient, type PortfolioSummaryPosition } from '../api/client';

const LEGACY_KEY = 'finsight-portfolio-positions';

/** 标准化后的本地持仓项 */
export interface LegacyPosition {
  ticker: string;
  shares: number;
}

/**
 * 从原始 localStorage 字典解析出有效持仓项。
 * 过滤无效项：空 ticker / 非正数 shares。
 */
export function parseLegacyPositions(raw: string | null): LegacyPosition[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!parsed || typeof parsed !== 'object') return [];

  return Object.entries(parsed as Record<string, unknown>).reduce<LegacyPosition[]>(
    (acc, [ticker, shares]) => {
      const normalized = String(ticker || '').trim().toUpperCase();
      const value = Number(shares);
      if (normalized && Number.isFinite(value) && value > 0) {
        acc.push({ ticker: normalized, shares: value });
      }
      return acc;
    },
    [],
  );
}

/**
 * 判断是否应执行迁移（纯函数，便于单测）。
 * 仅当：本地有有效持仓 且 后端持仓为空 时返回 true。
 */
export function shouldMigrate(
  localData: LegacyPosition[],
  backendPositions: PortfolioSummaryPosition[] | null | undefined,
): boolean {
  if (!localData.length) return false;
  const backendCount = Array.isArray(backendPositions) ? backendPositions.length : 0;
  return backendCount === 0;
}

/** 清除本地旧 key（彻底告别旧真相源） */
function clearLegacyKey(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(LEGACY_KEY);
}

/**
 * 执行一次性迁移。
 * @returns 迁移成功时返回 {migrated: 数量}；无需迁移或已清除时返回 null。
 */
export async function migrateLegacyPortfolio(
  sessionId: string,
): Promise<{ migrated: number } | null> {
  if (typeof window === 'undefined') return null;
  const sid = String(sessionId || '').trim();
  if (!sid) return null;

  const localData = parseLegacyPositions(window.localStorage.getItem(LEGACY_KEY));
  if (!localData.length) {
    // 本地没有遗留数据：顺手清掉空 key（若存在）后结束
    clearLegacyKey();
    return null;
  }

  // 查询后端当前持仓，决定是否迁移
  let backendPositions: PortfolioSummaryPosition[] = [];
  try {
    const summary = await apiClient.getPortfolioSummary(sid);
    backendPositions = Array.isArray(summary?.positions) ? summary.positions : [];
  } catch (error) {
    // 后端查询失败：保留本地数据，下次挂载再试（不清除、不迁移）
    console.error('迁移前查询后端持仓失败，跳过本次迁移:', error);
    return null;
  }

  if (!shouldMigrate(localData, backendPositions)) {
    // 后端已有数据 → 后端为准，丢弃本地旧数据避免脏数据复活
    clearLegacyKey();
    return null;
  }

  // 后端为空 + 本地有数据 → 全量写入后端（迁移是唯一允许用 sync 全量替换的场景）
  try {
    await apiClient.syncPortfolioPositions(
      sid,
      localData.map((item) => ({ ticker: item.ticker, shares: item.shares })),
    );
  } catch (error) {
    // 写入失败：保留本地数据，下次再试
    console.error('迁移本地持仓到后端失败:', error);
    return null;
  }

  // 迁移成功，删除本地 key
  clearLegacyKey();
  return { migrated: localData.length };
}
