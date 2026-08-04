'use client';

/**
 * Fixed transparent navbar.
 *
 * Ported from `Sapling Landing v4.dc.html`. Fades and slides in with the
 * hero, auto-hides on downward scroll past half a viewport (driven
 * imperatively from the scroll listener, not from state), collapses to a
 * "Pages" dropdown under 1180px, and hides entirely in explore mode.
 */

import Image from 'next/image';
import type { RefObject } from 'react';

/**
 * Marketing pages the design links to. `/about` exists today; the rest are
 * the design's intended routes and are not built yet.
 */
const PAGES: { label: string; href: string }[] = [
  { label: 'About', href: '/about' },
  { label: 'Team', href: '/team' },
  { label: 'Wiki', href: '/wiki' },
  { label: 'Gallery', href: '/gallery' },
  { label: 'News', href: '/news' },
  { label: 'FAQ', href: '/faq' },
];

const LINK: React.CSSProperties = {
  color: '#61726A', fontFamily: "'DM Sans',sans-serif", fontWeight: 500,
  fontSize: 13.5, letterSpacing: '0.02em', transition: 'color 300ms',
};

export interface NavbarProps {
  navRef: RefObject<HTMLElement | null>;
  heroMounted: boolean;
  exploring: boolean;
  navMenuOpen: boolean;
  onToggleMenu: () => void;
  onCloseMenu: () => void;
  onLogoClick: () => void;
  onGetStarted: () => void;
}

export function Navbar({
  navRef, heroMounted, exploring, navMenuOpen,
  onToggleMenu, onCloseMenu, onLogoClick, onGetStarted,
}: NavbarProps) {
  const hidden = exploring;
  return (
    <nav
      ref={navRef as RefObject<HTMLElement>}
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 50,
        padding: '16px 24px', background: 'transparent',
        opacity: hidden ? 0 : heroMounted ? 1 : 0,
        pointerEvents: hidden ? 'none' : 'auto',
        transform: heroMounted ? 'translateY(0)' : 'translateY(-30px)',
        transition:
          'opacity 800ms cubic-bezier(0.22,1,0.36,1), transform 400ms cubic-bezier(0.22,1,0.36,1)',
      }}
    >
      <div
        style={{
          maxWidth: 'min(1320px, 92%)', margin: '0 auto', display: 'flex',
          alignItems: 'center', justifyContent: 'space-between', gap: 20, position: 'relative',
        }}
      >
        <button
          onClick={onLogoClick}
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          }}
        >
          <Image
            src="/sapling-icon.svg" alt="" width={26} height={26}
            style={{ width: 26, height: 26, position: 'relative', top: -2 }}
          />
          <span
            style={{
              fontFamily: "'Spectral',Georgia,serif", fontWeight: 700, fontSize: 20,
              color: '#0C5638', letterSpacing: '-0.02em', lineHeight: 1.1,
            }}
          >
            Sapling
          </span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap', minWidth: 0 }}>
          <button
            onClick={onToggleMenu}
            type="button"
            className="nav-compact v4-navlink"
            aria-haspopup="menu"
            aria-expanded={navMenuOpen}
            title="Pages"
            style={{ ...LINK, display: 'none', alignItems: 'center', gap: 7, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
          >
            Pages
            <svg
              width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
              style={{
                flexShrink: 0, transition: 'transform 240ms',
                transform: `rotate(${navMenuOpen ? 180 : 0}deg)`,
              }}
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          <div className="nav-tabs" style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap' }}>
            {PAGES.map((p) => (
              <a key={p.href} href={p.href} className="v4-navlink" style={LINK}>
                {p.label}
              </a>
            ))}
            <a
              href="https://github.com/SaplingLearn/Sapling"
              target="_blank" rel="noopener noreferrer" title="Sapling on GitHub"
              className="v4-navlink"
              style={{ ...LINK, display: 'flex', alignItems: 'center', gap: 7 }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style={{ flexShrink: 0 }}>
                <path d="M12 .5C5.73.5.75 5.48.75 11.75c0 4.99 3.24 9.22 7.73 10.71.57.1.78-.25.78-.55v-1.93c-3.14.68-3.81-1.51-3.81-1.51-.51-1.3-1.25-1.65-1.25-1.65-1.03-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.72.39-1.22.71-1.5-2.5-.29-5.14-1.25-5.14-5.58 0-1.23.44-2.24 1.16-3.03-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.16a10.7 10.7 0 0 1 5.64 0c2.15-1.46 3.09-1.16 3.09-1.16.62 1.55.23 2.7.12 2.98.72.79 1.16 1.8 1.16 3.03 0 4.34-2.65 5.29-5.16 5.57.41.35.77 1.04.77 2.1v3.11c0 .3.2.66.79.55a11.26 11.26 0 0 0 7.72-10.71C23.25 5.48 18.27.5 12 .5z" />
              </svg>
              GitHub
            </a>
            <a
              href="https://ko-fi.com/saplinglearn"
              target="_blank" rel="noopener noreferrer" title="Support Sapling on Ko-fi"
              className="v4-kofi"
              style={{
                display: 'flex', alignItems: 'center', gap: 7, padding: '6px 13px 6px 10px',
                borderRadius: 99, border: '1px solid rgba(18,32,26,0.14)',
                background: 'rgba(253,252,249,0.72)', color: '#12201A',
                fontFamily: "'DM Sans',sans-serif", fontWeight: 600, fontSize: 13,
                letterSpacing: '0.01em', transition: 'all 220ms',
              }}
            >
              <Image
                src="/kofi-symbol.png" alt="" width={17} height={17}
                style={{ width: 17, height: 17, objectFit: 'contain' }}
              />
              Support us
            </a>
          </div>

          <span aria-hidden="true" style={{ width: 1, height: 16, background: 'rgba(18,32,26,0.14)', flex: '0 0 auto' }} />
          <button className="v4-navlink" style={{ ...LINK, background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>
            Sign In
          </button>
          <button
            onClick={onGetStarted}
            className="v4-btn-solid"
            style={{
              background: '#0C5638', color: '#fff', border: 'none', borderRadius: 6,
              padding: '8px 16px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
              fontSize: 13.5, cursor: 'pointer', transition: 'filter 200ms',
            }}
          >
            Get Started
          </button>
        </div>

        <div
          onClick={onCloseMenu}
          className="nav-panel"
          role="menu"
          style={{
            position: 'absolute', right: 0, top: 'calc(100% + 10px)', minWidth: 180, zIndex: 60,
            padding: 6, borderRadius: 12, background: 'rgba(253,252,249,0.96)',
            backdropFilter: 'blur(12px)', border: '1px solid rgba(18,32,26,0.1)',
            boxShadow: '0 16px 38px -18px rgba(18,32,26,0.4)',
            display: 'flex', flexDirection: 'column', gap: 1, transformOrigin: 'top right',
            transition: 'opacity 200ms ease, transform 240ms cubic-bezier(0.22,1,0.36,1)',
            opacity: navMenuOpen ? 1 : 0,
            transform: navMenuOpen ? 'scale(1) translateY(0)' : 'scale(0.96) translateY(-6px)',
            pointerEvents: navMenuOpen ? 'auto' : 'none',
          }}
        >
          {PAGES.map((p) => (
            <a
              key={p.href} href={p.href} className="v4-navmenu-item"
              style={{ padding: '9px 12px', borderRadius: 8, fontSize: 13.5, color: '#33443B' }}
            >
              {p.label}
            </a>
          ))}
        </div>
      </div>
    </nav>
  );
}
