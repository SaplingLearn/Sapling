/**
 * `GET /api/profile/{id}/settings`, shared between the UserProvider (which
 * reads it for product analytics) and the Settings screen (which reads it for
 * everything), so the two can never disagree about `analytics_opt_out` and
 * never send two identical requests at once:
 *
 * - concurrent callers for the same student get the SAME in-flight request
 *   (on /settings, the UserProvider's read and Settings' own are one GET);
 * - every answer — whoever asked — feeds the analytics account state
 *   (lib/analytics.ts applyAccountAnalytics / failAccountRead), under the
 *   generation guard there, so a read overtaken by a Settings toggle or a
 *   sign-out is ignored.
 *
 * Nothing is cached once a request settles: the next call is a fresh GET.
 */
import { fetchSettings } from "./api";
import {
  applyAccountAnalytics,
  beginAccountRead,
  failAccountRead,
  isCurrentAccountRead,
} from "./analytics";
import type { UserSettings } from "./types";

/** One in-flight GET per student, with the generation it was issued under. */
const inFlight = new Map<string, { gen: number; request: Promise<UserSettings> }>();

export function readAccountSettings(userId: string): Promise<UserSettings> {
  const pending = inFlight.get(userId);
  // Share a pending GET only while its answer would still be APPLIED: one
  // issued before a sign-out → sign-in (or a toggle) is stale, so a caller
  // reusing it would wait for an answer analytics.ts throws away and the
  // switch would stay on "Loading…". Issue a fresh read instead.
  if (pending && isCurrentAccountRead(pending.gen, userId)) return pending.request;
  const gen = beginAccountRead(userId);
  const request: Promise<UserSettings> = fetchSettings(userId)
    .then(
      (settings) => {
        applyAccountAnalytics(gen, userId, settings.analytics_opt_out);
        return settings;
      },
      (err: unknown) => {
        failAccountRead(gen, userId);
        throw err;
      },
    )
    .finally(() => {
      // Only our own entry: a newer read may have replaced it meanwhile.
      if (inFlight.get(userId)?.request === request) inFlight.delete(userId);
    });
  inFlight.set(userId, { gen, request });
  return request;
}

/** Test-only: forget in-flight requests. */
export function __resetAccountSettingsForTests(): void {
  inFlight.clear();
}
