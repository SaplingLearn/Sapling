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
  const msg = (error.message || "").toLowerCase();
  // Honest, calibrated copy rather than "Something went wrong." Parse
  // what we can from the error shape and phrase it like a study partner
  // would — calm, specific, not alarmed.
  const { headline, subtext } = (() => {
    if (msg.includes("network") || msg.includes("fetch")) {
      return { headline: "We can't reach the server right now", subtext: "Usually this is a flaky network. Try again in a moment — your work is saved." };
    }
    if (msg.includes("timeout") || msg.includes("aborted")) {
      return { headline: "That request took too long", subtext: "The server is probably under load. Try again in a few seconds." };
    }
    if (msg.includes("401") || msg.includes("unauth") || msg.includes("session")) {
      return { headline: "Your session expired", subtext: "Head back to sign in and we'll pick up where you left off." };
    }
    return { headline: "We hit a snag", subtext: "This is on us. Your progress is saved — try again, and if it keeps happening, let us know below." };
  })();

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
        style={{
          maxWidth: 480, width: "100%",
          padding: "var(--pad-xl) 12px", textAlign: "center",
        }}
      >
        <div className="label-micro" style={{ marginBottom: 12 }}>Something interrupted us</div>
        <div className="h-serif" style={{ fontSize: 28, marginBottom: 12, lineHeight: 1.2 }}>{headline}</div>
        <div className="body-serif" style={{ fontSize: 15, color: "var(--text-dim)", marginBottom: 18, lineHeight: 1.6 }}>
          {subtext}
        </div>
        {error.message && (
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 20, wordBreak: "break-word", fontFamily: "var(--font-mono)" }}>
            {error.message}
          </div>
        )}
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button className="btn btn--primary" onClick={reset}>Try again</button>
          {typeof window !== "undefined" && (
            <a
              className="btn"
              href={`mailto:saplinglearn@gmail.com?subject=${encodeURIComponent("Sapling error report")}&body=${encodeURIComponent(`I hit this error while using Sapling:\n\n${error.message || "Unknown"}\n\n(Stack trace below — you can delete if you don't want to share.)\n\n${error.stack || ""}`)}`}
            >
              Report this
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
