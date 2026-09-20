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
  expect(body).toContain("/careers");
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
  // The sitemap spreads one entry per open role. There need not be any —
  // careers/jobs.ts is empty while nothing is hiring — so a listed slug must
  // resolve, but an empty listing is the correct sitemap, not a failure. The
  // hard-404 on an unknown slug holds either way.
  const sitemap = await (await request.get("/sitemap.xml")).text();
  const slugUrl = sitemap.match(/<loc>([^<]*\/careers\/[^<]+)<\/loc>/)?.[1];
  if (slugUrl) {
    const known = await request.get(new URL(slugUrl).pathname);
    expect(known.status()).toBe(200);
  }

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
 * The actual SSR guard (#344 review #5, retargeted for the v5 landing).
 *
 * The assertions above were previously described as "the guard on not breaking
 * SSR", but they aren't: og:image / twitter:card / canonical are emitted by the
 * Metadata API whether or not any component server-renders.
 *
 * This test originally guarded `KnowledgeGraphDemo`, mounted through
 * `next/dynamic`, against someone reaching for `ssr: false` the moment a
 * hydration warning appeared — which would leave every other spec green while
 * silently dropping the section's copy out of the crawled HTML. The v5 landing
 * replaced that component, but the failure mode is unchanged and is in fact
 * sharper: the page is a client component whose visuals are canvas and WebGL,
 * so essentially all of its crawlable payload is the prose asserted below. Wrap
 * the page (or the hero) in a `ssr: false` dynamic import and this is the only
 * spec that notices.
 *
 * Assert on the RAW response body, before any JS runs. Note what is NOT
 * asserted: the wordmark and tagline are empty on the server because they
 * scramble in on the client, so `aria-label` on the h1 carries the accessible
 * name and is checked here in its place. The hero is main's with v5's lede
 * kept, so its crawlable text is the lede, the floating-card labels and the
 * CTA; the acts below carry the rest of the product claims.
 */
test("the landing page's copy is in the server-rendered HTML (#344)", async ({ request }) => {
  const res = await request.get("/");
  expect(res.status()).toBe(200);
  const html = await res.text();

  // the wordmark scrambles in client-side, so only its accessible name is server-rendered
  expect(html, "the wordmark's accessible name must survive SSR").toContain('aria-label="Sapling"');

  // the hero's own server-rendered text: the lede, the knowledge-state card and the CTA
  expect(html, "the lede is the page's primary SEO payload").toContain(
    "Sapling reads your whole course",
  );
  expect(html).toContain("Mastered");
  expect(html).toContain("Sign up for Beta Testing");

  // the acts below the hero state what the product does
  expect(html).toContain("Ingest");
  expect(html).toContain("Drop in the whole");
  expect(html).toContain("Ready to");
});
