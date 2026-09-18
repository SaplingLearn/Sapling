'use client';

/**
 * Fixed navbar — full-bleed and transparent, with scroll-driven colour.
 *
 * No scrim behind it. The bar used to carry a 92px blurred band tinted
 * off-white, which read as a frosted overlay across the top of the page;
 * the bar now sits directly on whatever is under it.
 *
 * The words are set bold in Sapling's own colours, with no shadow behind
 * them. A scrim, per-group capsules, a glow on the glyphs and ink that
 * switched with the backdrop were all tried and rejected.
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
 * The bar is the wordmark and the two actions, nothing else. v4's page-link
 * row (About, Wiki, Gallery, News, FAQ), its under-1280px "Pages" dropdown
 * and a Ko-fi "Support us" pill were each restored here for a while and each
 * dropped again as unnecessary on the landing: the footer (Closing.tsx) is
 * the complete index, and the companion pages keep their own full navbar in
 * CompanionShell. The divider that fenced the actions off from the row went
 * with the row. The `rule` and `pill*` fields in navTheme.ts are unused.
 *
 * The bar's show/hide transform is written directly to the node by the
 * engine's scroll handler, not through React.
 */

import Image from 'next/image';
import type { NavTheme } from './navTheme';

const TAB: React.CSSProperties = {
  fontFamily: "'DM Sans',sans-serif", fontWeight: 700, fontSize: 16,
  letterSpacing: '0.02em', transition: 'color 400ms', whiteSpace: 'nowrap',
};

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
  return (
    <nav
      ref={navRef}
      className="sapling-nav"
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 50,
        // must stay equal to the hero grid's horizontal padding
        // (the phone override lives in globals.css, `.ld-nav-*`)
        padding: '20px max(4.2vw,22px)',
        opacity: exploring ? 0 : heroMounted ? 1 : 0,
        pointerEvents: exploring ? 'none' : 'auto',
        transform: heroMounted ? 'translateY(0)' : 'translateY(-30px)',
        transition:
          'opacity 800ms cubic-bezier(0.22,1,0.36,1), transform 400ms cubic-bezier(0.22,1,0.36,1)',
      }}
    >
      <div className="ld-nav-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20 }}>
        <button
          onClick={onLogoClick}
          className="ld-nav-logo"
          style={{ display: 'flex', alignItems: 'center', gap: 5, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          <Image
            src="/sapling-icon.svg" alt="" width={32} height={32} priority
            className="ld-nav-mark"
            style={{ position: 'relative', top: -3, filter: theme.iconFilter, transition: 'filter 500ms' }}
          />
          <span
            className="ld-nav-word"
            style={{
              fontFamily: "'Spectral',Georgia,serif", fontWeight: 700, fontSize: 25,
              color: theme.logo, letterSpacing: '-0.02em', lineHeight: 1.1,
              transition: 'color 500ms',
            }}
          >
            Sapling
          </span>
        </button>

        <div className="ld-nav-actions" style={{ display: 'flex', alignItems: 'center', gap: 22, flexWrap: 'nowrap', flexShrink: 0 }}>
          <button
            onClick={onSignIn}
            className="ld-navlink ld-nav-signin"
            style={{ ...TAB, background: 'none', border: 'none', cursor: 'pointer', color: theme.ink }}
          >
            Sign In
          </button>
          <button
            onClick={onGetStarted}
            style={{
              background: theme.btnBg, color: theme.btnFg, border: 'none', borderRadius: 7,
              padding: '11px 21px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600,
              fontSize: 16, cursor: 'pointer', boxShadow: theme.lift, whiteSpace: 'nowrap',
              transition: 'filter 200ms, background 500ms, color 500ms',
            }}
            className="ld-btn-solid ld-nav-cta"
          >
            Get Started
          </button>
        </div>
      </div>
    </nav>
  );
}
