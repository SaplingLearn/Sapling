/**
 * Public SEO surface (#169 #170 #187): the App Router special files resolve
 * and the careers slug page hard-404s. Pure HTTP asserts against the built
 * frontend — no auth, no DB dependence beyond the fixture baseline.
 */
import { expect, test } from "./support/fixtures";

test("robots.txt allows the public surface and points at the sitemap", async ({ request }) => {
  const res = await request.get("/robots.txt");
  expect(res.status()).toBe(200);
  const body = await res.text();
  expect(body).toContain("Sitemap:");
  expect(body).toContain("Disallow: /dashboard");
  expect(body).toContain("Disallow: /api/");
});

test("sitemap.xml enumerates the public routes and nothing private", async ({ request }) => {
  const res = await request.get("/sitemap.xml");
  expect(res.status()).toBe(200);
  const body = await res.text();
  expect(body).toContain("/about");
  expect(body).toContain("/careers/");
  expect(body).not.toContain("/dashboard");
});

test("manifest.webmanifest carries the brand identity", async ({ request }) => {
  const res = await request.get("/manifest.webmanifest");
  expect(res.status()).toBe(200);
  const manifest = await res.json();
  expect(manifest.name).toContain("Sapling");
  expect(manifest.theme_color).toBe("#1B6C42");
});

test("careers slugs from the sitemap resolve; unknown slugs hard-404 (#187)", async ({
  request,
}) => {
  const sitemap = await (await request.get("/sitemap.xml")).text();
  const slugUrl = sitemap.match(/<loc>([^<]*\/careers\/[^<]+)<\/loc>/)?.[1];
  expect(slugUrl, "sitemap should list at least one job slug").toBeTruthy();
  const slugPath = new URL(slugUrl!).pathname;

  const known = await request.get(slugPath);
  expect(known.status()).toBe(200);

  const unknown = await request.get("/careers/definitely-not-a-job");
  expect(unknown.status()).toBe(404);
});

test("landing page ships social cards and a canonical URL (#169)", async ({ request }) => {
  const res = await request.get("/");
  expect(res.status()).toBe(200);
  const html = await res.text();
  expect(html).toContain('property="og:image"');
  expect(html).toContain("/og.png");
  expect(html).toContain('name="twitter:card"');
  expect(html).toContain('rel="canonical"');
});

/**
 * The actual SSR guard (#344 review #5).
 *
 * The assertions above were previously described as "the guard on not breaking
 * SSR", but they aren't: og:image / twitter:card / canonical are emitted by the
 * Metadata API whether or not any component server-renders. The landing page
 * mounts `KnowledgeGraphDemo` through `next/dynamic` with SSR left ON, and
 * `ssr: false` is the first thing anyone will reach for the moment a hydration
 * warning appears there — it would leave every other spec green while silently
 * dropping the section's copy out of the crawled HTML, which is the entire
 * reason that component carries the `usePrefersReducedMotion` machinery.
 * `landing-graph.spec.ts` runs post-hydration and cannot see the difference.
 *
 * So assert on the RAW response body, before any JS runs. With `ssr: false`
 * the dynamic import renders only its loading placeholder (an empty
 * `<section id="knowledge-graph">`), and every assertion below fails.
 */
test("the knowledge-graph section is in the server-rendered HTML (#344)", async ({ request }) => {
  const res = await request.get("/");
  expect(res.status()).toBe(200);
  const html = await res.text();

  expect(html, "graph section markup must be server-rendered").toContain(
    'data-testid="landing-graph"',
  );
  expect(html, "the section's copy must be crawlable").toContain(
    "Pick a course. Watch it grow.",
  );
  // Concept labels are the section's actual SEO payload.
  expect(html).toContain('data-testid="landing-graph-node-cs-root"');
  expect(html).toContain("Recursion");
});
