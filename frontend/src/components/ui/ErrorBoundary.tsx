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

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Best-effort logging — never rethrow
    try {
      // eslint-disable-next-line no-console
      console.error('[ErrorBoundary] Uncaught render error:', error, info.componentStack);
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

    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-fin-bg px-4 text-center">
        <div className="max-w-md space-y-4">
          <div className="text-4xl">⚠️</div>
          <h1 className="text-xl font-semibold text-fin-text">
            页面出了点问题
          </h1>
          <p className="text-sm text-fin-text-secondary">
            应用遇到了一个意外错误。您可以尝试重新加载页面。
          </p>
          <pre className="text-xs text-left bg-fin-bg-secondary text-fin-danger p-3 rounded-lg overflow-auto max-h-32">
            {error.message}
          </pre>
          <div className="flex items-center justify-center gap-3 pt-2">
            <button
              type="button"
              onClick={this.handleReset}
              className="px-4 py-2 rounded-lg bg-fin-primary text-white text-sm font-medium hover:bg-fin-primary/90 transition-colors"
            >
              重试
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg border border-fin-border text-fin-text text-sm font-medium hover:bg-fin-hover transition-colors"
            >
              刷新页面
            </button>
          </div>
        </div>
      </div>
    );
  }
}
