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
 * Note these pages use the WARM paper palette (#f4f1ea / #1a1814 / --brand-forest),
 * not the landing page's cool one. That is deliberate in the design and
 * matches the app's existing public pages — do not "unify" them.
 */

import Link from 'next/link';
import { SaplingWordmark } from '@/components/SaplingWordmark';
import { PAGE_MAX, PAGE_PAD } from '@/lib/landing/companionType';
import { cn } from "@/lib/cn";

/**
 * Page order as it appears in the footer. No Home entry: the wordmark in the
 * header is the way back to the landing page on every companion surface, and
 * a second link for it just crowded the row.
 */
export const COMPANION_NAV = [
  // About also carries the team: /team was folded into it and the route
  // deleted. It had never published — five empty portrait frames, unlinked and
  // noindexed, waiting on photographs — so the writing moved to the page people
  // already reach and the frames were dropped.
  { label: 'About', href: '/about' },
  { label: 'Wiki', href: '/wiki' },
  { label: 'Gallery', href: '/gallery' },
  { label: 'News', href: '/news' },
  { label: 'FAQ', href: '/faq' },
];

/**
 * The three links below the design's own footer row. They used to be plain
 * `<Link>`s while COMPANION_NAV entries got current-page styling, so landing
 * on /careers, /terms or /privacy left the footer with nothing marked — the
 * only pages in the shell where you could not tell where you were.
 */
export const COMPANION_EXTRA_NAV = [
  { label: 'Careers', href: '/careers' },
  { label: 'Terms of Service', href: '/terms' },
  { label: 'Privacy Policy', href: '/privacy' },
];

const GITHUB_URL = 'https://github.com/SaplingLearn/Sapling';
const KOFI_URL = 'https://ko-fi.com/saplinglearn';

export function CompanionShell({
  current,
  children,
}: {
  /** href of the page being rendered, so its footer link can claim aria-current. */
  current: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex flex-col bg-ink-50 text-ink-800 font-sans">
      {/* Geometry here is locked to the landing navbar: same horizontal
          padding, same 16px/16px vertical padding, same 92px masked scrim.
          The companion sources inset their bar to `min(1320px,92%)`, which
          lands it ~32px further in than the landing bar and 18px taller — so
          the mark visibly jumped when you navigated off `/`. Full-bleed wins;
          if you change `max(4.2vw,22px)` here, change it in Navbar.tsx and the
          hero grid too. Only the palette stays warm. */}
      <header className="sticky top-0 z-50 py-4 px-[max(4.2vw,22px)] pointer-events-none">
        <div
          aria-hidden="true"
          className="absolute left-0 right-0 top-0 h-23 [backdrop-filter:blur(9px)] [-webkit-backdrop-filter:blur(9px)] [background:linear-gradient(180deg,_#f4f1ea_0%,_#f4f1ea_44%,_rgba(244,241,234,0.82)_66%,_rgba(244,241,234,0.45)_82%,_rgba(244,241,234,0)_100%)] [mask-image:linear-gradient(180deg,_#000_0%,_#000_44%,_rgba(0,0,0,0.78)_66%,_rgba(0,0,0,0.42)_82%,_rgba(0,0,0,0)_100%)] [-webkit-mask-image:linear-gradient(180deg,_#000_0%,_#000_44%,_rgba(0,0,0,0.78)_66%,_rgba(0,0,0,0.42)_82%,_rgba(0,0,0,0)_100%)]"
        />
        <div className="flex items-center justify-between gap-5 relative pointer-events-auto">
          <Link href="/" className="flex items-center flex-[0_0_auto]">
            <SaplingWordmark width={104} />
          </Link>

          <div className="flex items-center gap-4.5 flex-nowrap min-w-0">
            <Link href="/?signin=1" className="cp-navlink font-sans text-[13.5px] tracking-[0.02em] [transition:color_300ms] whitespace-nowrap text-text-muted font-medium">Sign In</Link>
            <Link
              href="/#newsletter"
              className="cp-cta [background:var(--brand-forest)] text-accent-fg rounded-sm py-2 px-4 font-sans font-semibold text-[13.5px] whitespace-nowrap [transition:filter_200ms]"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      {/* One content box for every companion page, footer included. Pages
          used to size their own and had all drifted — 880 on /about, /faq and
          /team, 1060 on /wiki, 1180 on /gallery, 1240 on /news, 928 on an
          article, 1280 on the footer — so content jumped left and right as you
          navigated. Pages render content now, not a container. */}
      <main
        className="flex-1 min-w-0 w-full my-0 mx-auto box-border" style={{ maxWidth: PAGE_MAX, padding: `40px ${PAGE_PAD}px 64px` }}
      >
        {children}
      </main>

      <footer className="border-t border-t-[rgba(42,39,31,0.10)] bg-ink-0 box-border" style={{ padding: `48px ${PAGE_PAD}px` }}>
        <div className="my-0 mx-auto box-border flex flex-wrap items-center justify-between gap-6" style={{ maxWidth: PAGE_MAX }}>
          <div className="flex items-center gap-2">
            <SaplingWordmark width={64} />
            <span className="text-base text-text-muted">© 2026</span>
          </div>
          <div className="flex flex-wrap gap-6">
            {COMPANION_NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={n.href === current ? 'page' : undefined}
                className={cn("cp-navlink", "text-base", n.href === current ? "text-ink-800" : "text-text-muted", n.href === current ? "font-semibold" : "font-normal")}
              >
                {n.label}
              </Link>
            ))}
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="cp-navlink text-base text-text-muted">GitHub</a>
            <a href={KOFI_URL} target="_blank" rel="noopener noreferrer" className="cp-navlink text-base text-text-muted">Support us</a>
            {/* The design's companion footer stops at the nav links. These three
                are ours: /about used to be the only page linking them, so
                folding it into this shell would otherwise orphan /careers
                outright and leave the legal pages unreachable from any
                companion page. */}
            {COMPANION_EXTRA_NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={n.href === current ? 'page' : undefined}
                className={cn("cp-navlink", "text-base", n.href === current ? "text-ink-800" : "text-text-muted", n.href === current ? "font-semibold" : "font-normal")}
              >
                {n.label}
              </Link>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}
