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
      data-testid="error-fallback"
      className="min-h-screen flex items-center justify-center p-(--pad-xl) bg-bg"
    >
      <div
        className="max-w-120 w-full py-(--pad-xl) px-3 text-center"
      >
        <div className="label-micro mb-3">Something interrupted us</div>
        <div className="h-serif text-[28px] mb-3 leading-[1.2]">{headline}</div>
        <div className="body-serif text-[15px] text-text-dim mb-4.5 leading-[1.6]">
          {subtext}
        </div>
        {error.message && (
          <div className="text-xs text-text-muted mb-5 [word-break:break-word] font-code">
            {error.message}
          </div>
        )}
        <div className="flex gap-2.5 justify-center">
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
