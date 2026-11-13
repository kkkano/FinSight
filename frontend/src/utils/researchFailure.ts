import { zh } from '../locales/zh';

export interface ResearchFailurePresentation {
  code: string;
  message: string;
  action: string;
  retryable: boolean;
  diagnostic: string;
}

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): string => typeof value === 'string' ? value : '';

/** 只读取协议中的错误码与 HTTP 状态；不从错误原文猜测原因。 */
export function researchFailure(input?: unknown, fallback: string = zh.errors.unknown.message): ResearchFailurePresentation {
  const value = record(input);
  const response = record(value.response);
  const data = record(response.data);
  const detail = record(data.detail);
  const code = text(value.error_code) || text(detail.error_code) || text(detail.code) || text(data.error_code)
    || text(value.code) || (Object.hasOwn(zh.errors, text(value.reason)) ? text(value.reason) : '')
    || (Object.hasOwn(zh.errors, text(value.name)) ? text(value.name) : '');
  const status = typeof value.status === 'number' ? value.status : response.status;
  const httpCode = /^model_http_(\d{3})$/.exec(code)?.[1];
  const statusCode = httpCode ? Number(httpCode) : status;
  const key = Object.hasOwn(zh.errors, code) ? code
    : httpCode ? 'model_request_failed'
      : statusCode === 401 ? 'auth_required' : statusCode === 429 ? 'CapacityExceeded' : 'unknown';
  const presentation = zh.errors[key as keyof typeof zh.errors];
  const diagnostic = [code, text(value.reason), text(value.failure_detail), text(value.error), text(value.message),
    text(data.detail), text(detail.message), text(detail.reason)].filter(Boolean).join('\n');
  return { code: code || key, ...presentation, message: key === 'unknown' ? fallback : presentation.message, diagnostic };
}

export function researchFailureMessage(input?: unknown, fallback?: string): string {
  const failure = researchFailure(input, fallback);
  return [failure.message, failure.action].filter(Boolean).join(' ');
}
