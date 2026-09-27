/**
 * Next.js client instrumentation hook (Next 15.3+): runs once in the browser
 * before the app hydrates. Product analytics starts here — and only when the
 * build is configured for it; see src/lib/analytics.ts for the gate (no key,
 * local mode and the E2E/test build are all inert) and the privacy config.
 */
import { initAnalytics } from "@/lib/analytics";

void initAnalytics();
