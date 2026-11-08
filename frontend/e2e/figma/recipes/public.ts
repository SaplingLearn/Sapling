/**
 * 05 — landing + public pages (docs/figma/inventory/05-public-pages.md).
 *
 * Every recipe runs signed out (`persona: "public"`).
 *
 * Landing scroll acts. The engine (lib/landing/engine/index.ts) scrubs each
 * act off a SMOOTHED scroll position and latches progress only on frames that
 * move DOWN the page, so two ways in are used:
 *   - `jumpAct`: one `scrollTo` from the top. When that move is > 3vh the
 *     engine's smoothing bypasses itself (`jumping`), so the act latches the
 *     exact progress asked for on that single downward frame.
 *   - `scrub`: an in-page rAF loop that nudges the page down a few px a frame
 *     until a DOM condition the engine writes (caption opacity, tile counts,
 *     the act fold) holds — used where the target is < 3vh from the top
 *     (act I's first captions), where a jump would only lerp and never latch.
 * Either way the act then holds (no further downward frames), so the harness
 * captures exactly the state asserted.
 */
import { expect, type Page } from "@playwright/test";

import { hold, mockError, mockJson, text } from "../helpers";
import type { Recipe, RecipeBook } from "../types";

const T = 30_000;
const SUBSCRIBE = "/api/newsletter/subscribe";

// ── landing helpers ──────────────────────────────────────────────────────

/** Load `/` and wait out the intro overlay + hero scramble. */
async function openLanding(page: Page): Promise<void> {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#act-graph canvas")).toBeAttached({ timeout: T });
  await expect(page.locator('h1[aria-label="Sapling"]')).toHaveText("Sapling", { timeout: T });
  await text(page, "Grow Your Knowledge");
  // overlay drops from the tree 900ms after the hero mounts; the engine also
  // needs a measure pass (600ms throttle) before it can drive the acts
  await page.waitForTimeout(1_500);
}

/** Jump straight to `p` (0..1) through an act's scrub runway. See file header. */
async function jumpAct(page: Page, id: string, p: number): Promise<void> {
  await page.evaluate(
    ({ id, p }) => {
      const sec = document.getElementById(id);
      if (!sec) throw new Error(`#${id} missing`);
      const top = sec.getBoundingClientRect().top + window.scrollY;
      const runway = Math.max(0, sec.offsetHeight - window.innerHeight);
      window.scrollTo(0, top + p * runway);
    },
    { id, p },
  );
  await page.waitForTimeout(1_200);
}

type Until =
  | { kind: "opaque"; sel: string }
  | { kind: "folded"; sel: string };

/** Nudge the page down a few px per frame until `until` holds. See file header. */
async function scrub(page: Page, startId: string, until: Until): Promise<void> {
  await page.evaluate((id) => {
    const sec = document.getElementById(id);
    if (!sec) throw new Error(`#${id} missing`);
    window.scrollTo(0, sec.getBoundingClientRect().top + window.scrollY - 2);
  }, startId);
  // let the engine's smoothed scroll converge before walking (no latching
  // happens meanwhile: the page is not moving down)
  await page.waitForTimeout(2_500);
  await page.evaluate(
    (u) =>
      new Promise<void>((resolve, reject) => {
        const done = () => {
          const el = document.querySelector<HTMLElement>(u.sel);
          if (!el) return false;
          if (u.kind === "folded") return el.style.height === "100vh";
          // Walk until fully opaque: progress latches only while the page moves
          // down, so stopping at the engine's "0.99" frame froze the caption
          // there. Every caption window has a wide opacity-1 plateau.
          return parseFloat(el.style.opacity || "0") >= 1;
        };
        const deadline = performance.now() + 40_000;
        const step = () => {
          if (done()) return resolve();
          if (performance.now() > deadline) return reject(new Error(`scrub timed out: ${u.sel}`));
          window.scrollBy(0, 8);
          requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }),
    until,
  );
  await page.waitForTimeout(1_200);
}

/** Scroll a landing section's top into view (a jump; the acts above don't latch). */
async function toSection(page: Page, sel: string, offset = 0): Promise<void> {
  await page.evaluate(
    ({ sel, offset }) => {
      const el = document.querySelector(sel);
      if (!el) throw new Error(`${sel} missing`);
      window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY + offset);
    },
    { sel, offset },
  );
  // FadeIn reveals + the sticky DragField clusters settle
  await page.waitForTimeout(1_500);
}

function actGraphCap(i: number): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await scrub(page, "act-graph", { kind: "opaque", sel: `[data-cap="${i}"]` });
      await expect(page.locator(`[data-cap="${i}"]`)).toHaveCSS("opacity", "1", { timeout: T });
      await expect(page.locator(`[data-tick="${i}"]`)).toHaveCSS("height", "38px", { timeout: T });
    },
  };
}

/** Finish act I (it folds to 100vh), then click the canvas into explore mode. */
async function enterExplore(page: Page): Promise<void> {
  await openLanding(page);
  await jumpAct(page, "act-graph", 1);
  await expect
    .poll(() => page.evaluate(() => document.getElementById("act-graph")?.style.height), { timeout: T })
    .toBe("100vh");
  await page.waitForTimeout(800);
  const canvas = page.locator("#act-graph canvas");
  const box = await canvas.boundingBox();
  if (!box) throw new Error("act canvas has no box");
  await canvas.click({ position: { x: box.width / 2, y: box.height / 2 } });
  await expect(page.locator(".ld-hud")).toBeVisible({ timeout: T });
  await expect(page.getByRole("button", { name: /EXIT EXPLORE/ })).toBeVisible({ timeout: T });
  // camera glide + the HUD's delayed fade-in
  await page.waitForTimeout(2_000);
}

function ingest(p: number, check: (page: Page) => Promise<void>): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await jumpAct(page, "act-ingest", p);
      await expect(page.locator("#act-ingest h2")).toBeVisible({ timeout: T });
      await check(page);
    },
  };
}

async function tileCounts(page: Page): Promise<string[]> {
  return page.locator("[data-tilecount]").allTextContents();
}

function tutorFace(p: number, face: number): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await jumpAct(page, "act-tutor", p);
      await page.waitForTimeout(2_000); // the prism eases onto its face
      await expect(page.locator(`[data-tcap="${face}"]`)).toHaveCSS("opacity", "1", { timeout: T });
    },
  };
}

function tutorPill(label: string, face: number): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await jumpAct(page, "act-tutor", 0.93);
      await expect(page.locator("[data-tutor-pills]")).toHaveCSS("opacity", "1", { timeout: T });
      await page.locator("[data-tutor-pills] button", { hasText: label }).click();
      await page.waitForTimeout(3_500); // docked glide is the slow one (0.028/frame)
      await expect(page.locator(`[data-tcap="${face}"]`)).toHaveCSS("opacity", "1", { timeout: T });
    },
  };
}

const LAB_TITLES = [
  "Quizzes that meet you where you struggle.",
  "Cards that know when you’ll forget.",
  "Notes that feed the graph.",
  "A study guide built from your gaps.",
  "Learn next to your classmates.",
  "Your real grade, always current.",
  "Paste a syllabus. Get a semester.",
  "It asks. You answer.",
];

/** Open the feature lab from a gallery card, then pick tool `i` on its rail. */
function lab(i: number): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await toSection(page, "#gallery");
      const track = page.locator("[data-set-size]").first();
      const tb = await track.boundingBox();
      if (!tb) throw new Error("gallery rail has no box");
      // hovering the rail pauses the marquee, so the card holds still to click
      await page.mouse.move(720, tb.y + tb.height / 2);
      await page.waitForTimeout(400);
      const pt = await track.evaluate((el) => {
        const cards = Array.from(el.querySelectorAll<HTMLElement>("[data-tk]"));
        for (const c of cards) {
          const r = c.getBoundingClientRect();
          if (r.left > 20 && r.right < window.innerWidth - 20) {
            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
          }
        }
        return null;
      });
      if (!pt) throw new Error("no gallery card fully on screen");
      await page.mouse.click(pt.x, pt.y);
      await expect(page.locator(".ld-labclose")).toBeVisible({ timeout: T });
      await page.waitForTimeout(900);
      await page.locator(`[data-rail="${i}"]`).click();
      await page.waitForTimeout(1_200);
      await expect(page.locator(`[data-rail="${i}"]`)).toHaveCSS("background-color", "rgb(68, 93, 34)", { timeout: T });
      await expect(page.locator(".ld-lab-copy h3")).toHaveText(LAB_TITLES[i], { timeout: T });
    },
  };
}

async function openBeta(page: Page): Promise<void> {
  await openLanding(page);
  await page.getByRole("button", { name: /Sign up for Beta Testing/ }).first().click();
  await expect(page.locator(".ld-betacard")).toBeVisible({ timeout: T });
  await page.waitForTimeout(500);
}

async function betaSubmit(page: Page, email: string): Promise<void> {
  await page.locator(".ld-betainput").fill(email);
  await page.locator(".ld-betasubmit").click();
}

async function toNewsletter(page: Page): Promise<void> {
  await openLanding(page);
  await toSection(page, ".ld-newsletter", -250);
  await expect(page.locator(".ld-newsletter")).toBeVisible({ timeout: T });
}

async function newsletterSubmit(page: Page, email: string): Promise<void> {
  await page.locator(".ld-newsletter .ld-emailinput").fill(email);
  await page.locator(".ld-newsletter button[type=submit]").click();
}

/**
 * Stub the Google popup and record each sign-in BroadcastChannel name, so a
 * recipe can hold "waiting" with no real window and answer it in-page.
 */
async function stubSignInPopup(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __bcNames: string[] };
    w.__bcNames = [];
    const Orig = window.BroadcastChannel;
    window.BroadcastChannel = class extends Orig {
      constructor(name: string) {
        super(name);
        w.__bcNames.push(name);
      }
    };
    window.open = (() => ({ closed: false, focus() {}, close() {} })) as unknown as typeof window.open;
  });
}

async function signInWaiting(page: Page): Promise<void> {
  await stubSignInPopup(page);
  await openLanding(page);
  await page.locator(".ld-nav-signin").click();
  await expect(page.getByTestId("signin-modal")).toBeVisible({ timeout: T });
  await page.getByTestId("signin-google-button").click();
  await expect(page.getByTestId("signin-google-button")).toHaveText(/Waiting for Google/, { timeout: T });
}

const SIGNIN_ERRORS: Record<string, RegExp> = {
  not_approved: /pending approval/,
  invalid_domain: /approved school accounts/,
  signin_failed: /Sign-in failed/,
  session_expired: /session has expired/,
  oauth_denied: /Sign-in was cancelled/,
  env_misconfig: /misconfigured/,
  revoked: /access has been revoked/,
  google_not_configured: /not configured on the server/,
  unknown: /Something went wrong\. Please try again/,
};

function signInError(code: string): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await signInWaiting(page);
      await page.evaluate((error) => {
        const names = (window as unknown as { __bcNames: string[] }).__bcNames;
        const name = names.filter((n) => n.startsWith("sapling_signin:")).pop();
        if (!name) throw new Error("no sign-in channel opened");
        const ch = new BroadcastChannel(name);
        ch.postMessage({ type: "sapling_signin", success: false, error });
        setTimeout(() => ch.close(), 500);
      }, code);
      await expect(page.getByTestId("signin-error")).toHaveText(SIGNIN_ERRORS[code], { timeout: T });
      await expect(page.getByTestId("signin-google-button")).toHaveText(/Continue with Google/);
    },
  };
}

// ── companion helpers ────────────────────────────────────────────────────

async function openCompanion(page: Page, path: string, h1: string | RegExp): Promise<void> {
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await expect(page.locator("main h1").first()).toHaveText(h1, { timeout: T });
  await page.waitForTimeout(1_600); // the staggered fadeUp entrances
}

function page404(path: string): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      const res = await page.goto(path, { waitUntil: "domcontentloaded" });
      expect(res?.status()).toBe(404);
      await text(page, /could not be found/i);
    },
  };
}

function galleryFilter(label: string, n: number): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/gallery", "Gallery");
      await page.getByRole("button", { name: label, exact: true }).click();
      await page.waitForTimeout(1_200);
      await expect(page.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator("main figure")).toHaveCount(n, { timeout: T });
    },
  };
}

const NEWS_CARDS = 'main a[href^="/news/"]';

function newsFilter(label: string, n: number): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/news", "News");
      await page.locator('button[aria-haspopup="listbox"]').click();
      await page.getByRole("option", { name: label }).click();
      await expect(page.locator('button[aria-haspopup="listbox"]')).toHaveText(label, { timeout: T });
      await expect(page.locator(NEWS_CARDS)).toHaveCount(n, { timeout: T });
      await page.waitForTimeout(600);
    },
  };
}

function article(slug: string): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await page.goto(`/news/${slug}`, { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("link", { name: /The Journal/ }).first()).toBeVisible({ timeout: T });
      await expect(page.locator("main h1")).toBeVisible({ timeout: T });
      await expect(page.locator("main article")).toBeVisible({ timeout: T });
      await page.waitForTimeout(1_200); // hero image / motif paint
    },
  };
}

const WIKI_LINKS = 'nav[aria-label="Contents"] a';

async function openWiki(page: Page): Promise<void> {
  await openCompanion(page, "/wiki", "Wiki");
}

function landingAt(sel: string, check: (page: Page) => Promise<void>, offset = 0): Recipe {
  return {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await toSection(page, sel, offset);
      await check(page);
    },
  };
}

// ── the book ─────────────────────────────────────────────────────────────

export const RECIPES_PUBLIC: RecipeBook = {
  // ═══ landing: intro, hero, nav ═══
  "landing/intro-loading": {
    persona: "public",
    run: async (page) => {
      // hold the overlay: drop the one 1900ms timer (INTRO_MS) that mounts the hero
      await page.addInitScript(() => {
        const orig = window.setTimeout;
        window.setTimeout = ((handler: TimerHandler, ms?: number, ...args: unknown[]) =>
          ms === 1900 ? 0 : orig(handler, ms, ...args)) as typeof window.setTimeout;
      });
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("LOADING", { exact: true })).toBeVisible({ timeout: T });
      await text(page, /^100$/); // the counter tops out while held
      await page.waitForTimeout(1_000); // the sprout finishes growing (2.4s)
      await expect(page.locator('h1[aria-label="Sapling"]')).toHaveText("");
    },
  },
  "landing/hero-rest": {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await expect(page.locator(".floating-card").first()).toBeVisible({ timeout: T });
      await expect(page.getByRole("button", { name: /Sign up for Beta Testing/ }).first()).toBeVisible();
    },
  },
  "landing/nav-visible": {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      // down past half a viewport hides it; any upward scroll brings it back
      await page.evaluate(() => window.scrollTo(0, 700));
      await page.waitForTimeout(500);
      await page.evaluate(() => window.scrollTo(0, 350));
      await page.waitForTimeout(800);
      await expect
        .poll(() => page.locator(".sapling-nav").evaluate((n) => (n as HTMLElement).style.transform), { timeout: T })
        // useLanding writes 'translateY(0)'; the CSSOM reads it back as 0px.
        .toMatch(/^translateY\(0(px)?\)$/);
      await expect(page.locator(".ld-nav-signin")).toBeVisible();
    },
  },
  "landing/nav-hidden": {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await page.evaluate(() => window.scrollTo(0, 700));
      await page.waitForTimeout(800);
      await expect
        .poll(() => page.locator(".sapling-nav").evaluate((n) => (n as HTMLElement).style.transform), { timeout: T })
        .toBe("translateY(-100%)");
    },
  },

  // ═══ Act I — graph ═══
  "landing/act-graph-cap0": actGraphCap(0),
  "landing/act-graph-cap1": actGraphCap(1),
  "landing/act-graph-cap2": actGraphCap(2),
  "landing/act-graph-cap3-closing": {
    persona: "public",
    run: async (page) => {
      await actGraphCap(3).run(page);
      await expect(page.locator('[data-cap="3"]')).toContainText("CLICK TO EXPLORE");
    },
  },
  "landing/explore-idle": {
    persona: "public",
    run: async (page) => {
      await enterExplore(page);
      await expect(page.locator(".ld-hud-legend")).toBeVisible();
      await expect(page.locator(".ld-hud-inspector")).toHaveCount(0);
    },
  },
  "landing/explore-node-selected": {
    persona: "public",
    run: async (page) => {
      await enterExplore(page);
      const box = await page.locator("#act-graph canvas").boundingBox();
      if (!box) throw new Error("act canvas has no box");
      const cx = box.x + box.width / 2;
      const cy = box.y + box.height / 2;
      // node positions are random per load: spiral out from the centre (the
      // course root sits there) until a click lands on a concept
      const pts: [number, number][] = [[cx, cy]];
      for (let r = 24; r <= 320; r += 24) {
        for (let a = 0; a < 12; a++) {
          const t = (a / 12) * Math.PI * 2;
          pts.push([cx + Math.cos(t) * r, cy + Math.sin(t) * r * 0.8]);
        }
      }
      const inspector = page.locator(".ld-hud-inspector");
      for (const [x, y] of pts) {
        await page.mouse.click(x, y);
        await page.waitForTimeout(120);
        if ((await inspector.count()) > 0) break;
      }
      await expect(inspector).toBeVisible({ timeout: T });
      await expect(page.getByRole("button", { name: "Quiz me on this" })).toBeVisible();
      await page.mouse.move(0, 0);
      await page.waitForTimeout(800);
    },
  },
  "landing/explore-zoomed": {
    persona: "public",
    run: async (page) => {
      await enterExplore(page);
      const box = await page.locator("#act-graph canvas").boundingBox();
      if (!box) throw new Error("act canvas has no box");
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      for (let i = 0; i < 10; i++) {
        await page.mouse.wheel(0, -100); // ×1.08 per notch → ~2.2×
        await page.waitForTimeout(60);
      }
      await page.waitForTimeout(800);
      await expect(page.locator(".ld-hud")).toBeVisible();
      await expect(page.getByRole("button", { name: /EXIT EXPLORE/ })).toBeVisible();
    },
  },

  // ═══ Act II — ingest ═══
  // p=0.05, not 0: at 0 act I's bottom edge is still on screen and folds on
  // the jump frame, which abandons the frame that would have latched act II
  "landing/act-ingest-start": ingest(0.05, async (page) => {
    await expect.poll(() => tileCounts(page), { timeout: T }).toEqual(["+0", "+0", "+0", "+0"]);
  }),
  "landing/act-ingest-flying": ingest(0.4, async (page) => {
    // chips 0–1 have landed, 3–5 are mid-arc
    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              Array.from(document.querySelectorAll<HTMLElement>("[data-chip]")).filter(
                (c) => parseFloat(c.style.opacity || "0") > 0.5,
              ).length,
          ),
        { timeout: T },
      )
      .toBeGreaterThan(0);
    await expect.poll(() => tileCounts(page), { timeout: T }).not.toEqual(["+0", "+0", "+0", "+0"]);
  }),
  "landing/act-ingest-end": ingest(0.97, async (page) => {
    await expect.poll(() => tileCounts(page), { timeout: T }).toEqual(["+3", "+3", "+3", "+3"]);
  }),

  // ═══ Act III — tutor ═══
  "landing/act-tutor-socratic": tutorFace(0.1, 0),
  "landing/act-tutor-expository": tutorFace(0.42, 1),
  "landing/act-tutor-teachback": tutorFace(0.76, 2),
  "landing/act-tutor-docked-pills": {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await jumpAct(page, "act-tutor", 0.93);
      await expect(page.locator("[data-tutor-pills]")).toHaveCSS("opacity", "1", { timeout: T });
      await expect(page.locator("[data-tutor-pills] button")).toHaveCount(3);
    },
  },
  "landing/act-tutor-pill-socratic": tutorPill("SOCRATIC", 0),
  "landing/act-tutor-pill-expository": tutorPill("EXPOSITORY", 1),
  "landing/act-tutor-pill-teachback": tutorPill("TEACHBACK", 2),

  // ═══ gallery + feature lab ═══
  "landing/gallery-rest": landingAt("#gallery", async (page) => {
    await expect(page.locator("#gallery h2")).toContainText("The rest of the", { timeout: T });
    await expect(page.locator(".ld-galcard").first()).toBeVisible({ timeout: T });
  }),
  "landing/lab-quiz": lab(0),
  "landing/lab-flashcards": lab(1),
  "landing/lab-notetaker": lab(2),
  "landing/lab-guide": lab(3),
  "landing/lab-rooms": lab(4),
  "landing/lab-gradebook": lab(5),
  "landing/lab-calendar": lab(6),
  "landing/lab-tutor": lab(7),

  // ═══ FAQ ═══
  "landing/faq-default": landingAt("#faq", async (page) => {
    await expect(page.locator("#faq button[aria-expanded]").first()).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator("#faq h2")).toContainText("Honest answers about", { timeout: T });
  }),
  // n = 2 (a representative item past the default-open first one)
  "landing/faq-item-n-open": landingAt("#faq", async (page) => {
    const btns = page.locator("#faq button[aria-expanded]");
    await btns.nth(2).click();
    await page.waitForTimeout(700);
    await expect(btns.nth(2)).toHaveAttribute("aria-expanded", "true");
    await expect(btns.nth(0)).toHaveAttribute("aria-expanded", "false");
  }),
  "landing/faq-all-closed": landingAt("#faq", async (page) => {
    const btns = page.locator("#faq button[aria-expanded]");
    await btns.nth(0).click();
    await page.waitForTimeout(700);
    await expect(page.locator('#faq button[aria-expanded="true"]')).toHaveCount(0);
  }),

  // ═══ journal + newsletter ═══
  "landing/journal-rest": landingAt("#newsletter", async (page) => {
    await expect(page.locator(".ld-post")).toHaveCount(3);
    await expect(page.locator(".ld-post").first()).toBeVisible({ timeout: T });
  }),
  "landing/newsletter-idle": {
    persona: "public",
    run: async (page) => {
      await toNewsletter(page);
      await expect(page.locator(".ld-newsletter button[type=submit]")).toHaveText("Join the list");
    },
  },
  "landing/newsletter-invalid-noop": {
    persona: "public",
    run: async (page) => {
      await mockJson(page, SUBSCRIBE, { ok: true }, { method: "POST" }); // must never be hit
      await toNewsletter(page);
      await newsletterSubmit(page, "not-an-email");
      await page.waitForTimeout(500);
      await expect(page.locator(".ld-newsletter .ld-emailinput")).toHaveValue("not-an-email");
      await expect(page.locator(".ld-newsletter button[type=submit]")).toHaveText("Join the list");
      await expect(page.locator(".ld-newsletter [role=alert]")).toHaveCount(0);
    },
  },
  "landing/newsletter-submitting": {
    persona: "public",
    run: async (page) => {
      await hold(page, SUBSCRIBE, "POST");
      await toNewsletter(page);
      await newsletterSubmit(page, "figma.capture@example.com");
      await expect(page.locator(".ld-newsletter button[type=submit]")).toHaveText(/Signing you up/, { timeout: T });
    },
  },
  "landing/newsletter-error": {
    persona: "public",
    run: async (page) => {
      await mockError(page, SUBSCRIBE, 500, "Internal Server Error", "POST");
      await toNewsletter(page);
      await newsletterSubmit(page, "figma.capture@example.com");
      await expect(page.locator(".ld-newsletter [role=alert]")).toBeVisible({ timeout: T });
    },
  },
  "landing/newsletter-success": {
    persona: "public",
    run: async (page) => {
      await mockJson(page, SUBSCRIBE, { ok: true }, { method: "POST" });
      await toNewsletter(page);
      await newsletterSubmit(page, "figma.capture@example.com");
      await expect(page.locator(".ld-newsletter")).toContainText(/on the\s*tree/, { timeout: T });
    },
  },

  // ═══ closing ═══
  "landing/cta": landingAt("#cta", async (page) => {
    await expect(page.locator("#cta h2")).toContainText("Ready to", { timeout: T });
    await expect(page.locator("#cta button")).toBeVisible();
  }, -60),
  "landing/footer": {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await page.waitForTimeout(1_500);
      await expect(page.locator(".ld-footer")).toBeInViewport({ timeout: T });
      await expect(page.locator(".ld-footer").getByRole("link", { name: "Privacy Policy" })).toBeVisible();
    },
  },

  // ═══ beta modal ═══
  "landing/beta-modal-form": {
    persona: "public",
    run: async (page) => {
      await openBeta(page);
      await expect(page.getByRole("dialog")).toContainText("Join the");
      await expect(page.locator(".ld-betasubmit")).toHaveText(/Join the Waitlist/);
    },
  },
  "landing/beta-modal-validation": {
    persona: "public",
    run: async (page) => {
      await openBeta(page);
      await betaSubmit(page, "abc");
      await expect(page.locator(".ld-betacard [role=alert]")).toHaveText(/Enter a valid email/, { timeout: T });
    },
  },
  "landing/beta-modal-submitting": {
    persona: "public",
    run: async (page) => {
      await hold(page, SUBSCRIBE, "POST");
      await openBeta(page);
      await betaSubmit(page, "figma.capture@example.com");
      await expect(page.locator(".ld-betasubmit")).toHaveText(/Planting your node/, { timeout: T });
    },
  },
  "landing/beta-modal-error": {
    persona: "public",
    run: async (page) => {
      await mockError(page, SUBSCRIBE, 500, "Internal Server Error", "POST");
      await openBeta(page);
      await betaSubmit(page, "figma.capture@example.com");
      await expect(page.locator(".ld-betacard [role=alert]")).toBeVisible({ timeout: T });
      await expect(page.locator(".ld-betasubmit")).toHaveText(/Join the Waitlist/);
    },
  },
  "landing/beta-modal-success": {
    persona: "public",
    run: async (page) => {
      await mockJson(page, SUBSCRIBE, { ok: true }, { method: "POST" });
      await openBeta(page);
      await betaSubmit(page, "figma.capture@example.com");
      await expect(page.getByRole("dialog")).toContainText(/on the\s*waitlist/, { timeout: T });
    },
  },

  // ═══ sign-in modal ═══
  "landing/signin-modal-idle": {
    persona: "public",
    run: async (page) => {
      await openLanding(page);
      await page.locator(".ld-nav-signin").click();
      await expect(page.getByTestId("signin-modal")).toBeVisible({ timeout: T });
      await expect(page.getByTestId("signin-google-button")).toHaveText(/Continue with Google/);
      await page.waitForTimeout(400);
    },
  },
  "landing/signin-modal-waiting": {
    persona: "public",
    run: async (page) => {
      await signInWaiting(page);
      await expect(page.getByTestId("signin-cancel")).toBeVisible();
    },
  },
  ...Object.fromEntries(
    Object.keys(SIGNIN_ERRORS).map((code) => [`landing/signin-modal-error-${code}`, signInError(code)]),
  ),

  // ═══ companion shell ═══
  "shell/header": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/about", "About Sapling");
      const header = page.locator("header").first();
      await expect(header.getByRole("link", { name: "Sign In" })).toBeVisible();
      await expect(header.getByRole("link", { name: "Get Started" })).toBeVisible();
    },
  },
  "shell/footer": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/about", "About Sapling");
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await page.waitForTimeout(600);
      await expect(page.locator('footer a[aria-current="page"]')).toBeInViewport({ timeout: T });
      await expect(page.locator("footer").getByRole("link", { name: "Careers" })).toBeVisible();
    },
  },

  // ═══ about / careers ═══
  "about/default": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/about", "About Sapling");
      await text(page, /Meet the team/);
    },
  },
  "careers/not-hiring": {
    persona: "public",
    run: async (page) => {
      await page.goto("/careers", { waitUntil: "domcontentloaded" });
      await text(page, "Not hiring right now");
      await page.waitForTimeout(1_600);
    },
  },
  "careers-slug/404": page404("/careers/definitely-not-a-job"),

  // ═══ /faq ═══
  "faq/default": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/faq", "Questions we get");
      await expect(page.locator('button[data-faq="0"]')).toHaveAttribute("aria-expanded", "true");
    },
  },
  // n = 5 (an item in the second group)
  "faq/item-n-open": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/faq", "Questions we get");
      await page.locator('button[data-faq="5"]').click();
      await page.waitForTimeout(600);
      await expect(page.locator('button[data-faq="5"]')).toHaveAttribute("aria-expanded", "true");
      await expect(page.locator('button[data-faq="0"]')).toHaveAttribute("aria-expanded", "false");
    },
  },
  "faq/all-closed": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/faq", "Questions we get");
      await page.locator('button[data-faq="0"]').click();
      await page.waitForTimeout(600);
      await expect(page.locator('button[data-faq][aria-expanded="true"]')).toHaveCount(0);
    },
  },

  // ═══ /gallery ═══
  "gallery/all": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/gallery", "Gallery");
      await expect(page.locator("main figure")).toHaveCount(12);
      await expect(page.getByRole("button", { name: "All screens", exact: true })).toHaveAttribute("aria-pressed", "true");
    },
  },
  "gallery/filter-learn": galleryFilter("Learn", 3),
  "gallery/filter-study": galleryFilter("Study", 4),
  "gallery/filter-together": galleryFilter("Together", 2),
  "gallery/filter-semester": galleryFilter("Semester", 3),
  "gallery/lightbox-open": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/gallery", "Gallery");
      await page.locator('button[aria-label^="Expand "]').first().click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: T });
      await page.waitForTimeout(700);
      await expect(page.getByRole("dialog").getByRole("button", { name: "Close" })).toBeVisible();
    },
  },

  // ═══ /news ═══
  "news/default": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/news", "News");
      await expect(page.locator(NEWS_CARDS)).toHaveCount(7);
    },
  },
  "news/search-typing": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/news", "News");
      await page.getByRole("textbox", { name: "Search posts" }).fill("graph");
      await expect(page.getByRole("button", { name: "Clear search" })).toBeVisible();
      await expect.poll(() => page.locator(NEWS_CARDS).count(), { timeout: T }).toBeLessThan(7);
      await expect(page.locator(NEWS_CARDS).first()).toBeVisible();
    },
  },
  "news/menu-open": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/news", "News");
      await page.locator('button[aria-haspopup="listbox"]').click();
      await expect(page.getByRole("listbox")).toBeVisible({ timeout: T });
      await expect(page.getByRole("option")).toHaveCount(5);
    },
  },
  "news/filter-release": newsFilter("Releases", 2),
  "news/filter-product": newsFilter("Product", 2),
  "news/filter-perspective": newsFilter("Perspective", 2),
  "news/filter-founding": newsFilter("Founding", 1),
  "news/empty": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/news", "News");
      await page.getByRole("textbox", { name: "Search posts" }).fill("zzqxv");
      await text(page, /Nothing matches/);
      await expect(page.getByRole("button", { name: "Clear filters" })).toBeVisible();
      await expect(page.locator(NEWS_CARDS)).toHaveCount(0);
    },
  },

  // ═══ /news/[slug] ═══
  "news-slug/article-photo": article("why-we-built-sapling"),
  "news-slug/article-motif-canopy": article("the-map-we-keep-for-ourselves"),
  "news-slug/article-motif-graph": article("how-the-knowledge-graph-works"),
  "news-slug/article-motif-teachback": article("teachback-is-live"),
  "news-slug/article-motif-spacing": article("what-spacing-actually-buys-you"),
  "news-slug/article-motif-syllabus": article("syllabus-to-semester-in-one-upload"),
  "news-slug/404": page404("/news/definitely-not-a-post"),

  // ═══ legal ═══
  "privacy/default": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/privacy", /Privacy/);
      await expect(page.locator("main h2").first()).toBeVisible();
    },
  },
  "terms/default": {
    persona: "public",
    run: async (page) => {
      await openCompanion(page, "/terms", "Terms of Service");
      await expect(page.locator("main h2").first()).toBeVisible();
    },
  },

  // ═══ /wiki ═══
  "wiki/default": {
    persona: "public",
    run: async (page) => {
      await openWiki(page);
      await expect(page.locator(WIKI_LINKS)).toHaveCount(18);
    },
  },
  "wiki/scrollspy-section-x": {
    persona: "public",
    run: async (page) => {
      await openWiki(page);
      await page.locator("#flashcards").evaluate((el) => el.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(800);
      await expect(page.locator(`${WIKI_LINKS}[aria-current="true"]`)).toHaveAttribute("href", "#flashcards", { timeout: T });
    },
  },
  "wiki/search-filtered": {
    persona: "public",
    run: async (page) => {
      await openWiki(page);
      await page.getByRole("searchbox", { name: "Search the wiki" }).fill("mastery");
      await expect.poll(() => page.locator(WIKI_LINKS).count(), { timeout: T }).toBeLessThan(18);
      await expect(page.locator(WIKI_LINKS).first()).toBeVisible();
    },
  },
  "wiki/search-no-match": {
    persona: "public",
    run: async (page) => {
      await openWiki(page);
      await page.getByRole("searchbox", { name: "Search the wiki" }).fill("zzqxv");
      await expect(page.locator('nav[aria-label="Contents"]')).toContainText(/Nothing matches/, { timeout: T });
      await expect(page.locator(WIKI_LINKS)).toHaveCount(0);
    },
  },
  "wiki/search-cleared": {
    persona: "public",
    run: async (page) => {
      await openWiki(page);
      const box = page.getByRole("searchbox", { name: "Search the wiki" });
      await box.fill("mastery");
      await expect.poll(() => page.locator(WIKI_LINKS).count(), { timeout: T }).toBeLessThan(18);
      await box.fill("");
      await expect(box).toHaveValue("");
      await expect(page.locator(WIKI_LINKS)).toHaveCount(18, { timeout: T });
    },
  },
  "wiki/shot-lightbox": {
    persona: "public",
    run: async (page) => {
      await openWiki(page);
      await page.locator('button[aria-label^="Expand "]').first().click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: T });
      await page.waitForTimeout(700);
      await expect(page.getByRole("dialog").getByRole("button", { name: "Close" })).toBeVisible();
    },
  },

  // ═══ global ═══
  "global/404": page404("/definitely-not-a-page"),
};
