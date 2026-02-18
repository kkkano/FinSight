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

export interface TimelineEvent {
  id: string;
  timestamp: string;
  eventType: string;
  stage: string;
  message?: string;
  runId?: string;
  sessionId?: string;
  stepId?: string;
  kind?: string;
  name?: string;
  agent?: string;
  tool?: string;
  durationMs?: number;
  cached?: boolean;
  skipped?: boolean;
  status?: string;
  parallelGroup?: string | null;
  raw?: Record<string, unknown>;
}

// --- Execution run status ---

export type ExecutionRunStatus = 'running' | 'done' | 'error' | 'cancelled' | 'interrupted';
export type AnalysisDepth = 'quick' | 'report' | 'deep_research';
export type AgentPreferenceDepth = 'standard' | 'deep' | 'off';

export interface ToolCapability {
  name: string;
  group: string;
  markets: string[];
  operations: string[];
  depths: string[];
  riskLevel: string;
  selected: boolean;
  envReady: boolean;
  missingEnv: string[];
}

export interface AnalysisConfig {
  analysisDepth: AnalysisDepth;
  budget: number;
  agentDepths: Record<string, AgentPreferenceDepth>;
  concurrentMode: boolean;
}

export interface ExecutionRun {
  runId: string;
  query: string;
  tickers: string[];
  source: string;
  /** Output mode used for this run (brief / investment_report / chat). */
  outputMode: string;
  /** Explicit analysis depth semantics for planner/policy. */
  analysisDepth?: AnalysisDepth;
  status: ExecutionRunStatus;
  agentStatuses: Record<string, AgentRunInfo>;
  /** 0–100, monotonically increasing (never decreases). */
  progress: number;
  currentStep: string | null;
  timeline: TimelineEvent[];
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
  /** Interrupt data when status is 'interrupted' (human-in-the-loop). */
  interruptData?: {
    thread_id: string;
    prompt?: string;
    options?: string[];
    plan_summary?: string;
    required_agents?: string[];
  } | null;
}

// --- Start execution parameters (camelCase) ---

export interface StartExecutionParams {
  query: string;
  tickers?: string[];
  /** Maps to API `output_mode` at request time. */
  outputMode?: string;
  /** Explicit depth semantics to avoid query-text coupling. */
  analysisDepth?: AnalysisDepth;
  agents?: string[];
  source: string;
  budget?: number;
  agentPreferencesOverride?: {
    agents?: Record<string, AgentPreferenceDepth>;
    maxRounds?: number;
    concurrentMode?: boolean;
  };
}
