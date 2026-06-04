import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  migrateLegacyPortfolio,
  parseLegacyPositions,
  shouldMigrate,
  type LegacyPosition,
} from './portfolioMigration';
import { apiClient, type PortfolioSummaryPosition } from '../api/client';

function makeBackendPosition(ticker: string, shares: number): PortfolioSummaryPosition {
  return {
    ticker,
    shares,
    market_value: 0,
    cost_basis: 0,
  };
}

describe('parseLegacyPositions', () => {
  it('parses a valid {ticker: shares} dictionary', () => {
    const raw = JSON.stringify({ AAPL: 10, TSLA: 5 });
    expect(parseLegacyPositions(raw)).toEqual([
      { ticker: 'AAPL', shares: 10 },
      { ticker: 'TSLA', shares: 5 },
    ]);
  });

  it('uppercases tickers and drops invalid entries', () => {
    const raw = JSON.stringify({ aapl: 3, tsla: 0, '  ': 7, nvda: -2, msft: 'x' });
    expect(parseLegacyPositions(raw)).toEqual([{ ticker: 'AAPL', shares: 3 }]);
  });

  it('returns [] for null / empty / malformed JSON', () => {
    expect(parseLegacyPositions(null)).toEqual([]);
    expect(parseLegacyPositions('')).toEqual([]);
    expect(parseLegacyPositions('not-json')).toEqual([]);
    expect(parseLegacyPositions('[]')).toEqual([]);
    expect(parseLegacyPositions('"str"')).toEqual([]);
  });
});

describe('shouldMigrate', () => {
  const local: LegacyPosition[] = [{ ticker: 'AAPL', shares: 10 }];

  it('migrates when local has data and backend is empty', () => {
    expect(shouldMigrate(local, [])).toBe(true);
    expect(shouldMigrate(local, null)).toBe(true);
    expect(shouldMigrate(local, undefined)).toBe(true);
  });

  it('does NOT migrate when backend already has positions (never overwrite)', () => {
    expect(shouldMigrate(local, [makeBackendPosition('TSLA', 5)])).toBe(false);
  });

  it('does NOT migrate when local is empty', () => {
    expect(shouldMigrate([], [])).toBe(false);
    expect(shouldMigrate([], [makeBackendPosition('TSLA', 5)])).toBe(false);
  });
});

const LEGACY_KEY = 'finsight-portfolio-positions';

function makeSummary(positions: PortfolioSummaryPosition[]) {
  return {
    success: true,
    session_id: 'sess-1',
    positions,
    count: positions.length,
    total_value: 0,
    total_cost: 0,
    total_pnl: 0,
  };
}

/** 测试环境无 jsdom（node 默认）：用内存实现 stub window.localStorage。 */
function makeMemoryStorage() {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    setItem: (k: string, v: string) => void map.set(k, String(v)),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
  };
}

describe('migrateLegacyPortfolio (竞态安全：逐条 upsert + 二次校验)', () => {
  beforeEach(() => {
    vi.stubGlobal('window', { localStorage: makeMemoryStorage() });
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('后端为空 → 逐条 upsert 写入（不走全量 sync），清本地 key', async () => {
    window.localStorage.setItem(LEGACY_KEY, JSON.stringify({ AAPL: 10, TSLA: 5 }));
    // 两次查询都返回空（首查 + 写入前二次校验）
    const getSpy = vi
      .spyOn(apiClient, 'getPortfolioSummary')
      .mockResolvedValue(makeSummary([]));
    const upsertSpy = vi
      .spyOn(apiClient, 'updatePortfolioPosition')
      .mockResolvedValue({ success: true, session_id: 'sess-1' });
    const syncSpy = vi.spyOn(apiClient, 'syncPortfolioPositions');

    const result = await migrateLegacyPortfolio('sess-1');

    expect(result).toEqual({ migrated: 2 });
    expect(syncSpy).not.toHaveBeenCalled(); // 不再用全量 DELETE+INSERT
    expect(upsertSpy).toHaveBeenCalledTimes(2); // 逐条 upsert
    expect(upsertSpy).toHaveBeenCalledWith('sess-1', 'AAPL', 10);
    expect(upsertSpy).toHaveBeenCalledWith('sess-1', 'TSLA', 5);
    expect(getSpy).toHaveBeenCalledTimes(2); // 首查 + 写入前二次校验
    expect(window.localStorage.getItem(LEGACY_KEY)).toBeNull();
  });

  it('二次校验发现后端已被录入 → 放弃写入（不冲掉用户新数据），清本地 key', async () => {
    window.localStorage.setItem(LEGACY_KEY, JSON.stringify({ AAPL: 10 }));
    // 首查为空 → 决定迁移；二次校验时后端已有用户录入 → 放弃
    const getSpy = vi
      .spyOn(apiClient, 'getPortfolioSummary')
      .mockResolvedValueOnce(makeSummary([]))
      .mockResolvedValueOnce(makeSummary([makeBackendPosition('NVDA', 3)]));
    const upsertSpy = vi
      .spyOn(apiClient, 'updatePortfolioPosition')
      .mockResolvedValue({ success: true, session_id: 'sess-1' });

    const result = await migrateLegacyPortfolio('sess-1');

    expect(result).toBeNull();
    expect(upsertSpy).not.toHaveBeenCalled(); // 竞态保护：一条都不写
    expect(getSpy).toHaveBeenCalledTimes(2);
    expect(window.localStorage.getItem(LEGACY_KEY)).toBeNull(); // 后端为准，丢弃本地旧数据
  });

  it('upsert 失败 → 保留本地 key 供下次重试', async () => {
    window.localStorage.setItem(LEGACY_KEY, JSON.stringify({ AAPL: 10 }));
    vi.spyOn(apiClient, 'getPortfolioSummary').mockResolvedValue(makeSummary([]));
    vi.spyOn(apiClient, 'updatePortfolioPosition').mockRejectedValue(new Error('boom'));

    const result = await migrateLegacyPortfolio('sess-1');

    expect(result).toBeNull();
    expect(window.localStorage.getItem(LEGACY_KEY)).not.toBeNull(); // 保留以便重试
  });
});
