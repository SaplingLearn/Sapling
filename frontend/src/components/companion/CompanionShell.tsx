'use client';

/**
 * The chrome shared by the six companion pages (About, Team, Wiki, Gallery,
 * News, FAQ).
 *
 * Ported from the sibling `.dc.html` files in the design import. All six
 * repeat the same sticky header and footer verbatim; only the middle
 * changes, so it lives here once.
 *
 * Note these pages use the WARM paper palette (#f4f1ea / #1a1814 / #1B6C42),
 * not the landing page's cool one. That is deliberate in the design and
 * matches the app's existing public pages — do not "unify" them.
 */

import Image from 'next/image';
import Link from 'next/link';

const SANS = "'DM Sans',system-ui,sans-serif";

/** Page order as it appears in the nav. `/` is Home. */
export const COMPANION_NAV = [
  { label: 'Home', href: '/' },
  { label: 'About', href: '/about' },
  { label: 'Team', href: '/team' },
  { label: 'Wiki', href: '/wiki' },
  { label: 'Gallery', href: '/gallery' },
  { label: 'News', href: '/news' },
  { label: 'FAQ', href: '/faq' },
];

const GITHUB_URL = 'https://github.com/SaplingLearn/Sapling';
const KOFI_URL = 'https://ko-fi.com/saplinglearn';

const TAB: React.CSSProperties = {
  fontFamily: SANS, fontSize: 13.5, letterSpacing: '0.02em',
  transition: 'color 300ms', whiteSpace: 'nowrap',
};

const FOOTER_LINK: React.CSSProperties = { fontSize: 14, color: '#6f6857' };

export function CompanionShell({
  current,
  children,
}: {
  /** href of the page being rendered, so its tab can claim aria-current. */
  current: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#f4f1ea', color: '#1a1814', fontFamily: SANS }}>
      {/* Geometry here is locked to the landing navbar: same horizontal
          padding, same 16px/16px vertical padding, same 92px masked scrim.
          The companion sources inset their bar to `min(1320px,92%)`, which
          lands it ~32px further in than the landing bar and 18px taller — so
          the mark visibly jumped when you navigated off `/`. Full-bleed wins;
          if you change `max(4.2vw,22px)` here, change it in Navbar.tsx and the
          hero grid too. Only the palette stays warm. */}
      <header style={{ position: 'sticky', top: 0, zIndex: 50, padding: '16px max(4.2vw,22px)', pointerEvents: 'none' }}>
        <div
          aria-hidden="true"
          style={{
            position: 'absolute', left: 0, right: 0, top: 0, height: 92,
            backdropFilter: 'blur(9px)', WebkitBackdropFilter: 'blur(9px)',
            // gradient + mask ramps are the ones from `About Sapling.dc.html`,
            // the most developed of the companion scrims — the others stop at a
            // bare two-stop fade.
            background:
              'linear-gradient(180deg, #f4f1ea 0%, #f4f1ea 44%, rgba(244,241,234,0.82) 66%, rgba(244,241,234,0.45) 82%, rgba(244,241,234,0) 100%)',
            maskImage:
              'linear-gradient(180deg, #000 0%, #000 44%, rgba(0,0,0,0.78) 66%, rgba(0,0,0,0.42) 82%, rgba(0,0,0,0) 100%)',
            WebkitMaskImage:
              'linear-gradient(180deg, #000 0%, #000 44%, rgba(0,0,0,0.78) 66%, rgba(0,0,0,0.42) 82%, rgba(0,0,0,0) 100%)',
          }}
        />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, position: 'relative', pointerEvents: 'auto' }}>
          <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 4, flex: '0 0 auto' }}>
            <Image src="/sapling-icon.svg" alt="" width={26} height={26} style={{ flexShrink: 0, position: 'relative', top: -2 }} />
            <span style={{ fontFamily: "'Spectral',Georgia,serif", fontWeight: 700, fontSize: 20, color: '#1B6C42', letterSpacing: '-0.02em', lineHeight: 1.1 }}>
              Sapling
            </span>
          </Link>

          {/* A real <nav> landmark, not a bare <div>: the header carries the only
              route list on these pages, so without it a screen-reader user has no
              landmark to jump to and has to Tab through the whole thing. The label
              omits the word "navigation" — the role already announces that. */}
          <nav aria-label="Primary" style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap', minWidth: 0 }}>
            {/* below 1180px the tab row is swapped for this native disclosure */}
            <details className="nav-compact" style={{ display: 'none', position: 'relative', flex: '0 0 auto' }}>
              <summary style={{ display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer', listStyle: 'none', color: '#6f6857', fontFamily: SANS, fontWeight: 500, fontSize: 13.5 }}>
                Pages
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </summary>
              <div style={{ position: 'absolute', top: 'calc(100% + 12px)', right: 0, minWidth: 172, padding: 6, display: 'flex', flexDirection: 'column', gap: 1, background: '#faf8f3', border: '1px solid rgba(42,39,31,0.12)', borderRadius: 12, boxShadow: '0 16px 38px -18px rgba(26,24,20,0.4)' }}>
                {COMPANION_NAV.map((n) => (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={n.href === current ? 'page' : undefined}
                    className="cp-menuitem"
                    style={{ padding: '7px 11px', borderRadius: 7, fontFamily: SANS, fontSize: 13.5, fontWeight: n.href === current ? 600 : 500, color: n.href === current ? '#1a1814' : '#6f6857', transition: 'all 200ms' }}
                  >
                    {n.label}
                  </Link>
                ))}
              </div>
            </details>

            <div className="nav-tabs" style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap' }}>
              {COMPANION_NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={n.href === current ? 'page' : undefined}
                  className="cp-navlink"
                  style={{ ...TAB, color: n.href === current ? '#1a1814' : '#6f6857', fontWeight: n.href === current ? 600 : 500 }}
                >
                  {n.label}
                </Link>
              ))}
              <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" title="Sapling on GitHub" className="cp-navlink" style={{ ...TAB, display: 'flex', alignItems: 'center', gap: 7, color: '#6f6857', fontWeight: 500 }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ flexShrink: 0 }}>
                  <path d="M12 .5C5.73.5.75 5.48.75 11.75c0 4.99 3.24 9.22 7.73 10.71.57.1.78-.25.78-.55v-1.93c-3.14.68-3.81-1.51-3.81-1.51-.51-1.3-1.25-1.65-1.25-1.65-1.03-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.72.39-1.22.71-1.5-2.5-.29-5.14-1.25-5.14-5.58 0-1.23.44-2.24 1.16-3.03-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.16a10.7 10.7 0 0 1 5.64 0c2.15-1.46 3.09-1.16 3.09-1.16.62 1.55.23 2.7.12 2.98.72.79 1.16 1.8 1.16 3.03 0 4.34-2.65 5.29-5.16 5.57.41.35.77 1.04.77 2.1v3.11c0 .3.2.66.79.55a11.26 11.26 0 0 0 7.72-10.71C23.25 5.48 18.27.5 12 .5z" />
                </svg>
                GitHub
              </a>
              <a href={KOFI_URL} target="_blank" rel="noopener noreferrer" title="Support Sapling on Ko-fi" className="cp-kofi" style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '6px 13px 6px 10px', borderRadius: 99, border: '1px solid rgba(42,39,31,0.14)', background: '#faf8f3', color: '#1a1814', fontFamily: SANS, fontWeight: 600, fontSize: 13, transition: 'all 220ms' }}>
                <Image src="/kofi-symbol.png" alt="" width={17} height={17} style={{ objectFit: 'contain' }} />
                Support us
              </a>
            </div>

            <span aria-hidden="true" style={{ width: 1, height: 16, background: 'rgba(42,39,31,0.16)', flex: '0 0 auto' }} />
            <Link href="/?signin=1" className="cp-navlink" style={{ ...TAB, color: '#6f6857', fontWeight: 500 }}>Sign In</Link>
            <Link
              href="/#newsletter"
              className="cp-cta"
              style={{ background: '#1B6C42', color: '#fff', borderRadius: 6, padding: '8px 16px', fontFamily: SANS, fontWeight: 600, fontSize: 13.5, whiteSpace: 'nowrap', transition: 'filter 200ms' }}
            >
              Get Started
            </Link>
          </nav>
        </div>
      </header>

      {children}

      <footer style={{ borderTop: '1px solid rgba(42,39,31,0.10)', background: '#faf8f3', padding: '48px 32px', boxSizing: 'border-box' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', boxSizing: 'border-box', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Image src="/sapling-icon.svg" alt="Sapling" width={20} height={20} />
            <span style={{ fontSize: 14, color: '#6f6857' }}>Sapling · © 2026</span>
          </div>
          {/* Its own labelled landmark, separate from "Primary": this row is the
              only route to /careers and the legal pages, and two identically
              unlabelled navs would be indistinguishable in a landmark list. */}
          <nav aria-label="Footer" style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
            {COMPANION_NAV.map((n) => (
              <Link key={n.href} href={n.href} className="cp-navlink" style={{ fontSize: 14, color: '#6f6857' }}>{n.label}</Link>
            ))}
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="cp-navlink" style={FOOTER_LINK}>GitHub</a>
            <a href={KOFI_URL} target="_blank" rel="noopener noreferrer" className="cp-navlink" style={FOOTER_LINK}>Ko-fi</a>
            {/* The design's companion footer stops at the nav links. These three
                are ours: /about used to be the only page linking them, so
                folding it into this shell would otherwise orphan /careers
                outright and leave the legal pages unreachable from any
                companion page. */}
            <Link href="/careers" className="cp-navlink" style={FOOTER_LINK}>Careers</Link>
            <Link href="/terms" className="cp-navlink" style={FOOTER_LINK}>Terms of Service</Link>
            <Link href="/privacy" className="cp-navlink" style={FOOTER_LINK}>Privacy Policy</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
