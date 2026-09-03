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

import Image from 'next/image';
import Link from 'next/link';
import { DragField } from './DragField';
import { FadeIn } from '@/components/landing/anim';

const MOTES: { d: number; s: React.CSSProperties }[] = [
  { d: 0.30, s: { left: '6.5%', top: '22%', width: 7.4, height: 7.4, background: '#4FA574', opacity: 0.44, animation: 'nodeFloatA 15s ease-in-out -6s infinite' } },
  { d: 0.44, s: { right: '8.2%', top: '31%', width: 6.2, height: 6.2, background: '#8FD9A8', opacity: 0.5, animation: 'nodeFloatB 13s ease-in-out -3s infinite' } },
  { d: 0.22, s: { right: '13.6%', top: '74%', width: 9.6, height: 9.6, background: '#0E9E5A', opacity: 0.4, boxShadow: '0 0 22px #0E9E5A66', animation: 'nodeFloatA 18s ease-in-out -11s infinite' } },
  { d: 0.37, s: { left: '14.2%', top: '81%', width: 5.6, height: 5.6, background: '#6FBF8F', opacity: 0.46, animation: 'nodeFloatB 16s ease-in-out -8s infinite' } },
];

export function FinalCta({ onGetStarted }: { onGetStarted: () => void }) {
  return (
    <section id="cta" style={{ position: 'relative', padding: '130px 24px 120px', zIndex: 1 }}>
      <DragField section="cta" />

      <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 0 }}>
        {MOTES.map((m, i) => (
          <span key={i} data-depth={m.d} style={{ position: 'absolute', borderRadius: 99, ...m.s }} />
        ))}
      </div>

      {/* blooms, masked top and bottom so they don't band into the neighbours */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute', inset: '-14% 0', pointerEvents: 'none', zIndex: 0, overflow: 'hidden',
          WebkitMaskImage: 'linear-gradient(180deg, transparent 0%, #000 16%, #000 84%, transparent 100%)',
          maskImage: 'linear-gradient(180deg, transparent 0%, #000 16%, #000 84%, transparent 100%)',
        }}
      >
        <div style={{ position: 'absolute', top: '8%', right: '-15%', width: '38vw', height: '38vw', borderRadius: '50%', filter: 'blur(64px)', opacity: 0.38, background: 'rgba(46,125,82,0.22)' }} />
        <div style={{ position: 'absolute', bottom: '8%', left: '-12%', width: '32vw', height: '32vw', borderRadius: '50%', filter: 'blur(64px)', opacity: 0.28, background: 'rgba(43,140,150,0.2)' }} />
      </div>

      <FadeIn style={{ position: 'relative', zIndex: 1, maxWidth: 768, margin: '0 auto', textAlign: 'center' }}>
        <h2 style={{ margin: 0, fontFamily: "'Playfair Display',serif", fontSize: 'clamp(2.8rem, 6vw, 4.6rem)', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.05, color: '#12201A' }}>
          Ready to <br /> Start <em style={{ color: '#0C5638', paddingRight: 8 }}>Growing?</em>
        </h2>
        <p style={{ margin: '24px 0 0', color: '#61726A', fontSize: 17, fontWeight: 400 }}>
          Join students who learn smarter, not harder.
        </p>
        <div style={{ marginTop: 40, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <button
            onClick={onGetStarted}
            className="ld-btn-solid"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: '#0C5638', color: '#fff', border: 'none', borderRadius: 6, padding: '14px 32px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600, fontSize: 15.5, whiteSpace: 'nowrap', cursor: 'pointer', transition: 'filter 200ms' }}
          >
            Sign up for Beta Testing
          </button>
        </div>
      </FadeIn>
    </section>
  );
}

const FOOTER_LINKS = [
  { label: 'About', href: '/about' },
  { label: 'Team', href: '/team' },
  { label: 'Wiki', href: '/wiki' },
  { label: 'Gallery', href: '/gallery' },
  { label: 'News', href: '/news' },
  { label: 'FAQ', href: '/faq' },
];

const FOOTER_LINK: React.CSSProperties = { color: '#61726A', fontSize: 13.5, transition: 'color 300ms' };

export function SiteFooter() {
  return (
    <footer style={{ borderTop: '1px solid rgba(18,32,26,0.08)', padding: '48px 32px 44px', position: 'relative', zIndex: 1 }}>
      <div style={{ maxWidth: 1150, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Image src="/sapling-icon.svg" alt="Sapling" width={20} height={20} />
          <span style={{ fontSize: 13.5, fontWeight: 300, letterSpacing: '0.02em', color: '#61726A' }}>Sapling · © 2026</span>
        </div>
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          {FOOTER_LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="ld-navlink" style={FOOTER_LINK}>{l.label}</Link>
          ))}
          <a href="https://github.com/SaplingLearn/Sapling" target="_blank" rel="noopener noreferrer" className="ld-navlink" style={FOOTER_LINK}>GitHub</a>
          <a href="https://ko-fi.com/saplinglearn" target="_blank" rel="noopener noreferrer" className="ld-navlink" style={FOOTER_LINK}>Support us</a>
          <Link href="/terms" className="ld-navlink" style={FOOTER_LINK}>Terms of Service</Link>
          <Link href="/privacy" className="ld-navlink" style={FOOTER_LINK}>Privacy Policy</Link>
        </div>
      </div>
    </footer>
  );
}
