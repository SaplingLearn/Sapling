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
 * The page-link row (About/Team/Wiki/…, GitHub, Ko-fi) moved to the footer —
 * the bar now carries only the wordmark and the two actions. The companion
 * pages keep their own full navbar in CompanionShell.
 *
 * The bar's show/hide transform is written directly to the node by the
 * engine's scroll handler, not through React.
 */

import Image from 'next/image';
import type { NavTheme } from './navTheme';

const TAB: React.CSSProperties = {
  fontFamily: "'DM Sans',sans-serif", fontWeight: 500, fontSize: 13.5,
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
      </div>
    </nav>
  );
}
