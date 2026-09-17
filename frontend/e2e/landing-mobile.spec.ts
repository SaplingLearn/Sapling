/**
 * The landing page at phone width.
 *
 * Promoted from a real regression: every section declared its desktop layout
 * inline, so at 390px the ingest act's two-column copy collapsed to one word
 * per line, the FAQ and Journal kept their side-by-side grids, the newsletter
 * form ran off the right edge, the nav's "Get Started" wrapped onto two lines,
 * and — worst — the graph act's canvas carried `touch-action: none` across
 * the whole pinned stage, so a finger could not scroll past it at all. The
 * phone pass lives in globals.css under `.landing-v5` (≤900px stacks the
 * grids, ≤640px is the phone budget); this pins what it has to hold.
 *
 * Public surface: no auth, no DB. `test` comes from @playwright/test rather
 * than support/fixtures for the same reason landing-drag-field.spec does —
 * there is no row to reset — and the injected storageState is dropped so this
 * is what a signed-out visitor sees.
 */
import { expect, test, type Page } from "@playwright/test";

/** iPhone 14/15 CSS viewport — with the browser's toolbars showing, which
 *  is the height the pinned acts have to fit (they budget on `100svh`). */
const VW = 390;
const VH = 664;
/** The least a pinned act's illustration may leave between itself and the
 *  bottom of the screen. */
const FLOOR_PX = 24;

test.use({
  storageState: { cookies: [], origins: [] },
  viewport: { width: VW, height: VH },
  hasTouch: true,
});

/** Settle the landing: intro overlay, hero cascade, first engine measure. */
async function openLanding(page: Page): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".ld-nav-cta")).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(2_500);
}

/** Scroll the window so `selector`'s top sits `offset` px above the viewport,
 *  then wait out the engine's next measure pass. The engine folds a finished
 *  act to 100vh and re-scrolls to compensate, so the position is re-applied
 *  once after that settles. */
async function scrollInto(page: Page, selector: string, offset: number): Promise<void> {
  for (let i = 0; i < 2; i++) {
    await page.evaluate(
      ([sel, off]) => {
        const el = document.querySelector(sel as string)!;
        window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY + (off as number));
      },
      [selector, offset] as const,
    );
    await page.waitForTimeout(1_200);
  }
}

test("nothing overflows the phone viewport and the nav stays on one line", async ({ page }) => {
  await openLanding(page);

  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(VW);

  const cta = await page.locator(".ld-nav-cta").boundingBox();
  const signIn = await page.locator(".ld-nav-signin").boundingBox();
  expect(cta).not.toBeNull();
  expect(signIn).not.toBeNull();
  // one line of 14px text with 10px padding is ~38px; a wrapped button is 60+
  expect(cta!.height).toBeLessThan(44);
  expect(cta!.x + cta!.width).toBeLessThanOrEqual(VW - 8);
  expect(signIn!.x + signIn!.width).toBeLessThanOrEqual(cta!.x);
});

test("a finger can scroll through the graph act", async ({ page }) => {
  await openLanding(page);
  // `none` here traps every vertical swipe inside a 460vh section
  expect(
    await page.evaluate(() => getComputedStyle(document.querySelector("#act-graph canvas")!).touchAction),
  ).toBe("pan-y");
});

test("the ingest act stacks its copy and fits its scene to the stage", async ({ page }) => {
  await openLanding(page);

  // the collapsed grid gave this paragraph ~30px and one word per line
  const copy = await page.locator(".ld-ingest-p1").boundingBox();
  expect(copy!.width).toBeGreaterThan(300);

  await scrollInto(page, "#act-ingest", 1_200);
  const r = await page.evaluate(() => {
    const box = (el: Element | null) => el!.getBoundingClientRect();
    const stage = box(document.querySelector(".ld-ingest-stage"));
    const doc = box(document.querySelector(".ld-ingest-doc"));
    const tiles = document.querySelectorAll("[data-ingest-tile]");
    const first = box(tiles[0]);
    const last = box(tiles[tiles.length - 1]);
    return {
      stageBottom: stage.bottom, stageRight: stage.right, stageLeft: stage.left,
      docBottom: doc.bottom, firstTileTop: first.top, lastBottom: last.bottom, lastRight: last.right,
      vh: window.innerHeight,
    };
  });
  // document above the destinations, not beside them
  expect(r.docBottom).toBeLessThanOrEqual(r.firstTileTop + 1);
  // the fitted scene ends inside its stage, and the stage inside the screen
  expect(r.lastBottom).toBeLessThanOrEqual(r.stageBottom + 2);
  expect(r.stageBottom).toBeLessThanOrEqual(r.vh);
  // and off the floor: the tiles used to sit on the bottom edge of the screen
  expect(r.lastBottom).toBeLessThanOrEqual(r.vh - FLOOR_PX);
  // and the width compensation keeps it spanning the stage, not huddled left
  expect(r.lastRight).toBeGreaterThan(r.stageRight - 12);
});

test("the tutor act docks its card above the floor", async ({ page }) => {
  await openLanding(page);
  // the act's last stretch, where the prism has settled on its first face
  for (let i = 0; i < 2; i++) {
    await page.evaluate(() => {
      const el = document.getElementById("act-tutor")!;
      window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY + el.offsetHeight - window.innerHeight - 10);
    });
    await page.waitForTimeout(1_500);
  }
  await page.waitForTimeout(2_500);
  const r = await page.evaluate(() => {
    const face = document.querySelector('[data-panel="0"]')!.getBoundingClientRect();
    const copy = document.querySelector(".ld-tutor-copy")!.getBoundingClientRect();
    return { faceTop: face.top, faceBottom: face.bottom, faceLeft: face.left, faceRight: face.right, copyBottom: copy.bottom, vh: window.innerHeight };
  });
  // heading and pills above the card, the card inside the screen with room under it
  expect(r.faceTop).toBeGreaterThanOrEqual(r.copyBottom - 1);
  expect(r.faceBottom).toBeLessThanOrEqual(r.vh - FLOOR_PX);
  expect(r.faceLeft).toBeGreaterThanOrEqual(0);
  expect(r.faceRight).toBeLessThanOrEqual(VW);
});

test("narrowing a desktop window does not strand the drag clusters on screen", async ({ page }) => {
  // The sim re-homes the clusters into a fixed overlay once they scroll into
  // view at desktop width. Below 1024px the field is hidden, but the overlay
  // copies used to stay — parked in the top-left corner of every section.
  await page.setViewportSize({ width: 1280, height: 800 });
  await openLanding(page);
  await scrollInto(page, "#faq", 100);
  await expect(page.locator(".drag-overlay [data-dragnode]").first()).toBeAttached({ timeout: 10_000 });

  await page.setViewportSize({ width: VW, height: VH });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(2_000);
  await expect(page.locator(".drag-shell")).toBeHidden();
  const stray = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".drag-overlay [data-dragnode]")).filter((n) => {
      const r = n.getBoundingClientRect();
      return getComputedStyle(n).visibility !== "hidden" && r.width > 0 && r.height > 0;
    }).length,
  );
  expect(stray).toBe(0);
});

test("faq, journal and newsletter stack into one column", async ({ page }) => {
  await openLanding(page);

  const intro = await page.locator(".ld-faq-intro").boundingBox();
  const accordion = await page.locator(".ld-faq-intro + *").boundingBox();
  expect(accordion!.y).toBeGreaterThanOrEqual(intro!.y + intro!.height - 1);

  const cards = page.locator(".ld-journal-cards > *");
  const c0 = await cards.nth(0).boundingBox();
  const c1 = await cards.nth(1).boundingBox();
  expect(c1!.y).toBeGreaterThanOrEqual(c0!.y + c0!.height - 1);
  expect(c0!.width).toBeGreaterThan(300);

  const input = await page.locator(".ld-newsletter-form input").boundingBox();
  const button = await page.locator(".ld-newsletter-form button").boundingBox();
  expect(input!.width).toBeGreaterThan(300);
  expect(input!.x + input!.width).toBeLessThanOrEqual(VW);
  expect(button!.y).toBeGreaterThanOrEqual(input!.y + input!.height - 1);
});

test("the beta dialog fits the phone and leads with the form", async ({ page }) => {
  await openLanding(page);
  await page.getByRole("button", { name: "Sign up for Beta Testing" }).first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box!.width).toBeLessThanOrEqual(VW);
  expect(box!.height).toBeLessThanOrEqual(VH);
  await expect(dialog.getByLabel("Email address")).toBeInViewport();
  // the brand panel is tablet-and-up; the form is the action
  await expect(page.locator(".ld-beta-left")).toBeHidden();
});
