'use client';

/**
 * The final CTA, the footer, and the fixed section nav.
 *
 * Ported from `Sapling Landing v5.dc.html`.
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

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

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
    <footer style={{ borderTop: '1px solid rgba(18,32,26,0.08)', padding: '48px 32px 40px', position: 'relative', zIndex: 1 }}>
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
          <a href="https://ko-fi.com/saplinglearn" target="_blank" rel="noopener noreferrer" className="ld-navlink" style={FOOTER_LINK}>Ko-fi</a>
          <Link href="/terms" className="ld-navlink" style={FOOTER_LINK}>Terms of Service</Link>
          <Link href="/privacy" className="ld-navlink" style={FOOTER_LINK}>Privacy Policy</Link>
        </div>
      </div>
      <div style={{ maxWidth: 1150, margin: '32px auto 0', paddingTop: 24, borderTop: '1px solid rgba(18,32,26,0.06)', textAlign: 'center' }}>
        <p style={{ margin: 0, fontSize: 12, color: '#61726A', opacity: 0.75, fontWeight: 300, letterSpacing: '0.02em' }}>
          © 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez. All Rights Reserved.
        </p>
      </div>
    </footer>
  );
}

/** The eight jump targets, in page order. `id` is empty for the top of page. */
const SECTIONS = [
  { id: '', label: 'Top', nav: 'hero-top' },
  { id: 'act-graph', label: 'The graph', nav: 'act-graph' },
  { id: 'act-ingest', label: 'Ingest', nav: 'act-ingest' },
  { id: 'act-tutor', label: 'Tutor', nav: 'act-tutor' },
  { id: 'gallery', label: 'Features', nav: 'gallery' },
  { id: 'faq', label: 'FAQ', nav: 'faq' },
  { id: 'newsletter', label: 'Journal', nav: 'newsletter' },
  { id: 'cta', label: 'Get started', nav: 'cta' },
];

/**
 * Reading-progress hairline plus the bottom-centre section jump.
 *
 * The engine writes the progress width, the active dot and the pill's label
 * through `[data-stem]`, `[data-jumpdot]`, `[data-jumptick]` and
 * `[data-jumplabel]`; React only owns whether the menu is open.
 */
export function SectionNav({
  open,
  onToggle,
  onJump,
  onTop,
}: {
  open: boolean;
  onToggle: () => void;
  onJump: (id: string) => void;
  onTop: () => void;
}) {
  return (
    <>
      <div aria-hidden="true" style={{ position: 'fixed', left: 0, right: 0, top: 0, height: 2, zIndex: 58, pointerEvents: 'none' }}>
        <span data-stem="1" style={{ display: 'block', height: '100%', width: '0%', background: 'linear-gradient(90deg,#0E9E5A,#0C5638)', boxShadow: '0 0 10px rgba(14,158,90,0.45)' }} />
      </div>

      <nav
        className="sapling-nav"
        aria-label="Page sections"
        style={{ position: 'fixed', left: '50%', bottom: 22, transform: 'translateX(-50%)', zIndex: 56, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}
      >
        <div
          role="menu"
          style={{
            minWidth: 190, padding: 6, borderRadius: 14,
            background: 'rgba(253,252,249,0.82)', backdropFilter: 'blur(16px)',
            border: '1px solid rgba(18,32,26,0.1)',
            boxShadow: '0 16px 38px -18px rgba(18,32,26,0.4)',
            display: open ? 'flex' : 'none', flexDirection: 'column', gap: 1,
            transformOrigin: 'bottom center',
            opacity: open ? 1 : 0,
            transform: open ? 'scale(1)' : 'scale(0.96)',
            transition: 'opacity 200ms ease, transform 240ms cubic-bezier(0.22,1,0.36,1)',
          }}
        >
          {SECTIONS.map((sec, i) => (
            <button
              key={sec.nav}
              data-secnav={sec.nav}
              data-jump={i}
              type="button"
              onClick={() => (sec.id ? onJump(sec.id) : onTop())}
              className="ld-jumpitem"
              style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left', padding: '9px 12px', borderRadius: 9, border: 'none', background: 'none', cursor: 'pointer', fontFamily: "'DM Sans',sans-serif", fontSize: 13, color: '#33443B' }}
            >
              <span data-jumpdot="1" style={{ width: 5, height: 5, borderRadius: 99, flex: '0 0 auto', background: 'rgba(18,32,26,0.18)', transition: 'background 260ms, box-shadow 260ms' }} />
              {sec.label}
            </button>
          ))}
        </div>

        <button
          data-jumppill="1"
          onClick={onToggle}
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          title="Jump to a section"
          className="ld-jumppill"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 99, background: 'transparent', border: 'none', boxShadow: 'none', cursor: 'pointer', transition: 'opacity 260ms' }}
        >
          <span data-jumplabel="1" style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.2em', textTransform: 'uppercase', color: '#61726A', whiteSpace: 'nowrap', textShadow: '0 0 8px rgba(246,248,244,0.9)', transition: 'color 300ms, text-shadow 300ms' }}>
            Top
          </span>
          <span aria-hidden="true" style={{ display: 'flex', alignItems: 'center', gap: 3, paddingRight: 4 }}>
            {SECTIONS.map((_, i) => (
              <span key={i} data-jumptick={i} style={{ width: 4, height: 4, borderRadius: 99, background: 'rgba(18,32,26,0.18)', transition: 'background 300ms, transform 300ms' }} />
            ))}
          </span>
        </button>
      </nav>
    </>
  );
}
