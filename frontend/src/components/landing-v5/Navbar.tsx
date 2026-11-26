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

import { SaplingWordmark } from '@/components/SaplingWordmark';
import type { NavTheme } from './navTheme';
import { cn } from "@/lib/cn";

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
      className={cn("sapling-nav", "fixed top-0 left-0 right-0 z-50 py-5 px-[max(4.2vw,22px)] [transition:opacity_800ms_cubic-bezier(0.22,1,0.36,1),_transform_400ms_cubic-bezier(0.22,1,0.36,1)]", exploring ? "pointer-events-none" : "pointer-events-auto", heroMounted ? "[transform:translateY(0)]" : "[transform:translateY(-30px)]")}
      style={{ opacity: exploring ? 0 : heroMounted ? 1 : 0 }}
    >
      <div className="ld-nav-row flex items-center justify-between gap-5">
        <button
          onClick={onLogoClick}
          className="ld-nav-logo flex items-center gap-[5px] [background:none] border-0 cursor-pointer p-0"
        >
          <SaplingWordmark
            width={132}
            className="ld-nav-mark"
            style={{ filter: theme.logoFilter, transition: 'filter 500ms' }}
          />
        </button>

        <div className="ld-nav-actions flex items-center gap-5.5 flex-nowrap shrink-0">
          <button
            data-testid="signin-trigger"
            onClick={onSignIn}
            className="ld-navlink ld-nav-signin font-sans font-bold text-lg tracking-[0.02em] [transition:color_400ms] whitespace-nowrap [background:none] border-0 cursor-pointer"
            style={{ color: theme.ink }}
          >
            Sign In
          </button>
          <button
            data-testid="landing-get-started"
            onClick={onGetStarted}
            style={{ background: theme.btnBg, color: theme.btnFg, boxShadow: theme.lift }}
            className="ld-btn-solid ld-nav-cta border-0 rounded-[7px] py-[11px] px-[21px] font-sans font-semibold text-lg cursor-pointer whitespace-nowrap [transition:filter_200ms,_background_500ms,_color_500ms]"
          >
            Get Started
          </button>
        </div>
      </div>
    </nav>
  );
}
