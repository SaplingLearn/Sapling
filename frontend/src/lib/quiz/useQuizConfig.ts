"use client";

/**
 * `GET /api/quiz/config` — fetched once per page load and shared.
 *
 * The config endpoint is the single source of truth for the count and
 * difficulty option lists (#540 A2): the UI must never offer a value the route
 * would reject. It is unauthenticated, immutable for the life of a deploy and
 * tiny, so one in-flight promise is cached at module scope and every consumer
 * shares it. `resetQuizConfigCache` exists for tests.
 */

import { useEffect, useState } from "react";
import { fetchQuizConfig } from "./api";
import { describeQuizError, type QuizError } from "./errors";
import type { QuizConfig } from "./types";

let cached: Promise<QuizConfig> | null = null;

function load(): Promise<QuizConfig> {
  if (!cached) {
    cached = fetchQuizConfig().catch(err => {
      // Don't cache a failure — the next mount should be allowed to try again.
      cached = null;
      throw err;
    });
  }
  return cached;
}

export function resetQuizConfigCache(): void {
  cached = null;
}

export function useQuizConfig(): { config: QuizConfig | null; error: QuizError | null } {
  const [config, setConfig] = useState<QuizConfig | null>(null);
  const [error, setError] = useState<QuizError | null>(null);

  useEffect(() => {
    let cancelled = false;
    load().then(
      value => {
        if (!cancelled) setConfig(value);
      },
      err => {
        if (!cancelled) setError(describeQuizError(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  return { config, error };
}
