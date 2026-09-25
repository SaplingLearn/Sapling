/**
 * The graph act must lock to the viewport and hold for the length of its
 * section (#623).
 *
 * The act is scroll cinema: `#act-graph` is a 460vh section whose only child
 * is a `position: sticky; top: 0; height: 100vh` stage. Scrolling into it is
 * supposed to weld that stage to the top of the screen and hold it there for
 * 360vh — one section-height minus one stage-height — while four captions
 * cross-fade over the graph, releasing only as the last viewport of the
 * section scrolls past into the rise band.
 *
 * #623 reported the opposite: the stage never locking, so the act read as an
 * ordinary scrolling block. It did not reproduce — measured through the whole
 * act it pinned at exactly 0 at every width and in all three engines — and
 * the issue was closed as such. This file is what that verification leaves
 * behind, because the failure mode it describes is real, cheap to reintroduce,
 * and invisible to every other test:
 *
 *   1. `position: sticky` silently degrades to static scrolling the moment
 *      ANY ancestor between the section and the scroll container acquires an
 *      `overflow` of `hidden`, `auto` or `scroll`. Nothing errors, nothing
 *      warns, and the CSS on the stage itself still reads correctly. The
 *      whole chain is asserted below for that reason — one `overflow: hidden`
 *      added to `.landing-dc` or `.public-surface` for an unrelated clipping
 *      fix is the entire regression.
 *   2. The hold distance is the difference of two independently-edited
 *      numbers: the section's `460vh` and the stage's `100vh`. Either can be
 *      retuned without the other, and a stage that pins for a fraction of its
 *      act still pins — so a test that only asks "is it stuck?" stays green
 *      through the act collapsing to a third of its intended length.
 *
 * Both numbers are named as constants here rather than read back off the
 * product. Re-deriving the expectation from the markup makes the oracle
 * follow the regression: change `460vh` to `100vh` in ActGraph.tsx and a
 * self-measuring test re-frames itself around the new value and passes on
 * precisely the change it exists to catch. The oracle has to belong to the
 * test.
 *
 * Public surface: no auth, no DB. `test` comes from @playwright/test rather
 * than support/fixtures because there is no row to reset, and the project's
 * storageState is dropped — this is what a signed-out visitor sees.
 */
import { expect, test, type Page } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } });

/** The act's section height, in viewport heights — `ActGraph.tsx`'s `460vh`. */
const ACT_VH = 4.6;

/** The sticky stage's height, in viewport heights — its `100vh`. */
const STAGE_VH = 1;

/**
 * How far the stage is meant to stay welded to the top of the screen: the
 * section's own scroll length less the one viewport the stage occupies.
 */
const HOLD_VH = ACT_VH - STAGE_VH;

/**
 * Tolerance on the measured hold, as a fraction of a viewport.
 *
 * Generous on purpose. This guard is about the act keeping its shape, not
 * about pinning a number a designer is free to retune: a 10% retune of 460vh
 * should not turn this file red, while the collapse it exists to catch —
 * a stage that pins for a fraction of its act, or not at all — is off by
 * whole viewports. Wheel sampling also cannot land exactly on the release
 * point, so some slack is owed to the measurement itself.
 */
const HOLD_TOLERANCE_VH = 0.6;

/**
 * Where a frame of the act sat, sampled inside one rAF tick.
 *
 * `stageTop` is the whole assertion: while the act owns the screen it must be
 * 0. `secTop`/`secBottom` are the test's own definition of "the act owns the
 * screen", kept alongside so the pinned range is decided from the section's
 * geometry rather than from the stage that is under test.
 */
interface Frame {
  scrollY: number;
  stageTop: number;
  secTop: number;
  secBottom: number;
}

/**
 * Settle the landing and return the act's geometry.
 *
 * The intro overlay, the hero cascade and the engine's first frames all have
 * to be behind us: the canvas is attached before the engine has published its
 * graph, and scrolling during the cascade fights the page's own scroll
 * handling. The canvas being attached is the earliest honest signal that the
 * act is mounted; the wait after it covers the rest.
 */
async function openLanding(page: Page): Promise<{ top: number; height: number; vh: number }> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#act-graph canvas")).toBeAttached({ timeout: 15_000 });
  await page.waitForTimeout(2_500);
  return page.evaluate(() => {
    const section = document.getElementById("act-graph");
    if (!section) throw new Error("#act-graph is not in the page");
    return { top: section.offsetTop, height: section.offsetHeight, vh: window.innerHeight };
  });
}

/**
 * Walk the act with the wheel, sampling every frame.
 *
 * Wheel rather than `scrollTo`, and rAF rather than round trips, for the
 * reason the drag-field journeys use the same idiom: sticky is resolved by
 * the compositor, and a stage that jitters or detaches mid-scroll is only
 * visible between the positions a scripted jump would land on.
 */
async function walkTheAct(
  page: Page,
  act: { top: number; height: number; vh: number },
): Promise<Frame[]> {
  await page.evaluate((y) => window.scrollTo(0, y), Math.max(0, act.top - 600));
  await page.waitForTimeout(700);

  await page.evaluate(() => {
    const w = window as never as { __pin: Frame[]; __raf: number };
    w.__pin = [];
    const section = document.getElementById("act-graph")!;
    const stage = Array.from(section.children).find(
      (el) => getComputedStyle(el).position === "sticky",
    );
    if (!stage) throw new Error("#act-graph has no sticky stage");
    const tick = () => {
      const sb = section.getBoundingClientRect();
      w.__pin.push({
        scrollY: window.scrollY,
        stageTop: stage.getBoundingClientRect().top,
        secTop: sb.top,
        secBottom: sb.bottom,
      });
      w.__raf = requestAnimationFrame(tick);
    };
    w.__raf = requestAnimationFrame(tick);
  });

  // Drive on a wall-clock budget until the act is behind us — NOT for a
  // computed number of wheel ticks.
  //
  // `engine/scrollGovernor.ts` meters the wheel: a gesture may queue at most
  // MAX_BACKLOG_VH (2vh) ahead of the page and the page may move at most
  // MAX_SPEED_VH (2.4vh/s). Distance travelled is therefore a function of
  // elapsed TIME, and wheel events past the backlog are simply discarded — a
  // tight loop of 177 ticks asking for ~15900px reproducibly delivered 1908,
  // which is the governor working exactly as designed, not flake. Sending
  // more ticks cannot make the page move faster; only waiting can.
  //
  // Crossing this act needs roughly (460vh + a viewport) / 2.4vh/s ≈ 2.3s, so
  // the budget below is generous by an order of magnitude and exists only to
  // bound a hang. Driving through the real wheel path is deliberate: it keeps
  // the governor in the loop, which is where a future metering change could
  // break the act without touching a line of CSS.
  const deadline = Date.now() + 25_000;
  for (let i = 0; Date.now() < deadline; i++) {
    await page.mouse.wheel(0, 120);
    await page.waitForTimeout(16);
    if (i % 10 === 9) {
      const past = await page.evaluate(
        (vh) => document.getElementById("act-graph")!.getBoundingClientRect().bottom < vh - 400,
        act.vh,
      );
      if (past) break;
    }
  }
  await page.waitForTimeout(300);

  return page.evaluate(() => {
    const w = window as never as { __pin: Frame[]; __raf: number };
    cancelAnimationFrame(w.__raf);
    return w.__pin;
  });
}

/**
 * The frames during which the act owns the screen — its top at or above the
 * viewport top, its bottom at or below the viewport bottom.
 *
 * This is the window in which sticky is obliged to hold, derived from the
 * SECTION rather than from the stage, so it cannot collapse to "the frames
 * where the stage happened to be pinned" and assert itself.
 */
function pinnedFrames(frames: Frame[], vh: number): Frame[] {
  return frames.filter((f) => f.secTop <= 0 && f.secBottom >= vh);
}

test("the graph act welds its stage to the top of the screen", async ({ page }) => {
  const act = await openLanding(page);
  const frames = await walkTheAct(page, act);

  // "Did we cross it?" asked of the act's position, not of scrollY. The
  // governor rebases in-flight gestures, so `scrollY` is not monotonic across
  // a walk and last-minus-first understates the distance covered — a
  // precondition written that way fails on a walk that in fact crossed the
  // whole act. The section entering the top of the screen and later leaving
  // it is the same claim, stated where it cannot be confused by metering.
  expect(frames.some((f) => f.secTop > 0), "the walk should start above the act").toBe(true);
  expect(frames.some((f) => f.secTop <= 0), "the act should have reached the top").toBe(true);
  expect(frames.some((f) => f.secBottom < act.vh), "the act should have been passed").toBe(true);

  const held = pinnedFrames(frames, act.vh);
  expect(held.length, "the act should have owned the screen for many frames").toBeGreaterThan(30);

  // The regression, stated directly: through every frame in which the act
  // owns the screen, the stage's top edge is the viewport's top edge. A stage
  // that scrolls instead of sticking leaves immediately and by hundreds of px.
  const worst = Math.max(...held.map((f) => Math.abs(f.stageTop)));
  expect(worst, "the stage came unstuck while the act owned the screen").toBeLessThan(2);
});

test("the act holds for its whole 460vh rather than a fraction of it", async ({ page }) => {
  const act = await openLanding(page);
  const frames = await walkTheAct(page, act);
  const held = pinnedFrames(frames, act.vh);
  expect(held.length, "the act should have owned the screen").toBeGreaterThan(30);

  // Distance travelled with the stage welded, in viewport heights. The act is
  // 460vh holding a 100vh stage, so this is 360vh — collapse the section, or
  // grow the stage, and the cinema shortens without ever stopping sticking.
  //
  // Span, not last-minus-first: the governor's rebasing makes `scrollY`
  // non-monotonic within the walk, so the extremes are the honest reach.
  const ys = held.map((f) => f.scrollY);
  const heldVh = (Math.max(...ys) - Math.min(...ys)) / act.vh;
  expect(heldVh).toBeGreaterThan(HOLD_VH - HOLD_TOLERANCE_VH);
  expect(heldVh).toBeLessThan(HOLD_VH + HOLD_TOLERANCE_VH);

  // ...and it does release. A stage that never lets go is its own regression:
  // the rise band and the ingest act would never arrive.
  const after = frames.filter((f) => f.secBottom < act.vh);
  expect(after.length, "the act should have released before the walk ended").toBeGreaterThan(5);
  expect(Math.min(...after.map((f) => f.stageTop))).toBeLessThan(-100);
});

test("nothing in the act's ancestry breaks sticky positioning", async ({ page }) => {
  await openLanding(page);

  const chain = await page.evaluate(() => {
    const rows: Array<{ tag: string; overflowX: string; overflowY: string }> = [];
    let el: HTMLElement | null = document.getElementById("act-graph")!.parentElement;
    while (el) {
      const s = getComputedStyle(el);
      const cls = typeof el.className === "string" && el.className.trim()
        ? "." + el.className.trim().split(/\s+/)[0]
        : "";
      rows.push({ tag: el.tagName.toLowerCase() + cls, overflowX: s.overflowX, overflowY: s.overflowY });
      el = el.parentElement;
    }
    return rows;
  });

  expect(chain.length, "the act should have an ancestor chain up to <html>").toBeGreaterThan(2);

  // `clip` is explicitly allowed and deliberately used: `.landing-dc` and
  // `.public-surface` carry `overflow-x: clip` to contain the full-bleed
  // grounds, and unlike `hidden` it creates no scroll container, so sticky
  // survives it. `hidden`/`auto`/`scroll` is the regression — each one turns
  // the nearest such ancestor into the stage's scroll container and the pin
  // silently stops happening against the document.
  const breakers = chain.filter(
    (row) => ["hidden", "auto", "scroll"].includes(row.overflowX)
      || ["hidden", "auto", "scroll"].includes(row.overflowY),
  );
  expect(
    breakers,
    "an ancestor of #act-graph has a sticky-breaking overflow — use `clip` "
      + "instead of `hidden` if something there needs containing (#623)",
  ).toEqual([]);
});

/**
 * The issue asked specifically whether the pin differs at narrow widths, so
 * the answer is pinned here. The act carries no width media query, and the
 * stage is sized in viewport units, so a phone viewport is the same contract
 * on a taller, narrower screen — which is exactly why a layout change that
 * only lands under a breakpoint could take it out unnoticed.
 */
test("the stage pins at phone width too", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const act = await openLanding(page);
  const frames = await walkTheAct(page, act);

  const held = pinnedFrames(frames, act.vh);
  expect(held.length, "the act should have owned the screen").toBeGreaterThan(30);
  expect(Math.max(...held.map((f) => Math.abs(f.stageTop)))).toBeLessThan(2);
});
