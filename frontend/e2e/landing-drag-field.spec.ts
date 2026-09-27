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
 * The envelope a placed node's breathing stays inside.
 *
 * `PLACED_SWAY` is 1 — all of the free amplitude — and `sim.ts` puts the
 * resulting excursion at ~21px, deliberately matching what the node had
 * before it was touched. This was 12, written when a placed node kept only a
 * third of its drift; that reading is stale, and a dropped node measured
 * 12.7px against it.
 *
 * Still far short of the distance that would mean the node had wandered off
 * the spot it was left on: what bounds that is `PLACED_ANCHOR`, not this, and
 * the 1:1-travel and offset-against-copy journeys below are what would catch
 * a node that actually departed.
 */
const SWAY_PX = 26;

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
 * The copy cluster 4 is welded to: the `faq` question column.
 *
 * Named here, NOT read out of the field's `data-drag-track`. Taking the
 * reference from the product would make this journey follow the product:
 * delete `faq` from `DragField.tsx`'s `TRACKS` and the clusters go back to
 * sliding 374px out from under the words they annotate — the regression
 * 8bb34869 fixed — but a test that re-derived its own expectation would
 * re-frame itself along with it and stay green on exactly that. The oracle
 * has to belong to the test.
 *
 * `faq` is the only section in `TRACKS`, and this column is `sticky; top:110`,
 * so the section can scroll 300px while the copy moves ~202 — which is why
 * measuring a cluster here against raw `scrollY` was wrong.
 */
const FAQ_SECTION = "faq";
const FAQ_COPY = '[data-drag-anchor="faq"]';

/**
 * A cluster in a section with no weld and no pin, where moving 1:1 with the
 * document IS the contract. `newsletter` holds clusters 6 and 7, is absent
 * from `TRACKS`, and — unlike `cta`, which sits ~120px from the end of the
 * document — has room below it for a 300px scroll assertion.
 */
const UNTRACKED_CLUSTER = "6";
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
 * The probe ring and the FAQ copy it is welded to, sampled in ONE frame.
 *
 * One `page.evaluate`, not two: the sim is still integrating when this runs
 * (`SCROLL_QUIET_MS` expired long before), so sampling the node and its
 * reference in separate round trips compares two different frames.
 *
 * The column is resolved the way `engine/sim.ts` resolves it — scoped to the
 * field's own section, not `document`-wide — so this measures against the
 * element the sim actually bound to. A global lookup would silently diverge
 * from the product the moment a second match appeared earlier in the page.
 */
async function probeAgainstCopy(
  page: Page,
): Promise<{ x: number; y: number; copyTop: number; scrollY: number }> {
  return page.evaluate(({ section, copy }) => {
    const field = document.querySelector(`#${section} .drag-field`);
    if (!field) throw new Error(`no .drag-field in #${section}`);
    const el = (field.closest("section") ?? document).querySelector(copy);
    if (!el) throw new Error(`${copy} is not inside #${section}`);
    const b = document.querySelector("[data-e2e-probe]")!.getBoundingClientRect();
    return {
      x: b.left + b.width / 2,
      y: b.top + b.height / 2,
      copyTop: el.getBoundingClientRect().top,
      scrollY: window.scrollY,
    };
  }, { section: FAQ_SECTION, copy: FAQ_COPY });
}

/** How far this journey scrolls at each sample point. */
const SCROLL_RUN_PX = 1200;

test("nodes do not move of their own accord while the page scrolls", async ({ page }) => {
  await openLanding(page);

  // Sample every frame, in the page, so the measurement never depends on
  // round-trip timing. Each ring is measured against ITS OWN cluster, which
  // separates "the sim moved it" from "the section it belongs to is sticky".
  //
  // Each sample point is taken of the CURRENT scrollable range and clamped to
  // leave a full run of headroom below it. Two things force that. `foldActs`
  // collapses a finished act's runway, so the page gets shorter as it is read
  // — 0.9 of the height measured at the top landed past the end of the
  // shortened document, where the wheel moved the page 0px and there was
  // nothing to measure. And the clusters live low on the page, so the window
  // has to stay in their half: sampling at 0.2 and 0.4 scrolls perfectly well
  // and sees no rings at all.
  for (const fraction of [0.5, 0.6, 0.7]) {
    await page.evaluate(({ f, run }) => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      window.scrollTo(0, Math.min(Math.round(max * f), Math.max(0, max - run)));
    }, { f: fraction, run: SCROLL_RUN_PX });
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
        w.__frames.push({ t: performance.now(), y: window.scrollY, rings });
        w.__raf = requestAnimationFrame(tick);
      };
      w.__raf = requestAnimationFrame(tick);
    });

    // Paced, not fired in a burst. `engine/scrollGovernor.ts` meters the wheel
    // — a gesture queues at most MAX_BACKLOG_VH ahead and the page moves at
    // most MAX_SPEED_VH — so distance travelled is a function of elapsed time,
    // and ticks past the backlog are discarded. A tight loop of these asked for
    // 1200px and moved the page 0.
    for (let i = 0; i < 30; i++) {
      await page.mouse.wheel(0, 40);
      await page.waitForTimeout(16);
    }

    const result = await page.evaluate(() => {
      const w = window as never as {
        __frames: Array<{ t: number; y: number; rings: Array<{ k: string; dx: number; dy: number }> }>;
        __raf: number;
      };
      cancelAnimationFrame(w.__raf);
      // Path length, not frame-to-frame delta. The wander this catches is
      // ~0.15px per frame and only becomes visible by accumulating -- a
      // per-frame threshold loose enough to survive one noisy sample is
      // loose enough to miss the whole regression.
      const travelled = new Map<string, number>();
      let compared = 0;
      let movedFrames = 0;
      let pageTravel = 0;
      let starved = 0;
      // `sim.ts` holds the field still for SCROLL_QUIET_MS (140) after the last
      // scroll. A frame pair further apart than that straddles a window in
      // which the sim was entitled to resume breathing, and its motion is not
      // the wander this journey is looking for. On an unloaded machine no pair
      // is ever this far apart; under load they are, and counting them turned
      // legitimate breathing into a 0.4px/frame "drift" that failed here while
      // nine isolated runs of the same positions measured 0.005.
      const SIM_QUIET_MS = 140;
      for (let i = 1; i < w.__frames.length; i++) {
        if (w.__frames[i].y === w.__frames[i - 1].y) continue; // page was still
        if (w.__frames[i].t - w.__frames[i - 1].t >= SIM_QUIET_MS) { starved++; continue; }
        movedFrames++;
        pageTravel += Math.abs(w.__frames[i].y - w.__frames[i - 1].y);
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
        movedFrames,
        pageTravel,
        starved,
      };
    });

    // Distance travelled, not net displacement. `foldActs` collapses a
    // finished act's runway mid-scroll, which shortens the document and makes
    // the browser clamp `scrollY` back down — so the page can move hundreds of
    // px and end up ABOVE where it started. Two of these three sample points
    // finish net negative while scrolling perfectly well.
    expect(result.pageTravel, "the page should actually have moved").toBeGreaterThan(200);
    expect(result.movedFrames, "frames where the page actually moved").toBeGreaterThan(20);
    expect(result.compared, "rings should have been on screen to compare").toBeGreaterThan(20);
    // Welded: a node's offset within its own cluster is frozen while the page
    // moves, so it travels nowhere at all. This was tens of px before the fix.
    //
    // Asserted as a RATE rather than a total. Path length grows with sampling
    // density, and since `engine/scrollGovernor.ts` began metering the wheel
    // the same 1200px of scroll is delivered over ~56 frames instead of ~10 —
    // so the accumulated sub-pixel noise grew with it and a fixed 2px budget
    // started failing on a page that had not changed. A rate is what the
    // invariant actually means and is independent of how long the scroll takes.
    //
    // The regression this guards ran at ~0.15px per frame and totalled tens of
    // px; measured drift with headroom to scroll is ~0.004-0.01. 0.05 sits
    // clear of that and still catches the regression at a third of its rate.
    expect(result.worst / result.movedFrames).toBeLessThan(0.05);
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
  // Driven until the act is behind us on a wall-clock budget, for the same
  // reason as above: the governor meters the wheel, so a fixed tick count
  // cannot buy a fixed distance. This asked for the act's height and got 1500
  // of 3060 before the budget mattered.
  const deadline = Date.now() + 25_000;
  for (let i = 0; Date.now() < deadline; i++) {
    await page.mouse.wheel(0, 60);
    await page.waitForTimeout(16);
    if (i % 10 === 9) {
      const past = await page.evaluate(
        (h) => window.scrollY > h,
        act.top + act.height + 400,
      );
      if (past) break;
    }
  }
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

  // Placed, not detached: it belongs to the copy it was dropped over.
  //
  // Measured as an OFFSET that must not change, which is the idiom the
  // act-tutor journey above already uses for the same invariant — no delta
  // arithmetic whose sign only works out because the page happens to scroll
  // down. The node's distance from the FAQ column is the thing being pinned.
  const before = await probeAgainstCopy(page);
  await page.evaluate(() => window.scrollBy(0, 300));
  await page.waitForTimeout(600);
  const after = await probeAgainstCopy(page);

  // Preconditions first, most-basic first, so a failure names its own cause
  // instead of sending the next reader to `TRACKS` and `syncClusters()`.
  // `toBeCloseTo`, not `toBe`: `scrollY` is a browser-computed offset that is
  // only integral because `deviceScaleFactor` happens to be 1.
  expect(after.scrollY - before.scrollY, "the page should have scrolled")
    .toBeCloseTo(300, 0);
  // Signed, not `Math.abs`: scrolling DOWN must carry page content UP. A
  // regression that translated the copy downward under a downward scroll
  // would satisfy an absolute-value guard, and a node loyally following it
  // would satisfy everything below.
  //
  // The journey can only tell "welded" from "pinned to the screen" while the
  // copy still has travel left before its own pin — a node welded to an
  // already-pinned column is stationary, and so is a detached overlay. That
  // is a property of where `centreCluster` parks the cluster, not of the
  // product, so assert it and say so rather than assume it.
  expect(
    after.copyTop - before.copyTop,
    "the FAQ copy was already pinned at the drop position — this journey needs " +
      "it mid-travel; check #faq's layout or centreCluster's offset",
  ).toBeLessThan(-100);

  // ...and through all of that the node held its place against the copy.
  expect(Math.hypot(
    after.x - before.x,
    (after.y - after.copyTop) - (before.y - before.copyTop),
  )).toBeLessThan(SWAY_PX);
});

/**
 * The other half of "belongs to the page", on a cluster where that means what
 * it sounds like.
 *
 * The journey above deliberately measures against the FAQ copy, because that
 * is what its cluster is welded to. Something still has to pin the plain
 * case — a placed node in an untracked, unpinned section travelling exactly
 * with the document — or the file loses the reference frame its own header
 * (symptom 4) is about, and a cluster field that detached into a fixed
 * overlay would have nothing left to catch it.
 */
test("a dropped node in an untracked section travels 1:1 with the document", async ({ page }) => {
  await openLanding(page);
  await centreCluster(page, UNTRACKED_CLUSTER);
  const ring = await ringOf(page, SATELLITE, UNTRACKED_CLUSTER);

  await page.mouse.move(ring.x, ring.y);
  await page.mouse.down();
  await page.mouse.move(ring.x - 120, ring.y - 60, { steps: 20 });
  await page.mouse.up();
  await page.waitForTimeout(4_000);
  const settled = await probe(page);

  await page.evaluate(() => window.scrollBy(0, 300));
  await page.waitForTimeout(600);
  const scrolled = await probe(page);

  const moved = scrolled.scrollY - settled.scrollY;
  expect(moved, "the page should have scrolled").toBeCloseTo(300, 0);
  // No `TRACKS` entry and no sticky stage: this cluster owes the document the
  // whole 300px. This is the assertion the faq journey used to carry, on the
  // cluster where it is actually true.
  expect(Math.hypot(scrolled.x - settled.x, scrolled.y - (settled.y - moved)))
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
