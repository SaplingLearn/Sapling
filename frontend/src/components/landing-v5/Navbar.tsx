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
 * The page-link row is v4's, restored: the Ko-fi link is the bordered pill with
 * its mark, and under 860px the row collapses into a "Pages" dropdown rather
 * than vanishing. The v5 port had moved the whole row to the footer, leaving
 * the bar with only the wordmark and the two actions.
 *
 * It differs from v4 in one respect: the row is centred on the bar instead of
 * riding in the right-hand cluster. It is absolutely positioned to get there,
 * because the wordmark and the actions that flank it are not the same width —
 * a third flex child would centre on the gap between them, not on the bar. Out
 * of the flow it also cannot push Sign In or Get Started off their edge, which
 * is the constraint that motivated the centring in the first place. The 860px
 * collapse is what keeps a centred row from colliding with either flank: the
 * arithmetic runs out around 790px, comfortably below it.
 *
 * What did NOT come back: GitHub, Terms of Service and Privacy Policy, which
 * are footer-only now. Team is absent because the page is: it was folded into
 * /about and the route deleted, so About is the link that reaches it. Five
 * links instead of v4's eight, so the row collapses at 860px where v4 needed
 * 1180px. The footer remains the complete index. The companion pages keep
 * their own full navbar in CompanionShell.
 *
 * Where v4 hardcoded this row's colours they come off the theme here — `rule`
 * for the divider and `pillBorder`/`pillBg`/`pillFg` for the Ko-fi pill. Those
 * four fields have been sitting unused in navTheme.ts since the port dropped
 * the row; this is what they were defined for.
 *
 * The menu's open state is local. v4 lifted it to the page because its scroll
 * engine closed the panel; v5's does not, so the panel closes on its own —
 * item click, outside click, or Escape.
 *
 * The bar's show/hide transform is written directly to the node by the
 * engine's scroll handler, not through React.
 */

import { useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import type { NavTheme } from './navTheme';

const TAB: React.CSSProperties = {
  fontFamily: "'DM Sans',sans-serif", fontWeight: 500, fontSize: 13.5,
  letterSpacing: '0.02em', transition: 'color 400ms', whiteSpace: 'nowrap',
};

/** Page links the bar carries. The footer (Closing.tsx) keeps the full set. */
const PAGES: { label: string; href: string }[] = [
  { label: 'About', href: '/about' },
  { label: 'Wiki', href: '/wiki' },
  { label: 'Gallery', href: '/gallery' },
  { label: 'News', href: '/news' },
  { label: 'FAQ', href: '/faq' },
];

const KOFI_URL = 'https://ko-fi.com/saplinglearn';

export function Navbar({
  navRef,
  heroMounted,
  exploring,
  theme,
  onLogoClick,
  onSignIn,
  onGetStarted,
}: {
  navRef: React.RefObject<HTMLElement | null>;
  heroMounted: boolean;
  exploring: boolean;
  theme: NavTheme;
  onLogoClick: () => void;
  onSignIn: () => void;
  onGetStarted: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuWrapRef = useRef<HTMLDivElement | null>(null);

  // Close the Pages panel on an outside click or Escape. v4 got this from the
  // page, which owned the open state; here the panel owns its own dismissal.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!menuWrapRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  // Explore mode needs no handling of its own: it is entered by a pointer-up
  // on the graph canvas (useLanding.ts:484), which the outside-click listener
  // above sees first and closes the panel on.

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

        {/* Page row, centred on the bar rather than on the space between the
            wordmark and the actions — those two flank it and are not the same
            width, so a third flex child would sit off-centre. Taking the row
            out of the flow centres it on the viewport AND leaves the actions
            exactly where they were: the cluster below is still the only thing
            `space-between` pushes to the right edge. */}
        <div
          className="nav-tabs"
          style={{
            position: 'absolute', left: '50%', top: '50%',
            transform: 'translate(-50%,-50%)',
            display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap',
          }}
        >
          {PAGES.map((p) => (
            <Link key={p.href} href={p.href} className="ld-navlink" style={{ ...TAB, color: theme.ink, textDecoration: 'none' }}>
              {p.label}
            </Link>
          ))}
          <a
            href={KOFI_URL}
            target="_blank" rel="noopener noreferrer" title="Support Sapling on Ko-fi"
            className="ld-kofi"
            style={{
              display: 'flex', alignItems: 'center', gap: 7, padding: '6px 13px 6px 10px',
              borderRadius: 99, border: '1px solid ' + theme.pillBorder,
              background: theme.pillBg, color: theme.pillFg, textDecoration: 'none',
              fontFamily: "'DM Sans',sans-serif", fontWeight: 600, fontSize: 13,
              letterSpacing: '0.01em', transition: 'all 220ms', whiteSpace: 'nowrap',
            }}
          >
            <Image
              src="/kofi-symbol.png" alt="" width={17} height={17}
              style={{ width: 17, height: 17, objectFit: 'contain' }}
            />
            Support us
          </a>
        </div>

        <div ref={menuWrapRef} style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'nowrap', minWidth: 0 }}>
          {/* Collapsed form. `display:none` here, flipped to flex under 860px
              by the paired rule in globals.css. */}
          <button
            onClick={() => setMenuOpen((v) => !v)}
            type="button"
            className="nav-compact ld-navlink"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title="Pages"
            style={{ ...TAB, display: 'none', alignItems: 'center', gap: 7, background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: theme.ink }}
          >
            Pages
            <svg
              width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
              style={{
                flexShrink: 0, transition: 'transform 240ms',
                transform: menuOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              }}
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          {/* Kept, though the row it used to divide is now centred: it still
              fences the actions off, and dropping it would slide Sign In and
              Get Started 19px right — the one thing this change must not do. */}
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

          <div
            onClick={() => setMenuOpen(false)}
            className="nav-panel"
            role="menu"
            style={{
              position: 'absolute', right: 0, top: 'calc(100% + 10px)', minWidth: 180, zIndex: 60,
              padding: 6, borderRadius: 12, background: 'rgba(253,252,249,0.96)',
              backdropFilter: 'blur(12px)', border: '1px solid rgba(18,32,26,0.1)',
              boxShadow: '0 16px 38px -18px rgba(18,32,26,0.4)',
              display: 'flex', flexDirection: 'column', gap: 1, transformOrigin: 'top right',
              transition: 'opacity 200ms ease, transform 240ms cubic-bezier(0.22,1,0.36,1)',
              opacity: menuOpen ? 1 : 0,
              transform: menuOpen ? 'scale(1) translateY(0)' : 'scale(0.96) translateY(-6px)',
              pointerEvents: menuOpen ? 'auto' : 'none',
            }}
          >
            {PAGES.map((p) => (
              <Link
                key={p.href} href={p.href} className="ld-navmenu-item"
                style={{ padding: '9px 12px', borderRadius: 8, fontSize: 13.5, color: '#33443B', textDecoration: 'none' }}
              >
                {p.label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </nav>
  );
}
