/**
 * Shared type-narrowing utility for safely casting unknown values to records.
 *
 * Used across multiple dashboard components (OverviewTab, FearGreedGauge,
 * RiskMetricsCard, AgentStatusOverview, ConflictPanel) to safely access
 * nested report data without repeated inline type guards.
 */

/** Narrow an unknown value to a string-keyed record, or return null. */
export const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
