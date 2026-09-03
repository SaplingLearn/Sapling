'use client';

/**
 * The chrome shared by the six companion pages (About, Team, Wiki, Gallery,
 * News, FAQ).
 *
 * Ported from the sibling `.dc.html` files in the design import. All six
 * repeat the same sticky header and footer verbatim; only the middle
 * changes, so it lives here once.
 *
 * The header matches the landing bar: wordmark + Sign In + Get Started,
 * nothing else. The page links live in the footer, same as on `/`.
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
  /** href of the page being rendered, so its footer link can claim aria-current. */
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

          <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap', minWidth: 0 }}>
            <Link href="/?signin=1" className="cp-navlink" style={{ ...TAB, color: '#6f6857', fontWeight: 500 }}>Sign In</Link>
            <Link
              href="/#newsletter"
              className="cp-cta"
              style={{ background: '#1B6C42', color: '#fff', borderRadius: 6, padding: '8px 16px', fontFamily: SANS, fontWeight: 600, fontSize: 13.5, whiteSpace: 'nowrap', transition: 'filter 200ms' }}
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      {children}

      <footer style={{ borderTop: '1px solid rgba(42,39,31,0.10)', background: '#faf8f3', padding: '48px 32px', boxSizing: 'border-box' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', boxSizing: 'border-box', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Image src="/sapling-icon.svg" alt="Sapling" width={20} height={20} />
            <span style={{ fontSize: 14, color: '#6f6857' }}>Sapling · © 2026</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
            {COMPANION_NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={n.href === current ? 'page' : undefined}
                className="cp-navlink"
                style={{ fontSize: 14, color: n.href === current ? '#1a1814' : '#6f6857', fontWeight: n.href === current ? 600 : 400 }}
              >
                {n.label}
              </Link>
            ))}
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="cp-navlink" style={FOOTER_LINK}>GitHub</a>
            <a href={KOFI_URL} target="_blank" rel="noopener noreferrer" className="cp-navlink" style={FOOTER_LINK}>Support us</a>
            {/* The design's companion footer stops at the nav links. These three
                are ours: /about used to be the only page linking them, so
                folding it into this shell would otherwise orphan /careers
                outright and leave the legal pages unreachable from any
                companion page. */}
            <Link href="/careers" className="cp-navlink" style={FOOTER_LINK}>Careers</Link>
            <Link href="/terms" className="cp-navlink" style={FOOTER_LINK}>Terms of Service</Link>
            <Link href="/privacy" className="cp-navlink" style={FOOTER_LINK}>Privacy Policy</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
