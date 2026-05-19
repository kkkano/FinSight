/**
 * Global Error Boundary — prevents white-screen crashes.
 *
 * Catches any unhandled React render error and displays a recoverable
 * fallback UI instead of an empty page.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Optional custom fallback; receives the caught error. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

interface RecoverableErrorFallbackProps {
  error: Error;
  onRetry: () => void;
  onReload?: () => void;
  onHome?: () => void;
}

export function RecoverableErrorFallback({
  error,
  onRetry,
  onReload = () => window.location.reload(),
  onHome = () => {
    window.location.href = '/welcome';
  },
}: RecoverableErrorFallbackProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-fin-bg px-4 text-center text-fin-text">
      <div className="w-full max-w-lg rounded-xl border border-fin-border bg-fin-card p-6 shadow-lg">
        <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full border border-fin-warning/40 bg-fin-warning/10 text-xl text-fin-warning">
          !
        </div>
        <h1 className="text-xl font-semibold">加载失败</h1>
        <p className="mt-2 text-sm leading-6 text-fin-muted">
          页面没有拿到必要数据。请检查网络、后端服务或本地配置，然后重试。
        </p>
        <pre className="mt-4 max-h-32 overflow-auto rounded-lg border border-fin-border bg-fin-bg-secondary p-3 text-left text-xs text-fin-danger">
          {error.message}
        </pre>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 rounded-lg bg-fin-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-fin-primary/90"
          >
            重试
          </button>
          <button
            type="button"
            onClick={onReload}
            className="min-h-11 rounded-lg border border-fin-border px-4 py-2 text-sm font-medium text-fin-text transition-colors hover:bg-fin-hover"
          >
            刷新页面
          </button>
          <button
            type="button"
            onClick={onHome}
            className="min-h-11 rounded-lg border border-fin-border px-4 py-2 text-sm font-medium text-fin-text transition-colors hover:bg-fin-hover"
          >
            返回欢迎页
          </button>
        </div>
      </div>
    </div>
  );
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Best-effort logging — never rethrow
    try {
      console.error('[ErrorBoundary] Uncaught render error:', error, info.componentStack); // eslint-disable-line no-console
    } catch {
      // ignore
    }
  }

  private handleReset = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) {
      return this.props.fallback(error, this.handleReset);
    }

    return <RecoverableErrorFallback error={error} onRetry={this.handleReset} />;
  }
}
