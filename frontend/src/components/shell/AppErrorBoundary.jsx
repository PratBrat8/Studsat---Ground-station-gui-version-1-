import React, { Component } from 'react';

/**
 * Top-level error boundary — a panel crash must not blank the whole app (Phase 11).
 */
export default class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[AppErrorBoundary]', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="app-crash">
          <h1>Something went wrong</h1>
          <p className="muted">
            A UI error was caught so the rest of the ground station could stay
            up. Try switching tabs or reloading.
          </p>
          <pre className="app-crash-detail">
            {this.state.error?.message || String(this.state.error)}
          </pre>
          <button
            type="button"
            className="btn primary"
            onClick={() => {
              this.setState({ error: null });
              try {
                window.location.reload();
              } catch {
                /* ignore */
              }
            }}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
