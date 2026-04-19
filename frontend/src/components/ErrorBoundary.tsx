"use client";

import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: (error: Error, reset: () => void) => React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    if (process.env.NODE_ENV !== "production") {
      console.error("[ErrorBoundary]", error, info);
    }
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback(this.state.error, this.reset);
      return <ErrorFallback error={this.state.error} reset={this.reset} />;
    }
    return this.props.children;
  }
}

export function ErrorFallback({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "var(--pad-xl)",
        background: "var(--bg)",
      }}
    >
      <div
        className="card"
        style={{
          maxWidth: 440,
          width: "100%",
          padding: "var(--pad-xl)",
          textAlign: "center",
        }}
      >
        <div className="label-micro" style={{ marginBottom: 8 }}>Something went wrong</div>
        <div className="h-serif" style={{ fontSize: 24, marginBottom: 10 }}>An unexpected error occurred</div>
        <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 20, wordBreak: "break-word" }}>
          {error.message || "Unknown error"}
        </div>
        <button className="btn btn--primary" onClick={reset} style={{ justifyContent: "center", width: "100%" }}>
          Try again
        </button>
      </div>
    </div>
  );
}
