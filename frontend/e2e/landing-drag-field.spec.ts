/**
 * The landing page's draggable course clusters must read as part of the page.
 *
 * Promoted from a real regression: the clusters were a layer floating over the
 * site rather than in it. Four symptoms, all pinned here because unit tests
 * in jsdom can only assert the geometry the fixture itself supplies — whether
 * a real browser's layout, sticky positioning and compositor agree is only
 * answerable here.
 *
 *   1. a cluster inside a pinned act drifted up to 150px against the scroll;
 *   2. the sim kept integrating while the page scrolled, so every node
 *      wandered 20-50px of its own accord under a moving page;
 *   3. nodes were clamped to their svg's viewBox, walling the drag ~900px
 *      sideways and ~1600px up/down of the cluster's home;
 *   4. the field's sticky box was a different height from its act's stage, so
 *      it released a full viewport later — 882px of the copy scrolling away
 *      while the clusters stayed welded to the top of the screen. That one
 *      survived the first three fixes and every test written for them,
 *      because they all measured a cluster against its own field rather than
 *      against the page.
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

/**
 * The envelope a placed node's breathing stays inside — `PLACED_SWAY` is a
 * third of the free amplitude. Wide enough for the sway, far short of the
 * distance that would mean it had wandered off the spot it was left on.
 */
const SWAY_PX = 12;

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

/**
 * The cluster the drag journeys use: id 4, in the static `faq` section.
 *
 * Named rather than discovered. Picking "whatever ring is on screen" looks
 * more robust and is the opposite: the idle breathing drift moves nodes
 * ~20px, which is enough to change which of them clears a visibility filter,
 * so the journey grabs a different node from run to run and fails for reasons
 * that have nothing to do with the code.
 *
 * `faq` specifically, because these journeys need room on all four sides.
 * The `cta` clusters sit ~120px above the end of the document, so there is
 * nothing left to autoscroll into and a 300px scroll assertion cannot be met.
 */
const CLUSTER = "4";
/**
 * The section that cluster lives in, so the journeys can ask the page what
 * the cluster is welded to rather than assuming it is welded to nothing.
 */
const CLUSTER_SECTION = "faq";
/** A satellite, not the course puck: the link spring pulls hardest on these. */
const SATELLITE = 1;

/** Scroll the named cluster to a fixed place in the viewport. */
async function centreCluster(page: Page, id = CLUSTER): Promise<void> {
  const found = await page.evaluate((cid) => {
    const cluster = document.querySelector(`[data-dragnode="${cid}"]`);
    if (!cluster) return false;
    window.scrollBy(0, cluster.getBoundingClientRect().top - 380);
    return true;
  }, id);
  expect(found, `cluster ${id} should exist`).toBe(true);
  await page.waitForTimeout(700);
}

/**
 * Tag one ring of the named cluster and return its centre.
 *
 * Preference order starting at `index`, but only a ring that HIT-TESTS TO
 * ITSELF is taken. The rings of a cluster sit within a few px of each other
 * and the later-painted one wins: tagging ring 1 while the pointer actually
 * grabs ring 3 produces a test that watches the wrong node get towed along by
 * the link force, and reads that as the drag failing.
 */
async function ringOf(page: Page, index = SATELLITE, id = CLUSTER): Promise<Probe> {
  const found = await page.evaluate(({ cid, i }) => {
    const rings = Array.from(document.querySelectorAll(`[data-dragnode="${cid}"] [data-sim]`));
    const order = [rings[i], ...rings].filter(Boolean);
    for (const ring of order) {
      const b = ring.getBoundingClientRect();
      const x = b.left + b.width / 2;
      const y = b.top + b.height / 2;
      if (document.elementFromPoint(x, y) !== ring) continue;
      ring.setAttribute("data-e2e-probe", "1");
      return { x, y, scrollY: window.scrollY };
    }
    return null;
  }, { cid: id, i: index });
  expect(found, `cluster ${id} should expose a grabbable ring`).not.toBeNull();
  expect(found!.y, "the ring should be well inside the viewport").toBeGreaterThan(120);
  expect(found!.y).toBeLessThan(780);
  return found!;
}

async function probe(page: Page): Promise<Probe> {
  return page.evaluate(() => {
    const b = document.querySelector("[data-e2e-probe]")!.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2, scrollY: window.scrollY };
  });
}

/**
 * Where the page content a cluster is welded to currently sits on screen.
 *
 * A field names its weld target in `data-drag-track` (DragField.tsx's
 * `TRACKS`), and `engine/sim.ts` translates the cluster so that it holds a
 * fixed offset from it. `faq` is the one section that has one: its question
 * column is `sticky; top:110`, so the section can scroll 300px while the copy
 * the clusters belong to moves only ~202 and the clusters go with the copy.
 *
 * Read from the attribute rather than naming the column here, so this stays
 * in step with the product: if the weld is ever dropped, this falls back to
 * the field itself, which is the plain 1:1 page-scroll reference.
 */
async function weldTop(page: Page, section = CLUSTER_SECTION): Promise<number> {
  return page.evaluate((s) => {
    const field = document.querySelector(`#${s} .drag-field`);
    if (!field) throw new Error(`no drag field in #${s}`);
    const sel = field.getAttribute("data-drag-track");
    const el = sel ? document.querySelector(sel) : field;
    if (!el) throw new Error(`weld target ${sel} is not in the document`);
    return el.getBoundingClientRect().top;
  }, section);
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

test("a cluster holds still against its act, through the pin and the release", async ({ page }) => {
  await openLanding(page);

  // act-tutor is a 340vh section holding one sticky stage; clusters 2 and 3
  // live in it. Walk the whole act, including the point where the stage stops
  // sticking -- which is exactly where the field used to part company with
  // the copy, having been given a sticky box of a different height.
  const act = await page.evaluate(() => {
    const section = document.getElementById("act-tutor")!;
    return { top: section.offsetTop, height: section.offsetHeight };
  });

  await page.evaluate((y) => window.scrollTo(0, y), act.top - 200);
  await page.waitForTimeout(700);

  await page.evaluate(() => {
    const w = window as never as { __act: unknown[]; __raf: number };
    w.__act = [];
    const section = document.getElementById("act-tutor")!;
    // The stage is the sticky child carrying the COPY, identified by the act's
    // heading. Identifying it as "the sticky child without clusters in it"
    // silently resolves to the drag field once the sim has re-homed the
    // clusters into its overlay — which turns this whole journey into a
    // comparison of the cluster against its own anchor, i.e. zero by
    // construction, passing against the very markup it exists to catch.
    const stage = Array.from(section.children).find(
      (el) => getComputedStyle(el).position === "sticky"
        && !el.classList.contains("drag-field")
        && !el.querySelector(".drag-field")
        && el.querySelector("h2"),
    );
    if (!stage) throw new Error("act-tutor has no sticky stage carrying an h2");
    const tick = () => {
      const rows: Array<{ k: string; d: number }> = [];
      for (const id of ["2", "3"]) {
        const cluster = document.querySelector(`[data-dragnode="${id}"]`);
        if (!cluster) continue;
        const b = cluster.getBoundingClientRect();
        if (b.top < -2500 || b.top > window.innerHeight + 2500) continue;
        rows.push({ k: id, d: b.top - stage.getBoundingClientRect().top });
      }
      w.__act.push({ y: window.scrollY, rows });
      w.__raf = requestAnimationFrame(tick);
    };
    w.__raf = requestAnimationFrame(tick);
  });

  // Enough ticks to cross the whole act and come out the far side.
  const ticks = Math.ceil((act.height + 600) / 60);
  for (let i = 0; i < ticks; i++) await page.mouse.wheel(0, 60);
  await page.waitForTimeout(200);

  const result = await page.evaluate(() => {
    const w = window as never as {
      __act: Array<{ y: number; rows: Array<{ k: string; d: number }> }>;
      __raf: number;
    };
    cancelAnimationFrame(w.__raf);
    const seen = new Map<string, number[]>();
    for (const frame of w.__act) {
      for (const row of frame.rows) {
        if (!seen.has(row.k)) seen.set(row.k, []);
        seen.get(row.k)!.push(row.d);
      }
    }
    const spreads = [...seen.entries()].map(([k, ds]) => ({
      k, samples: ds.length, spread: Math.max(...ds) - Math.min(...ds),
    }));
    return {
      spreads,
      scrolled: w.__act.at(-1)!.y - w.__act[0].y,
    };
  });

  expect(result.scrolled, "should have crossed the whole act").toBeGreaterThan(act.height * 0.7);
  expect(result.spreads.length, "both act-tutor clusters should have been seen").toBe(2);
  for (const { k, samples, spread } of result.spreads) {
    expect(samples, `cluster ${k} should have been sampled`).toBeGreaterThan(30);
    // Welded to the act: the cluster's offset from the stage never changes,
    // whether the stage is pinned or scrolling away. This was 882px.
    expect(spread, `cluster ${k} drifted from its act's stage`).toBeLessThan(2);
  }
});

test("a held node reaches the far edge of the viewport", async ({ page }) => {
  await openLanding(page);
  await centreCluster(page);
  const ring = await ringOf(page, 0);

  // Toward whichever edge is further away. Clusters sit near one margin or
  // the other, so a fixed direction measures the short trip half the time.
  const width = page.viewportSize()!.width;
  const target = ring.x < width / 2 ? width - 6 : 6;

  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();
  await page.mouse.move(target, ring.y, { steps: 30 });
  await page.waitForTimeout(200);

  const at = await probe(page);
  // The old viewBox clamp walled this ~900px from the cluster's home, well
  // short of the far edge on a 1440px viewport.
  expect(Math.abs(ring.x - at.x)).toBeGreaterThan(1000);
  expect(Math.abs(at.x - target)).toBeLessThan(60);
  await page.mouse.up();
});

test("a held node can be carried down the document and back up", async ({ page }) => {
  await openLanding(page);
  await centreCluster(page);
  const ring = await ringOf(page, 0);
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
  await openLanding(page);
  await centreCluster(page);
  const ring = await ringOf(page);
  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();
  await page.mouse.move(400, 300, { steps: 20 });
  await page.mouse.up();

  const dropped = await probe(page);
  await page.waitForTimeout(4_000);
  const settled = await probe(page);
  // Inside its sway, not frozen on the spot: a placed node keeps a third of
  // the breathing drift, so it lives where it was left rather than dying
  // there. SWAY_PX is the envelope that buys.
  expect(Math.hypot(settled.x - dropped.x, settled.y - dropped.y)).toBeLessThan(SWAY_PX);

  // Placed, not detached: it belongs to the page and moves with it.
  //
  // "The page" is the copy its cluster is welded to, NOT raw scrollY. The faq
  // question column is `sticky; top:110`, so scrolling 300px moves the
  // section 300px and the copy only as far as the pin allows — and the
  // clusters go with the copy, which is the whole point of `TRACKS`.
  // Measuring against scrollY asserted the one coupling this section
  // deliberately does not have, and cost the node ~98px it never owed.
  const weldBefore = await weldTop(page);
  await page.evaluate(() => window.scrollBy(0, 300));
  await page.waitForTimeout(600);
  const scrolled = await probe(page);
  const travelled = (await weldTop(page)) - weldBefore;

  // Not a fixed overlay floating over the site: the copy it is welded to
  // really did move under it. Without this the assertion below would pass on
  // a node that is pinned to the screen and a page that never scrolled.
  expect(Math.abs(travelled), "the weld target should have moved").toBeGreaterThan(100);
  expect(scrolled.scrollY - settled.scrollY, "the page should have scrolled").toBe(300);

  // ...and the node went exactly that far, inside its sway.
  expect(Math.hypot(scrolled.x - settled.x, scrolled.y - (settled.y + travelled)))
    .toBeLessThan(SWAY_PX);
});

test("a short drag stays put instead of crawling home", async ({ page }) => {
  // There is no rejoin radius any more. A drop within 70px of a node's home
  // used to re-float it, so most drags — which are short — crept back to
  // where they started: 14px of travel still climbing 4s after a 40px drag,
  // against 0px for a 90px one. Every drop places the node now.
  await openLanding(page);
  await centreCluster(page);
  const ring = await ringOf(page);

  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();
  await page.mouse.move(ring.x + 34, ring.y - 22, { steps: 15 });
  await page.mouse.up();
  await page.waitForTimeout(500);

  const dropped = await probe(page);
  // Short enough that the old radius would have reeled it in, and it moved.
  const moved = Math.hypot(dropped.x - ring.x, dropped.y - ring.y);
  expect(moved).toBeLessThan(70);
  expect(moved).toBeGreaterThan(2);

  // Past a full breathing period: still there, still breathing. Dead still
  // was the other bug — a dropped node used to stop moving entirely.
  await page.waitForTimeout(5_000);
  const later = await probe(page);
  expect(Math.hypot(later.x - dropped.x, later.y - dropped.y)).toBeLessThan(SWAY_PX);
});
