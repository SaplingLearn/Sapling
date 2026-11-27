/**
 * Non-waiting reads of the learning loop's check-in, for `expect.poll`
 * predicates. A locator's `getAttribute` WAITS for its element, so a predicate
 * that reads the shown item just as the check-in hands over to the plan (the
 * item leaves the page between the phase read and the item read) hangs until
 * the poll times out — though the change the poll waits for has happened.
 * These read the page once and return at once.
 */
import type { Locator } from "@playwright/test";

/** Whether the page shows a check-in item other than `qh` (an item that has
 *  just left the page counts as "no", so the poll keeps polling). */
export async function showsAnotherItem(item: Locator, qh: string | null): Promise<boolean> {
  const now = await item.evaluateAll((els) => els[0]?.getAttribute("data-question-hash") ?? null);
  return now !== null && now !== qh;
}
