'use client';

/**
 * Fixed navbar — full-bleed, with a blurred scrim and scroll-driven colour.
 *
 * Ported from `Sapling Landing v5.dc.html`. Two things separate it from the
 * v4 bar it replaces:
 *
 * 1. No max-width wrapper. The horizontal padding is `max(4.2vw,22px)`,
 *    which is *exactly* the hero grid's side padding — that equality is what
 *    puts the leaf mark and the Get Started button on the wordmark's optical
 *    edges. Change one and you must change the other.
 * 2. Every colour comes from a theme object rather than a literal, so the bar
 *    can invert over the dark acts. See navTheme.ts.
 *
 * The bar's show/hide transform is written directly to the node by the
 * engine's scroll handler, not through React.
 */

import Image from 'next/image';
import Link from 'next/link';
import type { NavTheme } from './navTheme';

/** Companion pages. The design ships these as sibling .dc.html files; here
 *  they are app routes. Only Home exists as a section — the rest navigate. */
const PAGES = [
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
  fontFamily: "'DM Sans',sans-serif", fontWeight: 500, fontSize: 13.5,
  letterSpacing: '0.02em', transition: 'color 400ms', whiteSpace: 'nowrap',
};

export function Navbar({
  navRef,
  heroMounted,
  exploring,
  navMenuOpen,
  theme,
  onToggleMenu,
  onCloseMenu,
  onLogoClick,
  onSignIn,
  onGetStarted,
}: {
  navRef: React.RefObject<HTMLElement | null>;
  heroMounted: boolean;
  exploring: boolean;
  navMenuOpen: boolean;
  theme: NavTheme;
  onToggleMenu: () => void;
  onCloseMenu: () => void;
  onLogoClick: () => void;
  onSignIn: () => void;
  onGetStarted: () => void;
}) {
  return (
    <nav
      ref={navRef}
      className="sapling-nav"
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 50,
        // must stay equal to the hero grid's horizontal padding
        padding: '16px max(4.2vw,22px)',
        opacity: exploring ? 0 : heroMounted ? 1 : 0,
        pointerEvents: exploring ? 'none' : 'auto',
        transform: heroMounted ? 'translateY(0)' : 'translateY(-30px)',
        transition:
          'opacity 800ms cubic-bezier(0.22,1,0.36,1), transform 400ms cubic-bezier(0.22,1,0.36,1)',
      }}
    >
      {/* blurred band; masked so it dissolves rather than ending on a hard edge */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute', left: 0, right: 0, top: 0, height: 92,
          pointerEvents: 'none',
          backdropFilter: 'blur(9px)', WebkitBackdropFilter: 'blur(9px)',
          background: theme.scrim, transition: 'background 600ms ease',
          maskImage: 'linear-gradient(180deg, #000 0%, #000 44%, transparent 100%)',
          WebkitMaskImage: 'linear-gradient(180deg, #000 0%, #000 44%, transparent 100%)',
        }}
      />

      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20 }}>
        <button
          onClick={onLogoClick}
          style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          <Image
            src="/sapling-icon.svg" alt="" width={26} height={26} priority
            style={{ position: 'relative', top: -2, filter: theme.iconFilter, transition: 'filter 500ms' }}
          />
          <span
            style={{
              fontFamily: "'Spectral',Georgia,serif", fontWeight: 700, fontSize: 20,
              color: theme.logo, letterSpacing: '-0.02em', lineHeight: 1.1,
              transition: 'color 500ms',
            }}
          >
            Sapling
          </span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap', minWidth: 0 }}>
          {/* compact trigger, swapped in for the tab row below 1180px */}
          <button
            onClick={onToggleMenu}
            type="button"
            className="nav-compact"
            aria-haspopup="menu"
            aria-expanded={navMenuOpen}
            title="Pages"
            style={{ ...TAB, display: 'none', alignItems: 'center', gap: 7, background: 'none', border: 'none', cursor: 'pointer', color: theme.ink, padding: 0 }}
          >
            Pages
            <svg
              width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
              style={{ flexShrink: 0, transition: 'transform 240ms', transform: navMenuOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          <div className="nav-tabs" style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap' }}>
            {/* Home is the current page: it scrolls rather than navigating */}
            <button
              onClick={onLogoClick}
              type="button"
              aria-current="page"
              style={{ ...TAB, fontWeight: 600, background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: theme.inkHi }}
            >
              Home
            </button>
            {PAGES.map((p) => (
              <Link key={p.href} href={p.href} className="ld-navlink" style={{ ...TAB, color: theme.ink }}>
                {p.label}
              </Link>
            ))}
            <a
              href={GITHUB_URL} target="_blank" rel="noopener noreferrer" title="Sapling on GitHub"
              className="ld-navlink"
              style={{ ...TAB, display: 'flex', alignItems: 'center', gap: 7, color: theme.ink }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ flexShrink: 0 }}>
                <path d="M12 .5C5.73.5.75 5.48.75 11.75c0 4.99 3.24 9.22 7.73 10.71.57.1.78-.25.78-.55v-1.93c-3.14.68-3.81-1.51-3.81-1.51-.51-1.3-1.25-1.65-1.25-1.65-1.03-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.72.39-1.22.71-1.5-2.5-.29-5.14-1.25-5.14-5.58 0-1.23.44-2.24 1.16-3.03-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.16a10.7 10.7 0 0 1 5.64 0c2.15-1.46 3.09-1.16 3.09-1.16.62 1.55.23 2.7.12 2.98.72.79 1.16 1.8 1.16 3.03 0 4.34-2.65 5.29-5.16 5.57.41.35.77 1.04.77 2.1v3.11c0 .3.2.66.79.55a11.26 11.26 0 0 0 7.72-10.71C23.25 5.48 18.27.5 12 .5z" />
              </svg>
              GitHub
            </a>
            <a
              href={KOFI_URL} target="_blank" rel="noopener noreferrer" title="Support Sapling on Ko-fi"
              className="ld-kofi"
              style={{
                display: 'flex', alignItems: 'center', gap: 7, padding: '6px 13px 6px 10px',
                borderRadius: 99, border: `1px solid ${theme.pillBorder}`, background: theme.pillBg,
                color: theme.pillFg, fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
                fontSize: 13, letterSpacing: '0.01em', transition: 'all 400ms',
              }}
            >
              <Image src="/kofi-symbol.png" alt="" width={17} height={17} style={{ objectFit: 'contain' }} />
              Support us
            </a>
          </div>

          <span aria-hidden="true" style={{ width: 1, height: 16, background: theme.rule, flex: '0 0 auto', transition: 'background 500ms' }} />

          <button
            onClick={onSignIn}
            className="ld-navlink"
            style={{ ...TAB, background: 'none', border: 'none', cursor: 'pointer', color: theme.ink }}
          >
            Sign In
          </button>
          <button
            onClick={onGetStarted}
            style={{
              background: theme.btnBg, color: theme.btnFg, border: 'none', borderRadius: 6,
              padding: '8px 16px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
              fontSize: 13.5, cursor: 'pointer',
              transition: 'filter 200ms, background 500ms, color 500ms',
            }}
            className="ld-btn-solid"
          >
            Get Started
          </button>
        </div>

        {/* compact menu */}
        <div
          onClick={onCloseMenu}
          className="nav-panel"
          role="menu"
          style={{
            position: 'absolute', right: 0, top: 'calc(100% + 10px)', minWidth: 180, zIndex: 60,
            padding: 6, borderRadius: 12, background: 'rgba(253,252,249,0.96)',
            backdropFilter: 'blur(12px)', border: '1px solid rgba(18,32,26,0.1)',
            boxShadow: '0 16px 38px -18px rgba(18,32,26,0.4)',
            display: navMenuOpen ? 'flex' : 'none',
            flexDirection: 'column', gap: 1, transformOrigin: 'top right',
            opacity: navMenuOpen ? 1 : 0,
            transform: navMenuOpen ? 'scale(1)' : 'scale(0.96)',
            transition: 'opacity 200ms ease, transform 240ms cubic-bezier(0.22,1,0.36,1)',
          }}
        >
          <button
            onClick={onLogoClick}
            type="button"
            aria-current="page"
            style={{
              textAlign: 'left', border: 'none', cursor: 'pointer',
              fontFamily: "'DM Sans',sans-serif", fontWeight: 600, padding: '9px 12px',
              borderRadius: 8, fontSize: 13.5, color: '#12201A', background: 'rgba(12,86,56,0.07)',
            }}
          >
            Home
          </button>
          {PAGES.map((p) => (
            <Link
              key={p.href} href={p.href} className="ld-navmenu-item"
              style={{ padding: '9px 12px', borderRadius: 8, fontSize: 13.5, color: '#33443B' }}
            >
              {p.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
