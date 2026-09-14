export type PredictionDirection = 'long' | 'short' | 'neutral';

export type PredictionStatus =
  | 'waiting'
  | 'open'
  | 'triggered'
  | 'invalidated'
  | 'hit_target'
  | 'hit_stop'
  | 'held_range'
  | 'broke_range';

export interface PredictionRange {
  low: number;
  high: number;
}

export interface PredictionZone extends PredictionRange {
  label: string;
}

/** AI 只能提交标注合同；任何 bars/series/data 等行情数组都会在解析时被丢弃。 */
export interface PredictionOverlay {
  predictionId: string;
  symbol: string;
  direction: PredictionDirection;
  anchor: {
    timeframe: string;
    time: string;
    price: number;
  };
  entry?: number;
  stop?: number;
  target1?: number;
  target2?: number;
  range?: PredictionRange;
  zones?: PredictionZone[];
  status: PredictionStatus;
}

const DIRECTIONS = new Set<PredictionDirection>(['long', 'short', 'neutral']);
const STATUSES = new Set<PredictionStatus>([
  'waiting',
  'open',
  'triggered',
  'invalidated',
  'hit_target',
  'hit_stop',
  'held_range',
  'broke_range',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readFiniteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function readRange(value: unknown): PredictionRange | undefined {
  if (!isRecord(value)) return undefined;
  const low = readFiniteNumber(value.low);
  const high = readFiniteNumber(value.high);
  if (low === undefined || high === undefined || low > high) return undefined;
  return { low, high };
}

/**
 * 对受鉴权 API 的响应再做客户端白名单解析。
 * 兼容后端直接返回 prediction，或包在 `{ prediction }` 中；其余字段一律不进入图表。
 */
export function normalizePredictionOverlay(
  value: unknown,
  expectedSymbol?: string,
): PredictionOverlay | null {
  const envelope = isRecord(value) && isRecord(value.prediction) ? value.prediction : value;
  if (!isRecord(envelope) || !isRecord(envelope.anchor)) return null;

  const predictionId = String(envelope.predictionId ?? envelope.prediction_id ?? '').trim();
  const symbol = String(envelope.symbol ?? '').trim().toUpperCase();
  const direction = envelope.direction;
  const status = envelope.status;
  const timeframe = String(envelope.anchor.timeframe ?? '').trim();
  const time = String(envelope.anchor.time ?? '').trim();
  const price = readFiniteNumber(envelope.anchor.price);

  if (
    !predictionId
    || !symbol
    || (expectedSymbol && symbol !== expectedSymbol.trim().toUpperCase())
    || !DIRECTIONS.has(direction as PredictionDirection)
    || !STATUSES.has(status as PredictionStatus)
    || !timeframe
    || !time
    || price === undefined
  ) {
    return null;
  }

  const zones = Array.isArray(envelope.zones)
    ? envelope.zones.flatMap((zone): PredictionZone[] => {
        const range = readRange(zone);
        if (!range || !isRecord(zone)) return [];
        const label = String(zone.label ?? '').trim();
        return label ? [{ ...range, label }] : [];
      })
    : undefined;

  const result: PredictionOverlay = {
    predictionId,
    symbol,
    direction: direction as PredictionDirection,
    anchor: { timeframe, time, price },
    status: status as PredictionStatus,
  };

  for (const key of ['entry', 'stop', 'target1', 'target2'] as const) {
    const parsed = readFiniteNumber(envelope[key]);
    if (parsed !== undefined) result[key] = parsed;
  }

  const range = readRange(envelope.range);
  if (range) result.range = range;
  if (zones?.length) result.zones = zones;
  return result;
}

export type PredictionLoadResult =
  | { status: 'ready'; overlay: PredictionOverlay }
  | { status: 'unavailable'; overlay: null };

/** 404、越权、网络失败或非法响应都只关闭 AI 层，不影响真实行情。 */
export async function loadPredictionOverlay(
  predictionId: string,
  expectedSymbol: string | undefined,
  loader: (id: string) => Promise<unknown>,
): Promise<PredictionLoadResult> {
  try {
    const overlay = normalizePredictionOverlay(
      await loader(predictionId),
      expectedSymbol,
    );
    return overlay
      ? { status: 'ready', overlay }
      : { status: 'unavailable', overlay: null };
  } catch {
    return { status: 'unavailable', overlay: null };
  }
}
