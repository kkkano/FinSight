/**
 * Execution types — global execution state for agent runs.
 *
 * Frontend uses camelCase naming. The store layer handles
 * mapping to snake_case when constructing API requests.
 */
import type { ReportIR } from './index';

// --- Agent run status within a single execution ---

export type AgentRunStatus = 'pending' | 'running' | 'done' | 'error' | 'skipped';

export interface AgentRunInfo {
  name: string;
  status: AgentRunStatus;
  startedAt?: string;
  completedAt?: string;
  error?: string;
  fallbackReason?: string;
  retryable?: boolean;
}

// --- Execution run status ---

export type ExecutionRunStatus = 'running' | 'done' | 'error' | 'cancelled';

export interface ExecutionRun {
  runId: string;
  query: string;
  tickers: string[];
  source: string;
  /** Output mode used for this run (brief / investment_report / chat). */
  outputMode: string;
  status: ExecutionRunStatus;
  agentStatuses: Record<string, AgentRunInfo>;
  /** 0–100, monotonically increasing (never decreases). */
  progress: number;
  currentStep: string | null;
  report: ReportIR | null;
  streamedContent: string;
  fallbackReasons: string[];
  error: string | null;
  startedAt: string;
  completedAt: string | null;
  /** Null after run completes/cancels. */
  abortController: AbortController | null;
  /** Set of runIds that have been bridged to chat (prevent duplicate). */
  bridgedToChat?: boolean;
}

// --- Start execution parameters (camelCase) ---

export interface StartExecutionParams {
  query: string;
  tickers?: string[];
  /** Maps to API `output_mode` at request time. */
  outputMode?: string;
  agents?: string[];
  source: string;
  budget?: number;
}
