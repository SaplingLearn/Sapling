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
import { applyAccountAnalytics, beginAccountRead, failAccountRead } from "./analytics";
import type { UserSettings } from "./types";

const inFlight = new Map<string, Promise<UserSettings>>();

export function readAccountSettings(userId: string): Promise<UserSettings> {
  const pending = inFlight.get(userId);
  if (pending) return pending;
  const gen = beginAccountRead(userId);
  const request = fetchSettings(userId)
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
      inFlight.delete(userId);
    });
  inFlight.set(userId, request);
  return request;
}

/** Test-only: forget in-flight requests. */
export function __resetAccountSettingsForTests(): void {
  inFlight.clear();
}
