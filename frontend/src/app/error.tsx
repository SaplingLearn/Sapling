"use client";

import { ErrorFallback } from "@/components/ErrorBoundary";

// Root SEGMENT boundary: catches errors from child segments only. Errors in
// app/layout.tsx itself (fonts, providers) are caught by global-error.tsx.
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <ErrorFallback error={error} reset={reset} />;
}
