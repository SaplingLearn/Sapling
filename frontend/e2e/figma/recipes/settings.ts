import { expect, type Page, type Route } from "@playwright/test";

import { hold, mockError, mockJson, storage, text, visible } from "../helpers";
import type { Recipe, RecipeBook } from "../types";

/**
 * 04 — /settings, /settings/connections, /admin, /admin/analytics, pre-shell
 * flows (onboarding / pending / setting-up / auth callback) and app chrome.
 *
 * Every write these screens can make is either never confirmed or answered
 * by a mock (with its method), so the shared showcase DB is never mutated.
 */

const ACTIVE = "rich-user-active";
const T = 30_000;

// ── local helpers ───────────────────────────────────────────────────────────

/** Answer matching requests with a handler (pathname+search regex). */
async function routeRe(
  page: Page,
  re: RegExp,
  handler: (route: Route) => Promise<void> | void,
  method?: string,
): Promise<void> {
  await page.route(
    (url) => re.test(url.pathname + url.search),
    async (route) => {
      if (method && route.request().method() !== method) return route.fallback();
      await handler(route);
    },
  );
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

/** Fetch the real response and rewrite its JSON body. */
async function rewriteJson(
  page: Page,
  re: RegExp,
  mutate: (body: Record<string, unknown>) => Record<string, unknown>,
  method = "GET",
): Promise<void> {
  await routeRe(
    page,
    re,
    async (route) => {
      const res = await route.fetch();
      const body = (await res.json()) as Record<string, unknown>;
      await json(route, mutate(body), res.status());
    },
    method,
  );
}

/**
 * Timers with these exact delays never fire (toast auto-dismiss 5s/6s,
 * useConfirm's 3s disarm), so a transient state survives the harness settle.
 * Must run before navigation.
 */
async function pinTimers(page: Page, delays: number[]): Promise<void> {
  await page.addInitScript((ds) => {
    const orig = window.setTimeout.bind(window);
    const patched = ((fn: TimerHandler, ms?: number, ...rest: unknown[]) =>
      typeof ms === "number" && ds.includes(ms)
        ? orig(() => {}, 2_147_483_647)
        : orig(fn, ms, ...rest)) as typeof window.setTimeout;
    window.setTimeout = patched;
  }, delays);
}

/**
 * Swallow every leave/blur event from here on, so a JS hover/focus state
 * (nav hover wash, TopNav dropdown, Tooltip, chart crosshair) survives the
 * harness parking the mouse at (0,0) and blurring focus.
 */
async function freezePointer(page: Page): Promise<void> {
  await page.evaluate(() => {
    for (const t of ["mouseout", "mouseover", "mouseleave", "pointerout", "pointerover", "pointerleave", "focusout", "blur"]) {
      window.addEventListener(t, (e) => e.stopImmediatePropagation(), true);
    }
  });
}

// 1×1 transparent PNG.
const PNG_1PX = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);

const svgUri = (body: string) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">${body}</svg>`)}`;

// ── /settings ───────────────────────────────────────────────────────────────

const SETTINGS_RE = new RegExp(`/api/profile/${ACTIVE}/settings`);
const PROFILE_RE = new RegExp(`/api/profile/${ACTIVE}(\\?|$)`);

async function openSettings(page: Page, tab?: string): Promise<void> {
  await page.goto("/settings");
  await visible(page, "settings-tab-profile");
  // With the settings GET held (data-analytics-unknown) a second Settings tab
  // rail was in the DOM alongside the live one inside nav-feature-gate, so the
  // bare testid hit strict mode. Click the visible copy.
  if (tab) await page.getByTestId(`settings-tab-${tab}`).filter({ visible: true }).first().click();
}

/** Any profile PATCH (a blur-save) is answered locally, never written. */
async function mockProfileSave(page: Page, status = 200): Promise<void> {
  await routeRe(page, PROFILE_RE, (r) => json(r, status === 200 ? { updated: true } : { detail: "Internal Server Error" }, status), "PATCH");
}

async function mockSettingsSave(page: Page): Promise<void> {
  await routeRe(page, SETTINGS_RE, (r) => json(r, {}), "PATCH");
}

async function usernameState(page: Page, check: Record<string, unknown> | "hold", value: string): Promise<void> {
  await mockProfileSave(page);
  if (check === "hold") await hold(page, "/api/profile/username/check");
  else await mockJson(page, "/api/profile/username/check", check);
  await openSettings(page);
  const input = page.locator('input[placeholder="your-handle"]');
  await expect(input).toBeVisible({ timeout: T });
  await input.fill(value);
}

const frame = (id: string, name: string, rarity: string, ring: string) => ({
  id, type: "avatar_frame", name, slug: id, rarity,
  asset_url: svgUri(`<circle cx="32" cy="32" r="29" fill="none" stroke="${ring}" stroke-width="5"/>`),
});
const OWNED_FRAMES = [
  frame("fx-frame-sprout", "Sprout Ring", "common", "#6bcf7f"),
  frame("fx-frame-canopy", "Canopy", "rare", "#4dabf7"),
  frame("fx-frame-ember", "Ember", "epic", "#e8a33a"),
];
const LOCKED_FRAMES = [
  { ...frame("fx-frame-aurora", "Aurora", "legendary", "#b197fc"), owned: false, unlock_source: "achievement:streak-30" },
  { ...frame("fx-frame-oak", "Old Oak", "uncommon", "#8a6d3b"), owned: false, unlock_source: "Finish 10 quizzes" },
];
const emptyCosmetics = () => ({ avatar_frame: [], banner: [], name_color: [], title: [] });

async function mockCosmetics(page: Page, opts: { owned: boolean; catalog: boolean; equipped?: string }): Promise<void> {
  const owned = emptyCosmetics() as Record<string, unknown[]>;
  const catalog = emptyCosmetics() as Record<string, unknown[]>;
  if (opts.owned) owned.avatar_frame = OWNED_FRAMES.map((c) => ({ cosmetic: c, unlocked_at: "2026-03-01T12:00:00Z" }));
  if (opts.catalog) catalog.avatar_frame = [...OWNED_FRAMES.map((c) => ({ ...c, owned: opts.owned, unlock_source: null })), ...LOCKED_FRAMES];
  const equipped = opts.equipped ? { avatar_frame: OWNED_FRAMES.find((f) => f.id === opts.equipped) } : {};
  await routeRe(page, /\/cosmetics(\?|$)/, (r) => json(r, { cosmetics: owned, equipped }), "GET");
  await routeRe(page, /\/cosmetics\/catalog/, (r) => json(r, { catalog }), "GET");
}

/** The analytics switch for an account whose saved opt-out is `optOut`. */
async function analyticsWith(page: Page, optOut: boolean | "unset"): Promise<void> {
  await rewriteJson(page, SETTINGS_RE, (b) => {
    const next = { ...b };
    if (optOut === "unset") delete next.analytics_opt_out;
    else next.analytics_opt_out = optOut;
    return next;
  });
}

const analyticsNote = (page: Page, re: RegExp) =>
  expect(page.getByTestId("settings-analytics-note").filter({ visible: true }).first()).toContainText(re, { timeout: T });

const SETTINGS: RecipeBook = {
  "settings/loading": {
    run: async (page) => {
      await hold(page, SETTINGS_RE, "GET");
      await page.goto("/settings");
      await visible(page, "settings-tab-profile");
      await expect(page.getByText("Change avatar")).toHaveCount(0);
    },
  },
  "settings/load-error": {
    run: async (page) => {
      await mockError(page, SETTINGS_RE, 500, "Internal Server Error", "GET");
      await page.goto("/settings");
      await visible(page, "settings-tab-profile");
      await page.waitForTimeout(1_500);
      await expect(page.getByText("Change avatar")).toHaveCount(0);
    },
  },
  "settings/saving-chip": {
    run: async (page) => {
      await hold(page, SETTINGS_RE, "PATCH");
      await openSettings(page, "notifications");
      await page.getByTestId("settings-toggle-notification_email").click();
      await text(page, "saving…");
    },
  },
  "settings/profile": {
    run: async (page) => {
      await openSettings(page);
      await text(page, "Change avatar");
      await expect(page.locator('input[placeholder="your-handle"]')).toBeVisible({ timeout: T });
    },
  },
  "settings/profile-avatar-uploading": {
    run: async (page) => {
      await hold(page, "/avatar", "POST");
      await openSettings(page);
      await text(page, "Change avatar");
      await page.locator('input[type="file"][accept="image/*"]').first()
        .setInputFiles({ name: "avatar.png", mimeType: "image/png", buffer: PNG_1PX });
      await text(page, "Uploading…");
    },
  },
  "settings/profile-avatar-error": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockError(page, "/avatar", 500, "Storage unavailable", "POST");
      await openSettings(page);
      await text(page, "Change avatar");
      await page.locator('input[type="file"][accept="image/*"]').first()
        .setInputFiles({ name: "avatar.png", mimeType: "image/png", buffer: PNG_1PX });
      await text(page, /Upload failed/);
    },
  },
  "settings/profile-username-checking": {
    run: async (page) => {
      await usernameState(page, "hold", "maya_ellis_2");
      await expect(page.locator('input[placeholder="your-handle"]')).toHaveValue("maya_ellis_2");
    },
  },
  "settings/profile-username-available": {
    run: async (page) => {
      await usernameState(page, { available: true }, "maya_ellis_2");
      await text(page, "Available");
    },
  },
  "settings/profile-username-taken": {
    run: async (page) => {
      await usernameState(page, { available: false, reason: "taken" }, "jordan");
      await text(page, "Already taken");
    },
  },
  "settings/profile-username-invalid": {
    run: async (page) => {
      await usernameState(page, { available: false, reason: "invalid" }, "M!");
      await text(page, /3–24 chars/);
    },
  },
  "settings/profile-save-error": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockProfileSave(page, 500);
      await openSettings(page);
      const field = page.locator(".settings-field-row").filter({ hasText: "Display name" }).locator("input");
      await expect(field).toBeVisible({ timeout: T });
      await field.fill("Maya E.");
      await field.press("Tab");
      await text(page, /Couldn't save/);
    },
  },
  "settings/preview-modal": {
    run: async (page) => {
      await openSettings(page);
      await text(page, "Change avatar");
      await page.getByRole("button", { name: /Preview profile/ }).click();
      await text(page, "Profile preview");
    },
  },
  "settings/preview-error": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await openSettings(page);
      await text(page, "Change avatar");
      await routeRe(page, PROFILE_RE, (r) => json(r, { detail: "Internal Server Error" }, 500), "GET");
      await page.getByRole("button", { name: /Preview profile/ }).click();
      await text(page, /Couldn't load preview/);
    },
  },
  "settings/cosmetics-owned": {
    run: async (page) => {
      await mockCosmetics(page, { owned: true, catalog: true });
      await openSettings(page, "cosmetics");
      await text(page, "Sprout Ring");
      await text(page, "Owned · 3");
    },
  },
  "settings/cosmetics-owned-empty": {
    run: async (page) => {
      await mockCosmetics(page, { owned: false, catalog: true });
      await openSettings(page, "cosmetics");
      await text(page, "No frames unlocked yet.");
    },
  },
  "settings/cosmetics-catalog": {
    run: async (page) => {
      await mockCosmetics(page, { owned: true, catalog: true, equipped: "fx-frame-canopy" });
      await openSettings(page, "cosmetics");
      await page.getByRole("button", { name: /^Catalog · / }).click();
      await text(page, "🔒 locked");
      await text(page, /2 locked · earn achievements/);
    },
  },
  "settings/cosmetics-catalog-empty": {
    run: async (page) => {
      await mockCosmetics(page, { owned: false, catalog: false });
      await openSettings(page, "cosmetics");
      await page.getByRole("button", { name: /^Catalog · / }).click();
      await text(page, "Nothing in the catalog yet.");
    },
  },
  "settings/cosmetics-equipped": {
    run: async (page) => {
      await mockCosmetics(page, { owned: true, catalog: true, equipped: "fx-frame-canopy" });
      await openSettings(page, "cosmetics");
      await expect(page.getByRole("button", { name: "Unequip" })).toBeVisible({ timeout: T });
    },
  },
  "settings/cosmetics-busy": {
    run: async (page) => {
      await mockCosmetics(page, { owned: true, catalog: true });
      await hold(page, "/equip", "POST");
      await openSettings(page, "cosmetics");
      const equip = page.getByRole("button", { name: "Equip", exact: true });
      await expect(equip.first()).toBeVisible({ timeout: T });
      await equip.first().click();
      await expect(equip.nth(1)).toBeDisabled();
    },
  },
  "settings/preferences": {
    run: async (page) => {
      await openSettings(page, "preferences");
      await text(page, "Accent color");
    },
  },
  "settings/preferences-accent-active": {
    run: async (page) => {
      await mockSettingsSave(page);
      await openSettings(page, "preferences");
      await page.getByRole("button", { name: "Accent #8a63d2" }).click();
      await expect(page.getByRole("button", { name: "Accent #8a63d2" })).toHaveCSS("outline-style", "solid");
    },
  },
  "settings/notifications": {
    run: async (page) => {
      await openSettings(page, "notifications");
      await visible(page, "settings-toggle-notification_email");
    },
  },
  "settings/data": {
    run: async (page) => {
      await openSettings(page, "data");
      await visible(page, "settings-analytics");
      await text(page, "Danger Zone");
    },
  },
  "settings/data-export-success": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockJson(page, "/export", { sessions: [], notes: [], graph: { nodes: [], edges: [] } }, { method: "POST" });
      await openSettings(page, "data");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      await text(page, "Data exported.");
    },
  },
  "settings/data-export-error": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockError(page, "/export", 500, "Internal Server Error", "POST");
      await openSettings(page, "data");
      await page.getByRole("button", { name: "Export", exact: true }).click();
      await text(page, /Export failed/);
    },
  },
  "settings/data-analytics-unknown": {
    run: async (page) => {
      await hold(page, SETTINGS_RE, "GET");
      await openSettings(page, "data");
      await analyticsNote(page, /Loading your saved setting/);
    },
  },
  "settings/data-analytics-unreadable": {
    run: async (page) => {
      await mockError(page, SETTINGS_RE, 500, "Internal Server Error", "GET");
      await openSettings(page, "data");
      await analyticsNote(page, /couldn't load your saved setting/);
      await visible(page, "settings-analytics-reload");
    },
  },
  "settings/data-analytics-unset": {
    run: async (page) => {
      await analyticsWith(page, "unset");
      await openSettings(page, "data");
      await analyticsNote(page, /No choice is saved/);
    },
  },
  "settings/data-analytics-on": {
    run: async (page) => {
      await analyticsWith(page, false);
      await openSettings(page, "data");
      await analyticsNote(page, /^On — saved to your account, so it applies/);
    },
  },
  "settings/data-analytics-on-browser-blocked": {
    run: async (page) => {
      await page.addInitScript(() => {
        Object.defineProperty(Navigator.prototype, "doNotTrack", { get: () => "1", configurable: true });
      });
      await analyticsWith(page, false);
      await openSettings(page, "data");
      await analyticsNote(page, /Do Not Track or Global Privacy Control/);
    },
  },
  "settings/data-analytics-off": {
    run: async (page) => {
      await analyticsWith(page, true);
      await openSettings(page, "data");
      await analyticsNote(page, /^Off — saved to your account/);
    },
  },
  "settings/data-analytics-off-unsaved": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await analyticsWith(page, false);
      await mockError(page, SETTINGS_RE, 500, "Internal Server Error", "PATCH");
      await openSettings(page, "data");
      await analyticsNote(page, /^On/);
      await page.getByTestId("settings-analytics-toggle").click();
      await analyticsNote(page, /for this visit only/);
      await visible(page, "settings-analytics-retry");
    },
  },
  "settings/data-analytics-saving": {
    run: async (page) => {
      await analyticsWith(page, false);
      await hold(page, SETTINGS_RE, "PATCH");
      await openSettings(page, "data");
      await analyticsNote(page, /^On/);
      await page.getByTestId("settings-analytics-toggle").click();
      await expect(page.getByTestId("settings-analytics-toggle")).toBeDisabled();
    },
  },
};

// ── /settings/connections ──────────────────────────────────────────────────

const GS = "/api/gradescope/status";
const CONNECTIONS: RecipeBook = {
  "connections/checking": {
    run: async (page) => {
      await hold(page, GS);
      await page.goto("/settings/connections");
      await text(page, /Checking…/i);
    },
  },
  "connections/not-connected": {
    run: async (page) => {
      await mockJson(page, GS, { has_credentials: false, auth_mode: null, last_synced_at: null });
      await page.goto("/settings/connections");
      await text(page, /Not connected/i);
      await expect(page.getByRole("button", { name: "Connect", exact: true })).toBeEnabled();
    },
  },
  "connections/connected-password": {
    run: async (page) => {
      await mockJson(page, GS, { has_credentials: true, auth_mode: "password", last_synced_at: "2026-03-10T14:20:00Z" });
      await page.goto("/settings/connections");
      await text(page, /Credentials saved · password/i);
      await text(page, /Last sync ·/);
    },
  },
  "connections/connected-sso": {
    run: async (page) => {
      await mockJson(page, GS, { has_credentials: true, auth_mode: "cookies", last_synced_at: "2026-03-09T09:05:00Z" });
      await page.goto("/settings/connections");
      await text(page, /session cookies \(SSO\)/i);
    },
  },
  "connections/status-error": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockError(page, GS, 500);
      await page.goto("/settings/connections");
      await text(page, /Couldn't load Gradescope status/);
      await text(page, /Not connected/i);
    },
  },
  "connections/sync-modal": {
    run: async (page) => {
      await mockJson(page, GS, { has_credentials: false, auth_mode: null, last_synced_at: null });
      await page.goto("/settings/connections");
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: T });
    },
  },
};

// ── /admin ──────────────────────────────────────────────────────────────────

const role = (id: string, name: string, slug: string, color: string, icon: string | null, priority: number) => ({
  id, name, slug, color, icon, description: `${name} role`, is_staff_assigned: true, is_earnable: false, display_priority: priority,
});
const R_ADMIN = role("fx-role-admin", "Admin", "admin", "#c2410c", "🛡️", 100);
const R_TA = role("fx-role-ta", "Teaching Assistant", "ta", "#2b8c96", "🎓", 50);
const R_BETA = role("fx-role-beta", "Beta Tester", "beta", "#8a63d2", "🧪", 10);

const USERS = [
  { id: "rich-user-admin", name: "Ada Admin", email: "ada.admin@bu.edu", is_approved: true, is_admin: true, last_sign_in_at: "2026-03-11T08:12:00Z", created_at: "2026-01-04T10:00:00Z", roles: [R_ADMIN, R_TA] },
  { id: "rich-user-active", name: "Maya Ellis", email: "maya.ellis@bu.edu", is_approved: true, last_sign_in_at: "2026-03-10T21:40:00Z", created_at: "2026-01-12T15:30:00Z", roles: [R_BETA] },
  { id: "rich-user-second", name: "Jordan Lee", email: "jordan.lee@bu.edu", is_approved: true, last_sign_in_at: "2026-03-09T17:02:00Z", created_at: "2026-01-20T09:45:00Z", roles: [] },
  { id: "fx-user-noname", name: "", email: "new.signup@bu.edu", is_approved: true, last_sign_in_at: null, created_at: "2026-03-08T11:00:00Z", roles: [] },
  { id: "fx-user-sealed", name: "", email: null, undecryptable: true, is_approved: true, last_sign_in_at: "2026-02-02T13:00:00Z", created_at: "2025-12-01T13:00:00Z", roles: [] },
];

async function mockUsers(page: Page, users: unknown[] = USERS): Promise<void> {
  await mockJson(page, "/api/admin/users", { users, total: users.length, page: 1, page_size: 50 }, { method: "GET" });
}

async function adminTab(page: Page, tab: string): Promise<void> {
  await page.goto("/admin");
  await visible(page, `admin-tab-${tab}`);
  if (tab !== "users") await page.getByTestId(`admin-tab-${tab}`).click();
}

const day = (i: number) => new Date(Date.UTC(2026, 0, 10) + i * 86_400_000).toISOString();
const ALLOWLIST = [
  { email: "priya.n@bu.edu", approved_at: null, joined_at: null, invite_status: null },
  { email: "sam.ortiz@bu.edu", approved_at: null, joined_at: null, invite_status: null },
  { email: "lena.park@bu.edu", approved_at: null, joined_at: null, invite_status: null },
  { email: "omar.haddad@bu.edu", approved_at: day(20), joined_at: null, invite_status: "sent" },
  { email: "grace.kim@bu.edu", approved_at: day(22), joined_at: null, invite_status: "failed" },
  { email: "theo.brandt@bu.edu", approved_at: day(25), joined_at: null, invite_status: "queued" },
  { email: "nina.rossi@bu.edu", approved_at: day(26), joined_at: null, invite_status: "suppressed" },
  { email: "maya.ellis@bu.edu", approved_at: day(2), joined_at: day(3), invite_status: "sent" },
  { email: "jordan.lee@bu.edu", approved_at: day(5), joined_at: day(9), invite_status: "sent" },
].map((r, i) => ({ id: `fx-allow-${i}`, created_at: day(i), joined_user_id: r.joined_at ? `fx-u-${i}` : null, ...r }));

const EMAIL_STATUS = {
  configured: true,
  from_address: "Sapling <hello@saplinglearn.com>",
  variables: [
    { key: "first_name", label: "First name", fallback: "there", example: "Maya" },
    { key: "email", label: "Email", fallback: "", example: "maya@bu.edu" },
    { key: "signin_link", label: "Sign-in link", fallback: "", example: "https://saplinglearn.com", button: "Open Sapling" },
  ],
};
const AUDIENCES = [
  { key: "waitlist_all", label: "Everyone on the waitlist", count: 42 },
  { key: "waitlist_pending", label: "Waitlist: not yet approved", count: 17 },
  { key: "waitlist_approved_not_joined", label: "Approved, not joined yet", count: 9 },
  { key: "users_all", label: "All users", count: 128 },
];
const BROADCASTS = [
  { id: "fx-bc-3", subject: "Your spot in Sapling is ready", audience: "waitlist_approved_not_joined", status: "sent", recipient_count: 9, sent_count: 8, skipped_count: 1, failed_count: 0, created_at: "2026-03-08T15:00:00Z", sent_at: "2026-03-08T15:01:00Z", created_by: "rich-user-admin" },
  { id: "fx-bc-2", subject: "Spring midterm study tips", audience: "users_all", status: "failed", recipient_count: 120, sent_count: 114, skipped_count: 0, failed_count: 6, created_at: "2026-02-20T13:00:00Z", sent_at: "2026-02-20T13:04:00Z", created_by: "rich-user-admin" },
  { id: "fx-bc-1", subject: "Welcome to the Sapling beta", audience: "waitlist_all", status: "sent", recipient_count: 38, sent_count: 38, skipped_count: 0, failed_count: 0, created_at: "2026-01-15T10:00:00Z", sent_at: "2026-01-15T10:02:00Z", created_by: "rich-user-admin" },
];
const previewHtml = (subject: string) =>
  `<!doctype html><html><body style="font-family:Georgia,serif;background:#f6f3ea;padding:32px"><div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;padding:32px"><h1 style="font-size:22px;color:#2b5221">${subject || "Sapling"}</h1><p>Hi Ada,</p><p>Midterms are coming up. Here are three ways to get more out of your tutor sessions this week.</p><p><a style="display:inline-block;background:#2b5221;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none" href="#">Open Sapling</a></p></div></body></html>`;

async function mockEmail(
  page: Page,
  opts: { configured?: boolean; audiences?: unknown[]; broadcasts?: unknown[]; preview?: "ok" | "hold" | "error"; unknown?: string[] } = {},
): Promise<void> {
  await mockJson(page, "/api/admin/email/status", { ...EMAIL_STATUS, configured: opts.configured ?? true });
  await mockJson(page, "/api/admin/email/audiences", { audiences: opts.audiences ?? AUDIENCES });
  await mockJson(page, "/api/admin/email/broadcasts", { broadcasts: opts.broadcasts ?? BROADCASTS }, { method: "GET" });
  const preview = opts.preview ?? "ok";
  if (preview === "hold") await hold(page, "/api/admin/email/broadcasts/preview");
  else if (preview === "error") await mockError(page, "/api/admin/email/broadcasts/preview", 500);
  else
    await routeRe(page, /\/api\/admin\/email\/broadcasts\/preview/, async (r) => {
      const { subject } = (r.request().postDataJSON() ?? {}) as { subject?: string };
      await json(r, { subject: (subject ?? "").replace("{{first_name}}", "Ada"), html: previewHtml(subject ?? ""), unknown_variables: opts.unknown ?? [] });
    });
}

async function draftEmail(page: Page, subject: string, body: string): Promise<void> {
  await visible(page, "email-subject");
  await page.getByTestId("email-subject").fill(subject);
  await page.getByTestId("email-body").fill(body);
}

const FLAG_KEYS: [string, string][] = [
  ["tutor", "Tutor"], ["quiz", "Quiz"], ["tree", "Tree"], ["study", "Study"], ["library", "Library"],
  ["calendar", "Calendar"], ["social", "Social"], ["achievements", "Achievements"], ["grades", "Grades"],
  ["notetaker", "Notetaker"], ["course_planner", "Course Planner"],
];
const FLAGS = [
  ...FLAG_KEYS.map(([slug, label]) => ({
    key: `hide_${slug}`,
    description: `Hide ${label} from the nav; its pages redirect to /dashboard.`,
    variants: ["off", "on"],
    client_visible: true,
    default_variant: slug === "course_planner" ? "on" : "off",
    rollout_percent: slug === "notetaker" ? 25 : 0,
    rollout_variant: slug === "notetaker" ? "on" : null,
    updated_at: slug === "course_planner" ? "2026-03-09T16:20:00Z" : slug === "notetaker" ? "2026-03-10T09:00:00Z" : null,
    updated_by: slug === "course_planner" || slug === "notetaker" ? "rich-user-admin" : null,
    updated_by_name: slug === "course_planner" || slug === "notetaker" ? "Ada Admin" : null,
    targets: slug === "social"
      ? [
          { target_type: "role", target_id: "fx-role-beta", label: "Beta Tester", variant: "off" },
          { target_type: "user", target_id: "rich-user-second", label: "Jordan Lee", variant: "on" },
        ]
      : [],
  })),
  {
    key: "decision_router", description: "Tutor turn router on the Jev decision seam (ADR 0027). jev_shadow also runs flash-lite to measure agreement.",
    variants: ["off", "jev", "jev_shadow"], client_visible: false, default_variant: "off", rollout_percent: 10, rollout_variant: "jev_shadow",
    updated_at: "2026-03-02T12:00:00Z", updated_by: "rich-user-admin", updated_by_name: "Ada Admin", targets: [],
  },
  {
    key: "product_analytics", description: "PostHog product analytics, frontend + backend (ADR 0028).",
    variants: ["off", "on"], client_visible: true, default_variant: "on", rollout_percent: 0, rollout_variant: null,
    updated_at: "2026-02-14T12:00:00Z", updated_by: "rich-user-admin", updated_by_name: "Ada Admin", targets: [],
  },
];

async function flagsTab(page: Page, flags: unknown[] | "hold" = FLAGS): Promise<void> {
  if (flags === "hold") await hold(page, "/api/admin/flags", "GET");
  else await routeRe(page, /\/api\/admin\/flags(\?|$)/, (r) => json(r, { flags }), "GET");
  await adminTab(page, "flags");
}

const ACHIEVEMENTS = [
  { id: "fx-ach-first-steps", name: "First Steps", slug: "first-steps", description: "Finish your first tutor session.", icon: "🌱", category: "milestone", rarity: "common", is_secret: false, xp_reward: 25, icon_url: null, sort_order: 1, status: "live" },
  { id: "fx-ach-streak-7", name: "Week of Growth", slug: "streak-7", description: "Study seven days in a row.", icon: "🔥", category: "activity", rarity: "uncommon", is_secret: false, xp_reward: 75, icon_url: null, sort_order: 2, status: "live" },
  { id: "fx-ach-study-buddy", name: "Study Buddy", slug: "study-buddy", description: "Join a study room with a classmate.", icon: "🤝", category: "social", rarity: "rare", is_secret: false, xp_reward: 100, icon_url: null, sort_order: 3, status: "live" },
  { id: "fx-ach-night-owl", name: "Night Owl", slug: "night-owl", description: "Finish a quiz after midnight.", icon: "🦉", category: "special", rarity: "epic", is_secret: true, xp_reward: 150, icon_url: null, sort_order: 4, status: "live" },
  { id: "fx-ach-canopy", name: "Full Canopy", slug: "full-canopy", description: "Master every concept in a course.", icon: "🌳", category: "milestone", rarity: "legendary", is_secret: false, xp_reward: 500, icon_url: null, sort_order: 5, status: "draft" },
];

async function achievementsTab(page: Page, items: unknown[] = ACHIEVEMENTS): Promise<void> {
  await routeRe(page, /\/api\/admin\/achievements(\?|$)/, (r) => json(r, { achievements: items }), "GET");
  await routeRe(page, /\/api\/admin\/achievements\/[^/]+\/triggers/, (r) =>
    json(r, { triggers: [{ id: "fx-trig-1", achievement_id: "fx-ach-first-steps", trigger_type: "sessions_completed", trigger_threshold: 1 }] }), "GET");
  await routeRe(page, /\/api\/admin\/achievements\/[^/]+\/cosmetics/, (r) => json(r, { links: [] }), "GET");
  await adminTab(page, "achievements");
  await text(page, "Live catalog");
}

const ADMIN_COSMETICS = [
  { id: "fx-c-sprout", type: "avatar_frame", name: "Sprout Ring", slug: "sprout-ring", rarity: "common", asset_url: OWNED_FRAMES[0].asset_url },
  { id: "fx-c-canopy", type: "avatar_frame", name: "Canopy", slug: "canopy", rarity: "rare", asset_url: OWNED_FRAMES[1].asset_url },
  { id: "fx-c-dusk", type: "name_color", name: "Dusk", slug: "dusk", rarity: "epic", css_value: "linear-gradient(90deg, #8a63d2, #e8a33a)" },
  { id: "fx-c-forest", type: "name_color", name: "Forest", slug: "forest", rarity: "uncommon", css_value: "#2b5221" },
  { id: "fx-c-scholar", type: "title", name: "Scholar", slug: "scholar", rarity: "rare", css_value: "#2b8c96" },
];

const OVERVIEW_EMPTY = { totals: { users: 0, approved: 0, pending: 0, admins: 0 }, signups_by_day: [], approvals_by_day: [], role_counts: [] };

const ADMIN_BOOK: RecipeBook = {
  "admin/no-access": {
    run: async (page) => {
      await page.goto("/admin");
      await expect(page.getByTestId("app-shell").getByText(/don't have admin access/i)).toBeVisible({ timeout: T });
    },
  },
  "admin/shell": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "users");
      await text(page, "Staff only");
      await visible(page, "admin-users-summary");
    },
  },
  "admin/users-loading": {
    persona: "admin",
    run: async (page) => {
      await hold(page, "/api/admin/users", "GET");
      await adminTab(page, "users");
      await expect(page.getByTestId("admin-users-summary")).toHaveCount(0);
    },
  },
  "admin/users-populated": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "users");
      await visible(page, "admin-users-summary");
      await expect(page.locator("tbody tr").first()).toBeVisible({ timeout: T });
    },
  },
  "admin/users-filtered": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "users");
      await visible(page, "admin-users-summary");
      await page.getByPlaceholder("Search users…").fill("rich");
      await expect(page.getByTestId("admin-users-summary")).toContainText('filter "rich"', { timeout: T });
    },
  },
  "admin/users-empty": {
    persona: "admin",
    run: async (page) => {
      await mockUsers(page, []);
      await adminTab(page, "users");
      await expect(page.getByTestId("admin-users-summary")).toContainText("0 users", { timeout: T });
    },
  },
  "admin/users-row-variants": {
    persona: "admin",
    run: async (page) => {
      await mockUsers(page);
      await adminTab(page, "users");
      await text(page, "No profile name");
      await visible(page, "admin-user-undecryptable");
    },
  },
  "admin/users-role-assign": {
    persona: "admin",
    run: async (page) => {
      await mockUsers(page);
      await adminTab(page, "users");
      await page.getByRole("button", { name: "+ role" }).nth(1).click();
      await expect(page.getByRole("button", { name: "Add", exact: true })).toBeVisible({ timeout: T });
    },
  },
  "admin/users-role-chips": {
    persona: "admin",
    run: async (page) => {
      await mockUsers(page);
      await adminTab(page, "users");
      await expect(page.getByTitle("Revoke").first()).toBeVisible({ timeout: T });
      await text(page, "Teaching Assistant");
    },
  },
  "admin/users-remove-dialog": {
    persona: "admin",
    run: async (page) => {
      await mockUsers(page);
      await adminTab(page, "users");
      await page.getByTestId("admin-user-remove-access-rich-user-second").click();
      await visible(page, "admin-user-remove-body");
      await text(page, "Remove Jordan Lee's access?");
    },
  },
  "admin/users-remove-result": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockUsers(page);
      await mockJson(page, "/unapprove", { unapproved: true }, { method: "PATCH" });
      await adminTab(page, "users");
      await page.getByTestId("admin-user-remove-access-rich-user-second").click();
      await page.getByTestId("admin-user-remove-confirm").click();
      await text(page, /Access removed\. jordan\.lee@bu\.edu is back on the Allowlist/);
    },
  },
  "admin/users-load-error": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockError(page, "/api/admin/users", 500, "Internal Server Error", "GET");
      await adminTab(page, "users");
      await text(page, /Load failed/);
    },
  },

  // Allowlist
  "admin/allowlist-loading": {
    persona: "admin",
    run: async (page) => {
      await hold(page, "/api/admin/allowlist", "GET");
      await adminTab(page, "allowlist");
      await expect(page.getByTestId("allowlist-search")).toHaveCount(0);
    },
  },
  "admin/allowlist-populated": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await adminTab(page, "allowlist");
      await visible(page, "allowlist-row-priya.n@bu.edu");
    },
  },
  "admin/allowlist-status-chips": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await adminTab(page, "allowlist");
      await page.getByTestId("allowlist-filter-signup").click();
      await expect(page.getByTestId("allowlist-filter-signup")).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("allowlist-row-omar.haddad@bu.edu")).toHaveCount(0);
    },
  },
  "admin/allowlist-invite-chips": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await adminTab(page, "allowlist");
      await page.getByTestId("allowlist-filter-approved").click();
      await visible(page, "allowlist-invite-grace.kim@bu.edu");
    },
  },
  "admin/allowlist-not-configured": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", { ...EMAIL_STATUS, configured: false });
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await adminTab(page, "allowlist");
      await visible(page, "email-not-configured-banner");
    },
  },
  "admin/allowlist-no-match": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await adminTab(page, "allowlist");
      await page.getByTestId("allowlist-search").fill("zzz-nobody");
      await text(page, "No addresses match.");
    },
  },
  "admin/allowlist-selection": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await adminTab(page, "allowlist");
      await page.getByTestId("allowlist-select-priya.n@bu.edu").check();
      await expect(page.getByTestId("allowlist-bulk-approve")).toHaveText("Approve selected (1)");
      expect(await page.getByTestId("allowlist-select-all").evaluate((el) => (el as HTMLInputElement).indeterminate)).toBe(true);
    },
  },
  "admin/allowlist-bulk-dialog": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await adminTab(page, "allowlist");
      await page.getByTestId("allowlist-select-priya.n@bu.edu").check();
      await page.getByTestId("allowlist-select-sam.ortiz@bu.edu").check();
      await page.getByTestId("allowlist-bulk-approve").click();
      await visible(page, "allowlist-bulk-confirm-text");
      await text(page, "Approve 2 people?");
    },
  },
  "admin/allowlist-toasts": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await mockJson(page, "/api/admin/allowlist", { emails: ALLOWLIST }, { method: "GET" });
      await mockJson(page, "/api/admin/allowlist/approve", { email: { ...ALLOWLIST[0], approved_at: day(30), invite_status: "sent" } }, { method: "POST" });
      await adminTab(page, "allowlist");
      await page.getByTestId("allowlist-toggle-priya.n@bu.edu").click();
      await text(page, /Approved priya\.n@bu\.edu\. "You're in" email sent\./);
    },
  },

  // Email
  "admin/email-loading": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/email/status", EMAIL_STATUS);
      await hold(page, "/api/admin/email/broadcasts", "GET");
      await adminTab(page, "email");
      await page.waitForTimeout(500);
      await expect(page.getByTestId("email-subject")).toHaveCount(0);
    },
  },
  "admin/email-compose": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page);
      await adminTab(page, "email");
      await draftEmail(page, "Midterm prep: three tutor tricks", "Hi {{first_name}},\n\nMidterms are coming up. Here are three ways to get more out of your tutor sessions this week.\n\n{{signin_link}}");
      await page.getByTestId("email-audience-users_all").check();
      await visible(page, "email-preview-frame");
      await expect(page.getByTestId("email-send")).toBeEnabled();
    },
  },
  "admin/email-preview-loading": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page, { preview: "hold" });
      await adminTab(page, "email");
      await visible(page, "email-subject");
      await text(page, "Loading preview…");
    },
  },
  "admin/email-preview-error": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page, { preview: "error" });
      await adminTab(page, "email");
      await visible(page, "email-preview-error");
    },
  },
  "admin/email-unknown-vars": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page, { unknown: ["frist_name"] });
      await adminTab(page, "email");
      await draftEmail(page, "Quick check-in", "Hi {{frist_name}}, how is the semester going?");
      await visible(page, "email-unknown-variables");
    },
  },
  "admin/email-no-audiences": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page, { audiences: [] });
      await adminTab(page, "email");
      await text(page, "No audiences available.");
    },
  },
  "admin/email-not-configured": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page, { configured: false });
      await adminTab(page, "email");
      await visible(page, "email-not-configured-banner");
      await visible(page, "email-subject");
    },
  },
  "admin/email-confirm-dialog": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page);
      await mockError(page, /\/api\/admin\/email\/broadcasts$/, 403, "blocked by capture recipe", "POST");
      await adminTab(page, "email");
      await draftEmail(page, "Midterm prep: three tutor tricks", "Hi {{first_name}},\n\nMidterms are coming up.\n\n{{signin_link}}");
      await page.getByTestId("email-audience-waitlist_pending").check();
      await expect(page.getByTestId("email-send")).toBeEnabled({ timeout: T });
      await page.getByTestId("email-send").click();
      await visible(page, "email-send-confirm-input");
      await text(page, "Email 17 people?");
    },
  },
  "admin/email-history-empty": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page, { broadcasts: [] });
      await adminTab(page, "email");
      await text(page, "No broadcasts yet.");
    },
  },
  "admin/email-history-populated": {
    persona: "admin",
    run: async (page) => {
      await mockEmail(page);
      await adminTab(page, "email");
      await visible(page, "email-history-row-fx-bc-3");
      await page.getByTestId("email-history").scrollIntoViewIfNeeded();
    },
  },
  "admin/email-toasts": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockEmail(page);
      await mockJson(page, "/api/admin/email/broadcasts/test", { status: "sent", to: "ada.admin@bu.edu" }, { method: "POST" });
      await adminTab(page, "email");
      await draftEmail(page, "Midterm prep: three tutor tricks", "Hi {{first_name}}, midterms are coming up.");
      await page.getByTestId("email-send-test").click();
      await text(page, "Test email to ada.admin@bu.edu: sent");
    },
  },

  // Roles
  "admin/roles": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "roles");
      await text(page, /Roles · [1-9]/);
    },
  },
  "admin/roles-empty": {
    persona: "admin",
    run: async (page) => {
      await routeRe(page, /\/api\/admin\/roles(\?|$)/, (r) => json(r, { roles: [] }), "GET");
      await adminTab(page, "roles");
      await text(page, "No roles yet.");
    },
  },
  "admin/roles-delete-armed": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [3000]);
      await routeRe(page, /\/api\/admin\/roles(\?|$)/, (r) => json(r, { roles: [R_ADMIN, R_TA, R_BETA] }), "GET");
      await mockError(page, "/api/admin/roles/", 403, "blocked by capture recipe", "DELETE");
      await adminTab(page, "roles");
      const list = page.locator(".card").filter({ hasText: /Roles · 3/ });
      await list.getByRole("button").last().click();
      await expect(list.getByRole("button", { name: "Click again" })).toBeVisible({ timeout: T });
    },
  },
  "admin/roles-validation": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await adminTab(page, "roles");
      await page.getByRole("button", { name: "Create role" }).click();
      await text(page, "Name and slug are required.");
    },
  },

  // Flags
  "admin/flags-loading": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page, "hold");
      await page.waitForTimeout(500);
      await expect(page.locator(".flags")).toHaveCount(0);
    },
  },
  "admin/flags-list": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      await visible(page, "flag-row-hide_quiz");
    },
  },
  "admin/flags-empty": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page, []);
      await text(page, "No flags defined.");
    },
  },
  "admin/flags-multivariant-row": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      await visible(page, "flag-row-decision_router");
      await page.getByTestId("flag-row-decision_router").scrollIntoViewIfNeeded();
      await expect(page.getByTestId("flag-toggle-decision_router")).toHaveCount(0);
    },
  },
  "admin/flags-confirm-dialog": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      await page.getByTestId("flag-toggle-hide_quiz").click();
      await visible(page, "flag-save-scope-hide_quiz");
      await text(page, "Make Quiz hidden?");
    },
  },
  "admin/flags-panel": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      await page.getByTestId("flag-open-hide_quiz").click();
      await visible(page, "flag-panel-hide_quiz");
    },
  },
  "admin/flags-panel-dirty": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      await page.getByTestId("flag-open-hide_quiz").click();
      await page.getByTestId("flag-rollout-preset-hide_quiz-25").click();
      await visible(page, "flag-save-hide_quiz");
      await expect(page.getByTestId("flag-save-scope-hide_quiz")).toContainText(/rollout/i);
    },
  },
  "admin/flags-panel-invalid": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page, FLAGS.map((f) => (f.key === "decision_router" ? { ...f, rollout_percent: 0, rollout_variant: null } : f)));
      await page.getByTestId("flag-open-decision_router").click();
      await page.getByTestId("flag-rollout-preset-decision_router-10").click();
      await expect(page.getByTestId("flag-save-scope-decision_router")).toHaveText("Pick which setting the rollout serves.");
      await expect(page.getByTestId("flag-save-decision_router")).toBeDisabled();
    },
  },
  "admin/flags-panel-overrides": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      await page.getByTestId("flag-open-hide_social").click();
      await visible(page, "flag-target-row-hide_social-user-rich-user-second");
      await visible(page, "flag-target-row-hide_social-role-fx-role-beta");
    },
  },
  "admin/flags-student-results": {
    persona: "admin",
    run: async (page) => {
      await mockUsers(page, USERS.slice(0, 3));
      await flagsTab(page);
      await page.getByTestId("flag-open-hide_quiz").click();
      await page.getByTestId("flag-explain-input-hide_quiz").fill("Ma");
      await visible(page, "flag-explain-user-hide_quiz-rich-user-active");
    },
  },
  "admin/flags-explain-result": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/explain", { variant: "on", step: "user", detail: "" });
      await flagsTab(page);
      await page.getByTestId("flag-open-hide_social").click();
      const input = page.getByTestId("flag-explain-input-hide_social");
      await input.fill("rich-user-second");
      await input.press("Enter");
      await expect(page.getByTestId("flag-explain-result-hide_social")).toContainText("Hidden: this student has their own override", { timeout: T });
    },
  },
  "admin/flags-tooltips": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      const chip = page.getByTestId("flag-row-hide_social").getByText("2 overrides");
      await chip.hover();
      await text(page, /Role Beta Tester: Visible/);
      await freezePointer(page);
    },
  },

  // Achievements
  "admin/achievements-loading": {
    persona: "admin",
    run: async (page) => {
      await hold(page, /\/api\/admin\/achievements(\?|$)/, "GET");
      await adminTab(page, "achievements");
      await page.waitForTimeout(500);
      await expect(page.getByText("Live catalog")).toHaveCount(0);
    },
  },
  "admin/achievements": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "achievements");
      await text(page, "Live catalog");
    },
  },
  "admin/achievements-empty-variants": {
    persona: "admin",
    run: async (page) => {
      await achievementsTab(page, []);
      await text(page, "No live achievements yet.");
    },
  },
  "admin/achievement-card": {
    persona: "admin",
    run: async (page) => {
      await achievementsTab(page);
      await page.getByPlaceholder("Search name, slug, description…").fill("study buddy");
      await text(page, "Join a study room with a classmate.");
      await expect(page.getByText("Week of Growth")).toHaveCount(0);
    },
  },
  "admin/achievement-card-expanded": {
    persona: "admin",
    run: async (page) => {
      await achievementsTab(page);
      await page.getByRole("button", { name: "Edit", exact: true }).first().click();
      await text(page, /Triggers · 1/);
      await text(page, /Drop a 512×512 PNG/);
    },
  },
  "admin/achievement-icon-error": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await achievementsTab(page);
      await page.getByRole("button", { name: "Edit", exact: true }).first().click();
      await text(page, /Drop a 512×512 PNG/);
      await page.locator('input[type="file"][accept="image/png,image/webp,image/svg+xml"]').first()
        .setInputFiles({ name: "badge.txt", mimeType: "text/plain", buffer: Buffer.from("not an image") });
      await text(page, "Icon must be a PNG, WebP or SVG");
    },
  },
  "admin/xp-rules": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "achievements");
      const head = page.getByText(/XP rules · /);
      await expect(head).toBeVisible({ timeout: T });
      await head.scrollIntoViewIfNeeded();
    },
  },
  "admin/grant-panel": {
    persona: "admin",
    run: async (page) => {
      await achievementsTab(page);
      const btn = page.getByRole("button", { name: "Grant achievement" });
      await btn.scrollIntoViewIfNeeded();
      await expect(btn).toBeVisible({ timeout: T });
      await text(page, "Grant to user");
    },
  },

  // Cosmetics
  "admin/cosmetics": {
    persona: "admin",
    run: async (page) => {
      await routeRe(page, /\/api\/admin\/cosmetics(\?|$)/, (r) => json(r, { cosmetics: ADMIN_COSMETICS }), "GET");
      await adminTab(page, "cosmetics");
      await text(page, "Create cosmetic");
      await text(page, "Sprout Ring");
    },
  },
  "admin/cosmetics-row-expanded": {
    persona: "admin",
    run: async (page) => {
      await routeRe(page, /\/api\/admin\/cosmetics(\?|$)/, (r) => json(r, { cosmetics: ADMIN_COSMETICS }), "GET");
      await adminTab(page, "cosmetics");
      await page.getByRole("button", { name: "Manage" }).first().click();
      await text(page, "Roles that grant this");
    },
  },
  "admin/cosmetics-validation": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await adminTab(page, "cosmetics");
      await page.getByRole("button", { name: "Create cosmetic" }).click();
      await text(page, "Name and slug are required.");
    },
  },

  // Analytics tab
  "admin/analytics-overview-loading": {
    persona: "admin",
    run: async (page) => {
      await hold(page, "/api/admin/analytics/overview");
      await adminTab(page, "analytics");
      await page.waitForTimeout(500);
      await expect(page.getByText("Awaiting approval")).toHaveCount(0);
    },
  },
  "admin/analytics-overview": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "analytics");
      await text(page, "Awaiting approval");
      await text(page, /Role membership · /);
    },
  },
  "admin/analytics-overview-empty": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/analytics/overview", OVERVIEW_EMPTY);
      await adminTab(page, "analytics");
      await text(page, "Nobody has any roles yet.");
    },
  },
  "admin/analytics-overview-error": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockError(page, "/api/admin/analytics/overview", 500);
      await adminTab(page, "analytics");
      await text(page, /Analytics load failed/);
    },
  },

  // Audit + feedback
  "admin/audit": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "audit");
      await text(page, /recorded action/);
    },
  },
  "admin/feedback": {
    persona: "admin",
    run: async (page) => {
      await adminTab(page, "feedback");
      await visible(page, "adminfb-feedback-card");
      await visible(page, "adminfb-issues-card");
    },
  },
  "admin/feedback-empty": {
    persona: "admin",
    run: async (page) => {
      await mockJson(page, "/api/admin/feedback", { feedback: [] });
      await mockJson(page, "/api/admin/issue-reports", { reports: [] });
      await adminTab(page, "feedback");
      await text(page, "No feedback yet.");
      await text(page, "No issue reports yet.");
    },
  },
};

// ── /admin/analytics ───────────────────────────────────────────────────────

const A_FROM = "2026-02-09T12:00:00.000Z";
const A_TO = "2026-03-11T12:00:00.000Z";
const A_RANGE = { from: A_FROM, to: A_TO };
const A_DAYS = Array.from({ length: 31 }, (_, i) => new Date(Date.UTC(2026, 1, 9) + i * 86_400_000).toISOString().slice(0, 10));
const wave = (i: number, base: number, amp: number) => base + ((i * 37) % amp) + (i % 7 < 5 ? Math.round(amp / 2) : 0);

const A_SUMMARY = {
  range: A_RANGE, total_events: 18_432, distinct_active_users: 214, truncated: false,
  by_event_type: [
    ["tutor.turn", 6120], ["quiz.answered", 4210], ["quiz.started", 1904], ["note.created", 1388], ["document.uploaded", 962],
    ["flashcard.reviewed", 2140], ["study_room.joined", 418], ["error.5xx", 61],
  ].map(([event_type, count]) => ({ event_type, count })),
  series: A_DAYS.map((date, i) => ({ date, count: wave(i, 380, 260) })),
};
const A_USERS = {
  range: A_RANGE, total_users: 214, limit: 25, offset: 0, truncated: false,
  users: [
    ["rich-user-active", 1840, 3.4127, 812_400], ["rich-user-second", 1322, 2.0881, 498_120], ["user_1048", 977, 4.9012, 1_102_300],
    ["user_2231", 812, 0.9733, 240_500], ["user_3307", 640, 1.2045, 301_880], ["user_4410", 402, 0.4410, 110_020],
  ].map(([user_id, event_count, llm_cost_usd, total_tokens]) => ({ user_id, event_count, by_category: {}, llm_cost_usd, total_tokens })),
};
const COST_ROWS: Record<string, [string, number, number][]> = {
  feature: [["tutor", 5210, 28.41], ["quiz", 3120, 12.07], ["summary", 980, 4.12], ["concepts", 760, 3.36], ["syllabus", 120, 0.88]],
  model: [["claude-sonnet-5-5", 5210, 28.41], ["claude-haiku-5-5", 4980, 20.43]],
  user: [["user_1048", 860, 4.90], ["rich-user-active", 702, 3.41], ["rich-user-second", 455, 2.09]],
};
const costFor = (group: string) => {
  const rows = (COST_ROWS[group] ?? COST_ROWS.feature).map(([key, calls, cost]) => ({
    key, calls, prompt_tokens: calls * 1900, completion_tokens: calls * 420, total_tokens: calls * 2320, cost_usd: cost,
  }));
  const sum = (k: "calls" | "prompt_tokens" | "completion_tokens" | "total_tokens" | "cost_usd") => rows.reduce((a, r) => a + r[k], 0);
  return {
    range: A_RANGE, group_by: group, rows, truncated: false,
    totals: { calls: sum("calls"), prompt_tokens: sum("prompt_tokens"), completion_tokens: sum("completion_tokens"), total_tokens: sum("total_tokens"), cost_usd: sum("cost_usd") },
    series: A_DAYS.map((date, i) => ({ date, calls: wave(i, 220, 140), total_tokens: wave(i, 220, 140) * 2320, cost_usd: Number((wave(i, 220, 140) * 0.0047).toFixed(2)) })),
  };
};
const A_ERRORS = {
  range: A_RANGE, total: 61, limit: 50, offset: 0, truncated: false,
  series: A_DAYS.map((date, i) => ({ date, count: (i * 13) % 5 })),
  errors: [
    ["2026-03-11T10:42:03Z", "error.5xx", "POST", "/api/quiz/generate", 502, 30012.4],
    ["2026-03-11T09:15:44Z", "error.4xx", "GET", "/api/notes/{note_id}", 404, 12.8],
    ["2026-03-10T22:03:10Z", "error.5xx", "POST", "/api/documents/upload", 500, 4120.6],
    ["2026-03-10T18:27:51Z", "error.4xx", "PATCH", "/api/profile/{user_id}/settings", 422, 9.1],
  ].map(([created_at, event_type, method, path, status_code, duration_ms], i) => ({
    created_at, event_type, method, path, status_code, duration_ms, request_id: `fx-req-${i}`, user_id: null,
  })),
};

type Panel = "summary" | "users" | "cost" | "errors";
interface AnalyticsState {
  hold?: Panel[];
  fail?: Panel[];
  summary?: Partial<typeof A_SUMMARY>;
  users?: Partial<typeof A_USERS>;
  errors?: Partial<typeof A_ERRORS>;
  truncated?: boolean;
}

async function mockAnalytics(page: Page, state: AnalyticsState): Promise<void> {
  const routes: [Panel, RegExp, (url: URL) => unknown][] = [
    ["summary", /\/api\/admin\/analytics\/usage\/summary/, () => ({ ...A_SUMMARY, ...state.summary })],
    ["users", /\/api\/admin\/analytics\/usage\/by-user/, () => ({ ...A_USERS, ...state.users })],
    ["cost", /\/api\/admin\/analytics\/llm\/cost/, (u) => costFor(u.searchParams.get("group_by") ?? "feature")],
    ["errors", /\/api\/admin\/analytics\/errors/, () => ({ ...A_ERRORS, ...state.errors })],
  ];
  for (const [panel, re, body] of routes) {
    await routeRe(page, re, async (route) => {
      if (state.hold?.includes(panel)) return; // never answered
      if (state.fail?.includes(panel)) return json(route, { detail: "Internal Server Error" }, 500);
      const b = body(new URL(route.request().url())) as Record<string, unknown>;
      await json(route, state.truncated ? { ...b, truncated: true } : b);
    });
  }
}

async function openAnalytics(page: Page): Promise<void> {
  await page.goto("/admin/analytics");
  await visible(page, "admin-analytics-range-7d");
}

const ANALYTICS_BOOK: RecipeBook = {
  "admin-analytics/no-access": {
    run: async (page) => {
      await page.goto("/admin/analytics");
      await expect(page.getByTestId("app-shell").getByText(/don't have admin access/i)).toBeVisible({ timeout: T });
    },
  },
  "admin-analytics/loading": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, { hold: ["summary", "users", "cost", "errors"] });
      await openAnalytics(page);
      await text(page, "Loading…");
    },
  },
  "admin-analytics/populated": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, {});
      await openAnalytics(page);
      await expect(page.getByRole("img", { name: "Events per day" })).toBeVisible({ timeout: T });
      await expect(page.getByRole("img", { name: "Errors per day" })).toBeVisible({ timeout: T });
      await text(page, "tutor.turn");
    },
  },
  "admin-analytics/panel-error": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, { fail: ["users"] });
      await openAnalytics(page);
      await visible(page, "admin-analytics-users-retry");
    },
  },
  "admin-analytics/background-error": {
    persona: "admin",
    run: async (page) => {
      await pinTimers(page, [5000]);
      const state: AnalyticsState = {};
      await mockAnalytics(page, state);
      await openAnalytics(page);
      await expect(page.getByRole("img", { name: "Events per day" })).toBeVisible({ timeout: T });
      state.fail = ["summary"];
      await page.getByTestId("admin-analytics-range-7d").click();
      await expect(page.locator('[aria-live="polite"] [role="status"]').first()).toBeVisible({ timeout: T });
      await expect(page.getByRole("img", { name: "Events per day" })).toBeVisible();
    },
  },
  "admin-analytics/truncated": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, { truncated: true });
      await openAnalytics(page);
      await text(page, "Truncated — partial data");
    },
  },
  "admin-analytics/empty-chart": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, { summary: { series: [], by_event_type: [], total_events: 0, distinct_active_users: 0 } });
      await openAnalytics(page);
      await text(page, "No data in this range.");
    },
  },
  "admin-analytics/users-empty": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, { users: { users: [], total_users: 0 } });
      await openAnalytics(page);
      await text(page, "No user activity in this range.");
    },
  },
  "admin-analytics/errors-empty": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, { errors: { errors: [], total: 0, series: [] } });
      await openAnalytics(page);
      await text(page, "No errors in this range. 🎉");
    },
  },
  "admin-analytics/error-rate-variants": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, { summary: { series: [], total_events: 0 } });
      await openAnalytics(page);
      await text(page, "No events in this range.");
    },
  },
  "admin-analytics/chart-hover": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, {});
      await openAnalytics(page);
      const chart = page.getByRole("img", { name: "Events per day" });
      await expect(chart).toBeVisible({ timeout: T });
      const box = await chart.boundingBox();
      if (!box) throw new Error("chart has no box");
      await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5, { steps: 4 });
      await page.waitForTimeout(300);
      await freezePointer(page);
      await expect(chart.locator('circle[r="4.5"]')).toHaveCount(1);
    },
  },
  "admin-analytics/sort-active": {
    persona: "admin",
    run: async (page) => {
      await mockAnalytics(page, {});
      await openAnalytics(page);
      await page.getByTestId("admin-analytics-users-sort-cost").click();
      await expect(page.getByTestId("admin-analytics-users-sort-cost")).toHaveText(/LLM cost [↓↑]/);
    },
  },
};

// ── pre-shell ───────────────────────────────────────────────────────────────

const DRAFT = {
  first_name: "New", last_name: "Student", school: "Boston University", year: "sophomore",
  majors: ["Computer Science"], minors: ["Philosophy"],
  course_ids: ["fx-course-cs131", "fx-course-ma242"],
  course_cache: [
    { id: "fx-course-cs131", course_code: "CAS CS 131", course_name: "Combinatoric Structures" },
    { id: "fx-course-ma242", course_code: "CAS MA 242", course_name: "Linear Algebra" },
  ],
  learning_style: "visual", step: 0,
};

/** Onboarding at `step` (draft-driven). The local-seed probe 404s so the
 *  funnel never detours to /setting-up. */
async function onboardingAt(page: Page, step: number, draft: Partial<typeof DRAFT> = {}): Promise<void> {
  await mockError(page, "/api/auth/local-seed", 404, "Not Found");
  // The draft is per account (#757): the "new" persona is rich-user-new.
  await storage(page, { "sapling_onboarding_draft:rich-user-new": JSON.stringify({ ...DRAFT, ...draft, step }) });
  await page.goto("/onboarding");
  await visible(page, "onboarding-gate");
}

const onboardingRecipe = (step: number, draft: Partial<typeof DRAFT>, proof: (p: Page) => Promise<void>, before?: (p: Page) => Promise<void>): Recipe => ({
  persona: "new",
  run: async (page) => {
    if (before) await before(page);
    await onboardingAt(page, step, draft);
    await proof(page);
  },
});

const pendingRecipe = (status: Record<string, unknown> | "hold" | null, proof: (p: Page) => Promise<void>, before?: (p: Page) => Promise<void>): Recipe => ({
  persona: "public",
  run: async (page) => {
    if (status === "hold") await hold(page, "/api/auth/pending/status");
    else if (status !== null) await mockJson(page, "/api/auth/pending/status", status);
    if (before) await before(page);
    await page.goto(status === null ? "/pending" : "/pending?t=fx-pending-token");
    await visible(page, "pending-gate");
    await proof(page);
  },
});

const PRESHELL: RecipeBook = {
  "onboarding/step-0-welcome": onboardingRecipe(0, {}, async (p) => {
    await text(p, "Welcome to Sapling");
    await expect(p.getByTestId("onboarding-back")).toHaveCount(0);
  }),
  "onboarding/step-1-name": onboardingRecipe(1, {}, async (p) => {
    await visible(p, "onboarding-first-name");
    await visible(p, "onboarding-last-name");
  }),
  "onboarding/step-2-school": onboardingRecipe(2, {}, async (p) => {
    await expect(p.getByTestId("onboarding-school")).toBeDisabled({ timeout: T });
    await text(p, "Where are you studying?");
  }),
  "onboarding/step-3-academics": onboardingRecipe(3, {}, async (p) => {
    await visible(p, "onboarding-chip-remove-majors-Computer Science");
    await visible(p, "onboarding-chip-input-minors");
  }),
  "onboarding/step-4-courses": onboardingRecipe(4, { course_ids: [], course_cache: [] }, async (p) => {
    const first = p.locator('[data-testid^="onboarding-course-result-"]').first();
    await expect(first).toBeVisible({ timeout: T });
    await first.click();
    await expect(first).toContainText("✓");
  }),
  "onboarding/step-4-courses-searching": onboardingRecipe(4, {}, async (p) => {
    await text(p, "Searching…");
  }, (p) => hold(p, "/api/onboarding/courses")),
  "onboarding/step-4-courses-empty": onboardingRecipe(4, { course_ids: [], course_cache: [] }, async (p) => {
    await p.getByTestId("onboarding-course-search").fill("ZZZ 999");
    await text(p, "No courses match.");
  }, (p) => mockJson(p, "/api/onboarding/courses", { courses: [] })),
  "onboarding/step-5-style": onboardingRecipe(5, {}, async (p) => {
    await expect(p.getByTestId("onboarding-learning-style-visual")).toHaveAttribute("aria-checked", "true", { timeout: T });
    await expect(p.getByTestId("onboarding-continue")).toHaveText("Enter Sapling →");
  }),
  "onboarding/submitting": onboardingRecipe(5, {}, async (p) => {
    await p.getByTestId("onboarding-continue").click();
    await expect(p.getByTestId("onboarding-continue")).toHaveText("Saving…");
  }, (p) => hold(p, "/api/onboarding/profile", "POST")),
  "onboarding/submit-success": onboardingRecipe(5, {}, async (p) => {
    await p.getByTestId("onboarding-continue").click();
    await text(p, "Welcome to Sapling!");
  }, async (p) => {
    await pinTimers(p, [5000]);
    await mockJson(p, "/api/onboarding/profile", { user_id: "rich-user-new", courses_linked: [] }, { method: "POST" });
  }),
  "onboarding/submit-error": onboardingRecipe(5, {}, async (p) => {
    await p.getByTestId("onboarding-continue").click();
    await expect(p.locator('[aria-live="polite"] [role="status"]').first()).toBeVisible({ timeout: T });
    await expect(p.getByTestId("onboarding-continue")).toHaveText("Enter Sapling →");
  }, async (p) => {
    await pinTimers(p, [5000]);
    await mockError(p, "/api/onboarding/profile", 500, "Couldn't save your profile right now.", "POST");
  }),

  "pending/loading": pendingRecipe("hold", (p) => visible(p, "pending-loading")),
  "pending/unknown": pendingRecipe(null, (p) => visible(p, "pending-unknown")),
  "pending/not-on-waitlist": pendingRecipe({ email: "new.student@bu.edu", on_waitlist: false }, (p) => visible(p, "pending-join")),
  "pending/join-error": pendingRecipe({ email: "new.student@bu.edu", on_waitlist: false }, async (p) => {
    await p.getByTestId("pending-join").click();
    await visible(p, "pending-join-error");
  }, (p) => mockError(p, "/api/auth/pending/join", 500)),
  "pending/on-waitlist": pendingRecipe({ email: "new.student@bu.edu", on_waitlist: true }, async (p) => {
    await visible(p, "pending-on-waitlist");
    await expect(p.getByTestId("pending-joined")).toHaveCount(0);
  }),
  "pending/just-joined": pendingRecipe({ email: "new.student@bu.edu", on_waitlist: false }, async (p) => {
    await p.getByTestId("pending-join").click();
    await visible(p, "pending-joined");
  }, (p) => mockJson(p, "/api/auth/pending/join", { email: "new.student@bu.edu", on_waitlist: true })),

  "setting-up/waiting": {
    persona: "new",
    run: async (page) => {
      await mockJson(page, "/api/auth/local-seed", { state: "pending" });
      await page.goto("/setting-up");
      await visible(page, "setup-gate");
      await text(page, "Setting up your sample data…");
    },
  },
  "setting-up/failed": {
    persona: "new",
    run: async (page) => {
      await mockJson(page, "/api/auth/local-seed", { state: "failed", error: "Seeding stopped at enrollments: PostgREST answered 503." });
      await page.goto("/setting-up");
      await visible(page, "setup-error");
      await visible(page, "setup-continue");
    },
  },
  "auth-callback/signing-in": {
    persona: "public",
    run: async (page) => {
      await hold(page, "/api/auth/session", "POST");
      await page.goto("/auth/callback?user_id=rich-user-new&is_approved=true");
      await text(page, "Signing you in…");
    },
  },
};

// ── app chrome & global ────────────────────────────────────────────────────

const NAV_FLAGS: [string, string][] = [
  ["tutor", "learn"], ["quiz", "quiz"], ["tree", "tree"], ["study", "study"], ["library", "library"],
  ["calendar", "calendar"], ["social", "social"], ["achievements", "achievements"], ["grades", "gradebook"],
  ["notetaker", "notetaker"], ["course_planner", "course-planner"],
];

async function dashboard(page: Page): Promise<void> {
  await page.goto("/dashboard");
  await visible(page, "app-shell");
  await visible(page, "nav-link-dashboard");
}

async function openReport(page: Page): Promise<void> {
  await dashboard(page);
  await page.getByRole("button", { name: "Report", exact: true }).click();
  await text(page, "Report an issue");
}

// The prompt normally needs a wrapped-up session; `?testFeedback=session` on
// /learn skips that and the pacing (lib/feedbackPacing.ts) for the next client
// navigation out, and it opens once LoopLearn's hold on prompts is released.
const sessionStep = (step: number): Recipe => ({
  run: async (page) => {
    await page.goto("/learn?testFeedback=session");
    await visible(page, "app-shell");
    await page.getByTestId("nav-link-dashboard").click();
    await text(page, "How was that session?");
    if (step > 0) await page.getByRole("button", { name: "Great session" }).click();
    for (let i = 0; i < step; i++) await page.getByRole("button", { name: "Next", exact: true }).last().click();
    const label = ["How did it feel?", "What worked?", "Any friction?", "Anything else to add?"][step];
    await text(page, label);
  },
});

const CHROME: RecipeBook = {
  "shell/sidebar-expanded": {
    run: async (page) => {
      await dashboard(page);
      await expect(page.getByRole("button", { name: "Collapse sidebar" })).toBeVisible({ timeout: T });
    },
  },
  "shell/sidebar-collapsed": {
    run: async (page) => {
      await storage(page, { sapling_sidenav_collapsed: "1" });
      await dashboard(page);
      await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible({ timeout: T });
    },
  },
  "shell/nav-item-active": {
    run: async (page) => {
      await page.goto("/library");
      await visible(page, "nav-link-library");
      await expect(page.getByTestId("nav-link-library")).toHaveCSS("font-weight", "600");
    },
  },
  "shell/nav-item-hover": {
    run: async (page) => {
      await dashboard(page);
      const link = page.getByTestId("nav-link-quiz");
      await link.hover();
      await expect.poll(() => link.evaluate((el) => (el as HTMLElement).style.background), { timeout: T }).not.toBe("transparent");
      await freezePointer(page);
    },
  },
  "shell/topnav-desktop": {
    run: async (page) => {
      await storage(page, { sapling_layout: "topnav" });
      await page.goto("/dashboard");
      await visible(page, "app-shell");
      await expect(page.getByRole("button", { name: "Learn", exact: true })).toBeVisible({ timeout: T });
    },
  },
  "shell/topnav-group-open": {
    run: async (page) => {
      await storage(page, { sapling_layout: "topnav" });
      await page.goto("/dashboard");
      await visible(page, "app-shell");
      const trigger = page.getByRole("button", { name: "Learn", exact: true });
      await trigger.hover();
      await expect(trigger).toHaveAttribute("aria-expanded", "true", { timeout: T });
      await freezePointer(page);
      await expect(page.getByRole("link", { name: /Tutor/ }).first()).toBeVisible();
    },
  },
  "shell/role-student": {
    run: async (page) => {
      await dashboard(page);
      await expect(page.getByTestId("nav-link-admin")).toHaveCount(0);
    },
  },
  "shell/role-admin": {
    persona: "admin",
    run: async (page) => {
      await dashboard(page);
      await visible(page, "nav-link-admin");
    },
  },
  "shell/flags-loading": {
    run: async (page) => {
      await hold(page, "/api/flags");
      await dashboard(page);
      await expect(page.getByTestId("nav-link-quiz")).toHaveCount(0);
      await visible(page, "nav-link-settings");
    },
  },
  ...Object.fromEntries(
    NAV_FLAGS.map(([slug, href]): [string, Recipe] => [
      `shell/flag-hidden-${slug.replace(/_/g, "-")}`,
      {
        run: async (page) => {
          const flags = Object.fromEntries(NAV_FLAGS.map(([s]) => [`hide_${s}`, s === slug ? "on" : "off"]));
          await mockJson(page, "/api/flags", { flags: { ...flags, product_analytics: "off" } });
          await dashboard(page);
          await expect(page.getByTestId(`nav-link-${href === "learn" ? "quiz" : "learn"}`)).toBeVisible({ timeout: T });
          await expect(page.getByTestId(`nav-link-${href}`)).toHaveCount(0);
        },
      },
    ]),
  ),

  "global/error-segment": {
    persona: "admin",
    run: async (page) => {
      // Overview answered with an object missing `totals` → AnalyticsTab
      // throws during render → the segment boundary.
      await mockJson(page, "/api/admin/analytics/overview", {});
      await adminTab(page, "analytics");
      await visible(page, "error-fallback");
      await text(page, "Something interrupted us");
    },
  },

  "fab/report": {
    run: async (page) => {
      await dashboard(page);
      await expect(page.getByRole("button", { name: "Report", exact: true })).toBeVisible({ timeout: T });
    },
  },
  "modal/report-issue": {
    run: async (page) => {
      await openReport(page);
      await expect(page.getByPlaceholder("Describe the issue…")).toBeVisible();
    },
  },
  "modal/report-issue-toasts": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await openReport(page);
      await page.locator('input[type="file"][accept="image/*"][multiple]')
        .setInputFiles({ name: "notes.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
      await text(page, "notes.pdf isn't an image");
      await text(page, "Report an issue");
    },
  },
  "modal/feedback-global": {
    run: async (page) => {
      await page.goto("/dashboard?testFeedback=global");
      await visible(page, "app-shell");
      // FeedbackFlow opens after its fixed 45s delay (the override skips the
      // pacing — cooldowns, one per session — never the delay; /dashboard holds
      // no learning activity that would defer it).
      await expect(page.getByText("What's clicking?")).toBeVisible({ timeout: 70_000 });
    },
  },
  "modal/session-feedback-step-0": sessionStep(0),
  "modal/session-feedback-step-1": sessionStep(1),
  "modal/session-feedback-step-2": sessionStep(2),
  "modal/session-feedback-step-3": sessionStep(3),
  "modal/disclaimer": {
    run: async (page) => {
      await page.addInitScript(() => window.localStorage.removeItem("sapling_disclaimer_ack"));
      await page.goto("/learn");
      await text(page, "Sapling uses AI");
      await text(page, "Heads up");
    },
  },

  "toast/success": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await mockJson(page, "/api/issue-reports", { ok: true }, { method: "POST" });
      await openReport(page);
      await page.getByPlaceholder("Describe the issue…").fill("The calendar week view skips Sunday.");
      await page.getByRole("button", { name: "Submit", exact: true }).click();
      await text(page, "Thanks — we'll take a look.");
    },
  },
  "toast/error": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await openSettings(page);
      await text(page, "Change avatar");
      await page.locator('input[type="file"][accept="image/*"]').first()
        .setInputFiles({ name: "resume.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
      await text(page, "Pick an image file (PNG or JPG).");
    },
  },
  "toast/warn": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await openReport(page);
      await page.getByRole("button", { name: "Submit", exact: true }).click();
      await text(page, "Describe what happened first.");
    },
  },
  "toast/info": {
    run: async (page) => {
      await pinTimers(page, [5000]);
      await page.goto("/quiz?concept=fx-no-such-concept");
      await text(page, "That concept isn't in your current semester");
    },
  },
  "toast/achievement-unlock": {
    run: async (page) => {
      await pinTimers(page, [5000, 6000]);
      let calls = 0;
      await routeRe(page, new RegExp(`/api/profile/${ACTIVE}/achievements`), async (route) => {
        calls += 1;
        const earned = calls === 1 ? [] : [{
          achievement: { ...ACHIEVEMENTS[1], id: "fx-ach-unlock", name: "Week of Growth", icon: "🔥", rarity: "rare" },
          earned_at: "2026-03-11T12:00:00Z", is_featured: false,
        }];
        await json(route, { earned, available: [] });
      }, "GET");
      await openSettings(page);
      await expect.poll(() => calls, { timeout: T }).toBeGreaterThan(0);
      await page.waitForTimeout(1_000);
      await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await text(page, "Week of Growth");
    },
  },

  "overlay/dialog": {
    persona: "admin",
    run: async (page) => {
      await mockUsers(page);
      await adminTab(page, "users");
      await page.getByTestId("admin-user-remove-access-fx-user-noname").click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: T });
    },
  },
  "overlay/sheet": {
    persona: "admin",
    run: async (page) => {
      await flagsTab(page);
      await page.getByTestId("flag-row-hide_notetaker").click();
      await visible(page, "flag-panel-hide_notetaker");
    },
  },
};

export const RECIPES_SETTINGS: RecipeBook = {
  ...SETTINGS,
  ...CONNECTIONS,
  ...ADMIN_BOOK,
  ...ANALYTICS_BOOK,
  ...PRESHELL,
  ...CHROME,
};
