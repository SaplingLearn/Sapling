/**
 * Shared recipe helpers. All mocks match on URL substrings of the BACKEND API
 * (the frontend calls same-origin /api/*, proxied to the backend).
 */
import { expect, type Page, type Route } from "@playwright/test";

export const NODE_RECURSION = "rich-node-cs-recursion";
export const COURSE_CS101 = "rich-course-cs101";
export const SESSION_RECURSION = "rich-sess-cs-recursion";

function matcher(pattern: string | RegExp) {
  return (url: URL) =>
    typeof pattern === "string" ? url.pathname.includes(pattern) : pattern.test(url.pathname + url.search);
}

/** Respond to matching requests with a fixed JSON body/status. */
export async function mockJson(
  page: Page,
  pattern: string | RegExp,
  body: unknown,
  opts: { status?: number; method?: string } = {},
): Promise<void> {
  await page.route(matcher(pattern), async (route: Route) => {
    if (opts.method && route.request().method() !== opts.method) return route.fallback();
    await route.fulfill({
      status: opts.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

/** Make matching requests fail with an HTTP error. */
export async function mockError(
  page: Page,
  pattern: string | RegExp,
  status = 500,
  detail = "Internal Server Error",
  method?: string,
): Promise<void> {
  await mockJson(page, pattern, { detail }, { status, method });
}

/** Never answer matching requests → the UI stays in its loading state. */
export async function hold(page: Page, pattern: string | RegExp, method?: string): Promise<void> {
  await page.route(matcher(pattern), async (route: Route) => {
    if (method && route.request().method() !== method) return route.fallback();
    // intentionally never fulfilled
  });
}

/** Set localStorage keys before any page script runs. */
export async function storage(page: Page, kv: Record<string, string>): Promise<void> {
  await page.addInitScript((entries) => {
    for (const [k, v] of Object.entries(entries)) window.localStorage.setItem(k, v);
  }, kv);
}

export async function visible(page: Page, testId: string, timeout = 30_000): Promise<void> {
  await expect(page.getByTestId(testId).first()).toBeVisible({ timeout });
}

export async function text(page: Page, t: string | RegExp, timeout = 30_000): Promise<void> {
  await expect(page.getByText(t).first()).toBeVisible({ timeout });
}
