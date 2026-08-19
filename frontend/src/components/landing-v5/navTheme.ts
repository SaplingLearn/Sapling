'use client';

/**
 * The navbar's two colour states, and the scroll rule that picks between them.
 *
 * Every value here is lifted verbatim from `renderVals()` in
 * `Sapling Landing v5.dc.html`, which builds the full two-theme table —
 * and then never uses the dark half, because the scroll handler hardwires
 * `const wantDark = false`.
 *
 * We wire it up. The page passes through one full-bleed dark act; leaving the
 * navbar in its light palette over it is plainly a stub rather than a design
 * intent, and the design brief calls for the interpolation. The rule
 * below is the one the dead code was shaped for: whichever section owns the
 * vertical centre of the viewport decides the theme.
 */

import { useEffect, useState } from 'react';

export interface NavTheme {
  /** Resting link colour. */
  ink: string;
  /** Hover / current-page colour. */
  inkHi: string;
  logo: string;
  /** CSS filter applied to the leaf mark, to lift it off a dark ground. */
  iconFilter: string;
  rule: string;
  pillBorder: string;
  pillBg: string;
  pillFg: string;
  btnBg: string;
  btnFg: string;
  /** The 92px blurred band behind the bar. */
  scrim: string;
}

export const NAV_LIGHT: NavTheme = {
  ink: '#61726A',
  inkHi: '#12201A',
  logo: '#0C5638',
  iconFilter: 'none',
  rule: 'rgba(18,32,26,0.14)',
  pillBorder: 'rgba(18,32,26,0.14)',
  pillBg: 'rgba(253,252,249,0.72)',
  pillFg: '#12201A',
  btnBg: '#0C5638',
  btnFg: '#fff',
  scrim:
    'linear-gradient(180deg, rgba(240,244,242,0.94) 0%, rgba(240,244,242,0.5) 52%, rgba(240,244,242,0) 100%)',
};

export const NAV_DARK: NavTheme = {
  ink: 'rgba(214,234,222,0.62)',
  inkHi: '#F2FAF5',
  logo: '#EAF3EC',
  iconFilter: 'brightness(1.85) saturate(0.95)',
  rule: 'rgba(214,234,222,0.2)',
  pillBorder: 'rgba(214,234,222,0.2)',
  pillBg: 'rgba(255,255,255,0.06)',
  pillFg: '#EAF3EC',
  btnBg: '#EAF3EC',
  btnFg: '#07301E',
  scrim:
    'linear-gradient(180deg, rgba(6,23,16,0.88) 0%, rgba(6,23,16,0.42) 52%, rgba(6,23,16,0) 100%)',
};

/**
 * The sections that sit on a dark ground.
 *
 * Only `act-graph` qualifies. `act-ingest` has no dark background at all, and
 * `act-tutor` paints a light mint gradient (`rgba(230,242,232,…)`) over the
 * page ground `#f0f4f2`. Listing either of those made the nav switch to
 * `NAV_DARK` — `ink: rgba(214,234,222,0.62)` on near-white — which is
 * unreadable. Only add a section here once it actually renders dark.
 */
const DARK_SECTIONS = ['act-graph'];

/**
 * True while the viewport's vertical centre sits inside a dark act.
 *
 * Reads layout on scroll, but only `getBoundingClientRect()` on at most
 * three elements and only when the flag would actually change — the
 * transitions themselves are CSS, so there is no per-frame work here.
 */
export function useNavDark(enabled = true): boolean {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let raf = 0;

    const read = () => {
      raf = 0;
      const mid = window.innerHeight / 2;
      const inDark = DARK_SECTIONS.some((id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        const r = el.getBoundingClientRect();
        return r.top <= mid && r.bottom >= mid;
      });
      setDark((prev) => (prev === inDark ? prev : inDark));
    };

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(read);
    };

    read();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, [enabled]);

  return dark;
}
