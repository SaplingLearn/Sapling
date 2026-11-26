'use client';

/**
 * The final CTA and the footer.
 *
 * Ported from `Sapling Landing v5.dc.html`. The source's fixed section-jump
 * pill (and its top reading-progress hairline) was removed by request — no
 * floating scroll-position chrome.
 *
 * Note the CTA is heading + line + button, nothing more. The source's logic
 * class still carries a whole "plant a concept" interaction — `plantVal`,
 * `plantedCount`, `_plant()`, a localStorage-backed grove and a canvas ref —
 * but no markup in the file references any of it, so it can never run. That
 * is the fourth such dead branch in this file, after `wantDark = false`, the
 * unreferenced `heroWipe`/`heroChar` keyframes, and the hero mode switcher.
 * Not ported; recoverable from the source if it is ever wired up.
 */

import Link from 'next/link';
import { SaplingWordmark } from '@/components/SaplingWordmark';
import { DragField } from './DragField';
import { FadeIn } from '@/components/landing/anim';

const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.30, s: { left: '6.5%', top: '22%', width: 7.4, height: 7.4, background: '#7B9E51', opacity: 0.44, animation: 'nodeFloatA 15s ease-in-out -6s infinite' } },
  { d: 0.44, s: { right: '8.2%', top: '31%', width: 6.2, height: 6.2, background: '#B1D28B', opacity: 0.5, animation: 'nodeFloatB 13s ease-in-out -3s infinite' } },
  { d: 0.22, s: { right: '13.6%', top: '74%', width: 9.6, height: 9.6, background: '#68951F', opacity: 0.4, boxShadow: '0 0 22px #68951F66', animation: 'nodeFloatA 18s ease-in-out -11s infinite' } },
  { d: 0.37, s: { left: '14.2%', top: '81%', width: 5.6, height: 5.6, background: '#96B86F', opacity: 0.46, animation: 'nodeFloatB 16s ease-in-out -8s infinite' } },
];

export function FinalCta({
  onGetStarted,
  ctaLabel = 'Sign up for Beta Testing',
}: {
  onGetStarted: () => void;
  /** "Sign up" while open access is on (docs/design/open-access-gate.md). */
  ctaLabel?: string;
}) {
  return (
    <section id="cta" className="ld-cta relative pt-32.5 px-6 pb-30 z-1">
      <DragField section="cta" />

      <div aria-hidden="true" className="absolute inset-0 pointer-events-none overflow-hidden z-0">
        {MOTES.map((m, i) => (
          <span key={i} data-depth={m.d} className="absolute rounded-[99px]" style={{ ...m.s }} />
        ))}
      </div>

      {/* blooms, masked top and bottom so they don't band into the neighbours */}
      <div
        aria-hidden="true"
        className="absolute inset-y-[-14%] inset-x-0 pointer-events-none z-0 overflow-hidden [-webkit-mask-image:linear-gradient(180deg,_transparent_0%,_#000_16%,_#000_84%,_transparent_100%)] [mask-image:linear-gradient(180deg,_transparent_0%,_#000_16%,_#000_84%,_transparent_100%)]"
      >
        <div className="absolute top-[8%] right-[-15%] w-[38vw] h-[38vw] rounded-[50%] [filter:blur(64px)] opacity-38 bg-[rgba(89,119,49,0.22)]" />
        <div className="absolute bottom-[8%] left-[-12%] w-[32vw] h-[32vw] rounded-[50%] [filter:blur(64px)] opacity-28 bg-[rgba(123,158,81,0.2)]" />
      </div>

      <FadeIn style={{ position: 'relative', zIndex: 1, maxWidth: 768, margin: '0 auto', textAlign: 'center' }}>
        <h2 className="m-0 font-display text-[length:clamp(2.8rem,_6vw,_4.6rem)] font-semibold tracking-[-0.02em] leading-[1.05] text-moss-900">
          Ready to <br /> Start <em className="text-brand-forest pr-2">Growing?</em>
        </h2>
        <p className="mt-6 mx-0 mb-0 text-moss-500 text-[17px] font-normal">
          Join students who learn smarter, not harder.
        </p>
        <div className="mt-10 flex flex-col items-center">
          <button
            onClick={onGetStarted}
            className="ld-btn-solid inline-flex items-center gap-2 [background:#445D22] text-accent-fg border-0 rounded-sm py-3.5 px-8 font-sans font-semibold text-[15.5px] whitespace-nowrap cursor-pointer [transition:filter_200ms]"
          >
            {ctaLabel}
          </button>
        </div>
      </FadeIn>
    </section>
  );
}

const FOOTER_LINKS = [
  // About also carries the team; /team was folded into it and the route
  // deleted. See COMPANION_NAV in components/companion/CompanionShell.tsx.
  { label: 'About', href: '/about' },
  { label: 'Wiki', href: '/wiki' },
  { label: 'Gallery', href: '/gallery' },
  { label: 'News', href: '/news' },
  { label: 'FAQ', href: '/faq' },
];

export function SiteFooter() {
  return (
    <footer className="ld-footer border-t border-t-[rgba(25,31,19,0.08)] pt-12 px-8 pb-11 relative z-1">
      <div className="ld-footer-row max-w-287.5 my-0 mx-auto flex items-center justify-between gap-6 flex-wrap">
        <div className="flex items-center gap-2">
          <SaplingWordmark width={64} />
          <span className="text-[13.5px] font-light tracking-[0.02em] text-moss-500">© 2026</span>
        </div>
        <div className="ld-footer-links flex gap-6 flex-wrap">
          {FOOTER_LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="ld-navlink text-moss-500 text-[13.5px] [transition:color_300ms]">{l.label}</Link>
          ))}
          <a href="https://github.com/SaplingLearn/Sapling" target="_blank" rel="noopener noreferrer" className="ld-navlink text-moss-500 text-[13.5px] [transition:color_300ms]">GitHub</a>
          <a href="https://ko-fi.com/saplinglearn" target="_blank" rel="noopener noreferrer" className="ld-navlink text-moss-500 text-[13.5px] [transition:color_300ms]">Support us</a>
          <Link href="/terms" className="ld-navlink text-moss-500 text-[13.5px] [transition:color_300ms]">Terms of Service</Link>
          <Link href="/privacy" className="ld-navlink text-moss-500 text-[13.5px] [transition:color_300ms]">Privacy Policy</Link>
        </div>
      </div>
    </footer>
  );
}
