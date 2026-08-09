/**
 * The landing page's draggable course clusters must read as part of the page.
 *
 * Promoted from a real regression: the clusters were a layer floating over the
 * site rather than in it. Three symptoms, all pinned here because unit tests
 * in jsdom can only assert the geometry the fixture itself supplies — whether
 * a real browser's layout, sticky positioning and compositor agree is only
 * answerable here.
 *
 *   1. a cluster inside a pinned act drifted up to 150px against the scroll;
 *   2. the sim kept integrating while the page scrolled, so every node
 *      wandered 20-50px of its own accord under a moving page;
 *   3. nodes were clamped to their svg's viewBox, walling the drag ~900px
 *      sideways and ~1600px up/down of the cluster's home.
 *
 * Public surface: no auth, no DB. `test` comes from @playwright/test rather
 * than support/fixtures precisely because there is no row to reset — the
 * fixtures' per-test TRUNCATE would be pure cost here. The storageState the
 * project config injects is dropped for the same reason: this is what a
 * signed-out visitor sees.
 *
 * The field is hidden below 1024px by a media query in globals.css, so every
 * test here pins a desktop viewport.
 */
import { expect, test, type Page } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] }, viewport: { width: 1440, height: 900 } });

/** Where a ring sits on screen, and what the page is doing underneath it. */
interface Probe {
  x: number;
  y: number;
  scrollY: number;
}

/** Settle the landing: the intro overlay, the hero cascade, and the first
 *  frames of the sim all have to be behind us before anything is measured. */
async function openLanding(page: Page): Promise<number> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("[data-dragnode]").first()).toBeAttached({ timeout: 15_000 });
  await page.waitForTimeout(2_500);
  return page.evaluate(() => document.documentElement.scrollHeight);
}

/** Tag a ring that is comfortably inside the viewport, and return its centre. */
async function grabbableRing(page: Page, nth = 0): Promise<Probe> {
  const found = await page.evaluate((n) => {
    const rings = Array.from(document.querySelectorAll("[data-dragnode] [data-sim]"));
    const visible = rings.filter((r) => {
      const b = r.getBoundingClientRect();
      return b.top > 150 && b.top < window.innerHeight - 150
        && b.left > 100 && b.left < window.innerWidth - 100;
    });
    const pick = visible[n] || visible[0];
    if (!pick) return null;
    pick.setAttribute("data-e2e-probe", "1");
    const b = pick.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2, scrollY: window.scrollY };
  }, nth);
  expect(found, "a drag cluster should be on screen at this scroll position").not.toBeNull();
  return found!;
}

async function probe(page: Page): Promise<Probe> {
  return page.evaluate(() => {
    const b = document.querySelector("[data-e2e-probe]")!.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2, scrollY: window.scrollY };
  });
}

test("nodes do not move of their own accord while the page scrolls", async ({ page }) => {
  const height = await openLanding(page);

  // Sample every frame, in the page, so the measurement never depends on
  // round-trip timing. Each ring is measured against ITS OWN cluster, which
  // separates "the sim moved it" from "the section it belongs to is sticky".
  for (const fraction of [0.5, 0.8, 0.9]) {
    await page.evaluate((y) => window.scrollTo(0, y), Math.round(height * fraction));
    await page.waitForTimeout(700);

    await page.evaluate(() => {
      (window as never as { __frames: unknown[] }).__frames = [];
      const w = window as never as { __frames: unknown[]; __raf: number };
      const tick = () => {
        const rings: Array<{ k: string; dx: number; dy: number }> = [];
        document.querySelectorAll("[data-dragnode]").forEach((cluster) => {
          const cb = cluster.getBoundingClientRect();
          cluster.querySelectorAll("[data-sim]").forEach((r, i) => {
            const b = r.getBoundingClientRect();
            if (b.top > -600 && b.top < window.innerHeight + 600) {
              rings.push({
                k: `${cluster.getAttribute("data-dragnode")}:${i}`,
                dx: b.left - cb.left, dy: b.top - cb.top,
              });
            }
          });
        });
        w.__frames.push({ y: window.scrollY, rings });
        w.__raf = requestAnimationFrame(tick);
      };
      w.__raf = requestAnimationFrame(tick);
    });

    for (let i = 0; i < 30; i++) await page.mouse.wheel(0, 40);

    const result = await page.evaluate(() => {
      const w = window as never as {
        __frames: Array<{ y: number; rings: Array<{ k: string; dx: number; dy: number }> }>;
        __raf: number;
      };
      cancelAnimationFrame(w.__raf);
      // Path length, not frame-to-frame delta. The wander this catches is
      // ~0.15px per frame and only becomes visible by accumulating -- a
      // per-frame threshold loose enough to survive one noisy sample is
      // loose enough to miss the whole regression.
      const travelled = new Map<string, number>();
      let compared = 0;
      for (let i = 1; i < w.__frames.length; i++) {
        if (w.__frames[i].y === w.__frames[i - 1].y) continue; // page was still
        const now = Object.fromEntries(w.__frames[i].rings.map((r) => [r.k, r]));
        for (const before of w.__frames[i - 1].rings) {
          const after = now[before.k];
          if (!after) continue;
          const step = Math.hypot(after.dx - before.dx, after.dy - before.dy);
          travelled.set(before.k, (travelled.get(before.k) ?? 0) + step);
          compared++;
        }
      }
      return {
        worst: Math.max(0, ...travelled.values()),
        compared,
        scrolled: w.__frames.at(-1)!.y - w.__frames[0].y,
      };
    });

    expect(result.scrolled, "the page should actually have scrolled").toBeGreaterThan(200);
    expect(result.compared, "rings should have been on screen to compare").toBeGreaterThan(20);
    // Welded: a node's offset within its own cluster is frozen while the page
    // moves, so it travels nowhere at all. This was tens of px before the fix.
    expect(result.worst).toBeLessThan(2);
  }
});

test("a held node reaches the far edge of the viewport", async ({ page }) => {
  const height = await openLanding(page);
  await page.evaluate((y) => window.scrollTo(0, y), Math.round(height * 0.86));
  await page.waitForTimeout(800);

  const ring = await grabbableRing(page);
  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();
  await page.mouse.move(6, ring.y, { steps: 30 });
  await page.waitForTimeout(200);

  const at = await probe(page);
  // The old viewBox clamp walled this ~900px from the cluster's home, well
  // short of the edge on a 1440px viewport.
  expect(ring.x - at.x).toBeGreaterThan(1000);
  expect(at.x).toBeLessThan(60);
  await page.mouse.up();
});

test("a held node can be carried down the document and back up", async ({ page }) => {
  const height = await openLanding(page);
  await page.evaluate((y) => window.scrollTo(0, y), Math.round(height * 0.86));
  await page.waitForTimeout(800);

  const ring = await grabbableRing(page);
  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();

  // Held in the bottom band, the page scrolls under the node — which is what
  // lets it leave its own section at all.
  await page.mouse.move(ring.x, 885);
  await page.waitForTimeout(1_500);
  const down = await probe(page);
  expect(down.scrollY - ring.scrollY).toBeGreaterThan(300);
  expect(down.y, "still under the cursor, not lost off screen").toBeGreaterThan(700);

  await page.mouse.move(ring.x, 15);
  await page.waitForTimeout(1_500);
  const up = await probe(page);
  expect(up.scrollY).toBeLessThan(down.scrollY - 300);
  expect(up.y).toBeLessThan(200);

  // Parked away from the bands, the page must sit still.
  await page.mouse.move(ring.x, 450);
  const parked = await probe(page);
  await page.waitForTimeout(900);
  expect((await probe(page)).scrollY).toBe(parked.scrollY);
  await page.mouse.up();
});

test("a dropped node stays where it was put, and scrolls with the page", async ({ page }) => {
  const height = await openLanding(page);
  await page.evaluate((y) => window.scrollTo(0, y), Math.round(height * 0.86));
  await page.waitForTimeout(800);

  // A satellite rather than the course puck: the link spring pulls hardest on
  // these, and used to reel them straight back home.
  const ring = await grabbableRing(page, 1);
  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();
  await page.mouse.move(400, 300, { steps: 20 });
  await page.mouse.up();

  const dropped = await probe(page);
  await page.waitForTimeout(4_000);
  const settled = await probe(page);
  expect(Math.hypot(settled.x - dropped.x, settled.y - dropped.y)).toBeLessThan(1);

  // Placed, not detached: it belongs to the page and moves with it.
  await page.evaluate(() => window.scrollBy(0, 300));
  await page.waitForTimeout(600);
  const scrolled = await probe(page);
  expect(scrolled.y).toBeCloseTo(settled.y - 300, 0);
  expect(scrolled.x).toBeCloseTo(settled.x, 0);
});

test("dropping a node back where it started returns it to the cluster", async ({ page }) => {
  const height = await openLanding(page);
  await page.evaluate((y) => window.scrollTo(0, y), Math.round(height * 0.86));
  await page.waitForTimeout(800);

  const ring = await grabbableRing(page, 1);
  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();
  await page.mouse.move(400, 300, { steps: 20 });
  await page.mouse.up();
  await page.waitForTimeout(500);

  const held = await probe(page);
  await page.mouse.move(held.x, held.y);
  await page.mouse.down();
  await page.mouse.move(ring.x + 6, ring.y + 6, { steps: 20 });
  await page.mouse.up();
  await page.waitForTimeout(2_500);

  // Back among its neighbours...
  const home = await probe(page);
  expect(Math.hypot(home.x - ring.x, home.y - ring.y)).toBeLessThan(120);
  // ...and breathing again, which is what says it rejoined rather than being
  // placed a second time.
  await page.waitForTimeout(4_000);
  const later = await probe(page);
  expect(Math.hypot(later.x - home.x, later.y - home.y)).toBeGreaterThan(0.5);
});
