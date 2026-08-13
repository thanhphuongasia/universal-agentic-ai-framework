import { Component, type ReactNode, type ErrorInfo } from "react";

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(_error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", _error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex items-center justify-center h-full p-8">
          <div className="max-w-md w-full rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950 p-6 text-center space-y-3">
            <div className="text-2xl">⚠️</div>
            <h2 className="font-semibold text-red-800 dark:text-red-300">Something went wrong</h2>
            <p className="text-sm text-red-600 dark:text-red-400 font-mono break-words">
              {this.state.error.message}
            </p>
            <button
              onClick={() => this.setState({ error: null })}
              className="text-sm text-red-700 dark:text-red-300 underline hover:no-underline"
            >
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
