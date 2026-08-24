import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('ErrorBoundary caught:', error, info);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    const { children, fallback } = this.props;
    if (!error) return children;
    if (fallback) return fallback(error, this.reset);
    return (
      <div className="rounded border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
        <p className="font-semibold">Ошибка рендера компонента</p>
        <pre className="mt-2 whitespace-pre-wrap text-xs">{error.message}</pre>
        <button
          type="button"
          onClick={this.reset}
          className="mt-3 rounded border border-danger px-2 py-1 text-xs hover:bg-danger/20"
        >
          Попробовать снова
        </button>
      </div>
    );
  }
}