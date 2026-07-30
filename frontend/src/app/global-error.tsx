"use client";

import { ErrorFallback } from "@/components/ErrorBoundary";
// global-error replaces the root layout entirely, so the token stylesheet the
// layout imports is not guaranteed to be present — import it here too or the
// fallback renders unstyled var() soup.
import "./globals.css";

// Catches errors thrown by the root layout and the providers it mounts
// (ErrorBoundary/ToastProvider/UserProvider init), which the segment-level
// error.tsx cannot see (#172). Must render its own <html>/<body>.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en" data-accent="sage" data-density="compact">
      <body>
        <ErrorFallback error={error} reset={reset} />
      </body>
    </html>
  );
}
