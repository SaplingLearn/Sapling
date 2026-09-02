'use client';

/**
 * Journal + newsletter.
 *
 * Ported from `Sapling Landing v5.dc.html`. Three editorial cards over an
 * email capture. Two cards carry a photo; the third renders a knowledge-graph
 * illustration inline instead.
 *
 * The source uses its `image-slot` web component (a drag-to-fill authoring
 * affordance) for the photos. Here they are `next/image` against the assets
 * already in `public/`, keeping the source's 860/574 aspect so the card
 * geometry is unchanged.
 */

import Image from 'next/image';
import { POSTS, POST_META } from '@/lib/landing/content';
import { DragField } from './DragField';

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

/** The inline graph illustration used by the third card. */
function GraphThumb() {
  return (
    <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(ellipse 80% 70% at 45% 45%, #123526 0%, #0B2418 60%, #071A11 100%)' }}>
      <svg width="100%" height="100%" viewBox="0 0 243 158" preserveAspectRatio="xMidYMid slice">
        <line x1="118" y1="76" x2="62" y2="44" stroke="rgba(143,217,168,0.28)" />
        <line x1="118" y1="76" x2="54" y2="108" stroke="rgba(143,217,168,0.28)" />
        <line x1="118" y1="76" x2="182" y2="50" stroke="rgba(143,217,168,0.28)" />
        <line x1="118" y1="76" x2="176" y2="116" stroke="rgba(143,217,168,0.18)" />
        <line x1="62" y1="44" x2="182" y2="50" stroke="rgba(143,217,168,0.1)" />
        <line x1="54" y1="108" x2="176" y2="116" stroke="rgba(143,217,168,0.1)" />
        {/* each node's ring arc is its mastery, drawn from 12 o'clock */}
        <circle cx="118" cy="76" r="15" fill="none" stroke="rgba(230,242,232,0.14)" strokeWidth="2.6" />
        <circle cx="118" cy="76" r="15" fill="none" stroke="#0E9E5A" strokeWidth="2.6" strokeLinecap="round" strokeDasharray="58 94" transform="rotate(-90 118 76)" />
        <circle cx="118" cy="76" r="9" fill="#0E9E5A" />
        <text x="118" y="79" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="7" fill="#061710">112</text>
        <circle cx="62" cy="44" r="10" fill="none" stroke="rgba(230,242,232,0.14)" strokeWidth="2.2" />
        <circle cx="62" cy="44" r="10" fill="none" stroke="#4FA574" strokeWidth="2.2" strokeLinecap="round" strokeDasharray="38 25" transform="rotate(-90 62 44)" />
        <circle cx="62" cy="44" r="5.5" fill="#4FA574" />
        <text x="62" y="26" textAnchor="middle" fontFamily="DM Sans" fontSize="7.5" fill="#8FA89A">Trees</text>
        <circle cx="54" cy="108" r="10" fill="none" stroke="rgba(230,242,232,0.14)" strokeWidth="2.2" />
        <circle cx="54" cy="108" r="10" fill="none" stroke="#0E9E5A" strokeWidth="2.2" strokeLinecap="round" strokeDasharray="55 8" transform="rotate(-90 54 108)" />
        <circle cx="54" cy="108" r="5.5" fill="#0E9E5A" />
        <text x="54" y="130" textAnchor="middle" fontFamily="DM Sans" fontSize="7.5" fill="#8FA89A">Sorting</text>
        <circle cx="182" cy="50" r="10" fill="none" stroke="rgba(230,242,232,0.14)" strokeWidth="2.2" />
        <circle cx="182" cy="50" r="10" fill="none" stroke="#E27A63" strokeWidth="2.2" strokeLinecap="round" strokeDasharray="16 47" transform="rotate(-90 182 50)" />
        <circle cx="182" cy="50" r="5" fill="#E27A63" />
        <text x="182" y="32" textAnchor="middle" fontFamily="DM Sans" fontSize="7.5" fill="#8FA89A">Recursion</text>
        <circle cx="176" cy="116" r="9" fill="none" stroke="rgba(230,242,232,0.12)" strokeWidth="2" />
        <circle cx="176" cy="116" r="4.5" fill="#9a9a9a" />
        <text x="176" y="137" textAnchor="middle" fontFamily="DM Sans" fontSize="7.5" fill="#6C8377">DP</text>
      </svg>
      <span style={{ position: 'absolute', left: 11, top: 10, ...MONO, fontSize: 7.5, letterSpacing: '0.2em', color: '#8FD9A8' }}>
        CS 112 · KNOWLEDGE GRAPH
      </span>
    </div>
  );
}

export function Journal({
  email,
  subscribed,
  subscribing,
  error,
  onEmail,
  onSubscribe,
}: {
  email: string;
  subscribed: boolean;
  subscribing: boolean;
  error: string | null;
  onEmail: (v: string) => void;
  onSubscribe: () => void;
}) {
  return (
    <section id="newsletter" style={{ position: 'relative', padding: '120px 24px 100px', zIndex: 1 }}>
      <DragField section="newsletter" />

      <div style={{ maxWidth: 1150, margin: '0 auto' }}>
        <div data-reveal="1" style={{ display: 'grid', gridTemplateColumns: '7fr 4fr', gap: 48, alignItems: 'end', marginBottom: 56 }}>
          <div>
            <span style={{ ...MONO, fontSize: 11, letterSpacing: '0.32em', color: '#0C5638', textTransform: 'uppercase', fontWeight: 500 }}>
              The Sapling Journal
            </span>
            <h2 style={{ margin: '20px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 'clamp(2.2rem, 4.4vw, 3.6rem)', fontWeight: 600, lineHeight: 1.05, letterSpacing: '-0.02em', color: '#12201A' }}>
              The story of Sapling, <em style={{ color: '#0C5638' }}>as it grows.</em>
            </h2>
          </div>
          <p style={{ margin: '0 0 6px', color: '#61726A', fontSize: 15, lineHeight: 1.7 }}>
            Why we built it, where it&rsquo;s headed, and what we&rsquo;re learning about learning,
            written by the four of us, once a month.
          </p>
        </div>

        <div data-reveal="1" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 22 }}>
          {POSTS.map((p, i) => {
            const meta = POST_META[i] ?? POST_META[0];
            return (
              <div data-anim key={p.title} style={{ display: 'flex', animation: 'cardFloat 7.5s ease-in-out infinite both', animationDelay: meta.floatDelay }}>
                <a
                  href="#newsletter"
                  className="ld-post"
                  style={{ display: 'flex', flexDirection: 'column', width: '100%', background: '#FDFCF9', border: '1px solid rgba(18,32,26,0.09)', borderRadius: 16, padding: '14px 14px 20px', color: 'inherit' }}
                >
                  <div style={{ position: 'relative', width: '100%', borderRadius: 11, overflow: 'hidden', background: '#EEF1EC', aspectRatio: '860 / 574' }}>
                    {meta.isGraph ? (
                      <GraphThumb />
                    ) : (
                      <Image
                        src={meta.src}
                        alt=""
                        fill
                        sizes="(max-width: 900px) 100vw, 33vw"
                        style={{ objectFit: 'cover' }}
                      />
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 16, padding: '0 6px' }}>
                    <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.26em', color: '#0C5638', textTransform: 'uppercase' }}>{p.tag}</span>
                    <span style={{ ...MONO, fontSize: 9.5, color: '#61726A' }}>{p.date}</span>
                  </div>
                  <h3 style={{ margin: '12px 6px 0', fontFamily: "'Playfair Display',serif", fontSize: 22, fontWeight: 600, lineHeight: 1.22, letterSpacing: '-0.01em' }}>
                    {p.title}
                  </h3>
                  <p style={{ margin: '12px 6px 18px', color: '#61726A', fontSize: 13.5, lineHeight: 1.7, flex: 1 }}>{p.excerpt}</p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 11, margin: '0 6px', paddingTop: 14, borderTop: '1px solid #EBF1EC' }}>
                    <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.2em', color: '#0C5638' }}>READ · {p.time}</span>
                    <div aria-hidden="true" style={{ display: 'flex', alignItems: 'center', gap: 16, color: '#8B9891' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5 }}>
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                        </svg>
                        {meta.comments}
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5 }}>
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21.2l7.7-7.7 1.1-1.1a5.5 5.5 0 0 0 0-7.8z" />
                        </svg>
                        {meta.likes}
                      </span>
                    </div>
                  </div>
                </a>
              </div>
            );
          })}
        </div>

        {/*
          The newsletter panel's gradient is the shared hero surface. The
          source inlines the literal, but #288 consolidated that exact value
          behind `--surface-hero` / `.hero-surface` after it had drifted at
          four of its five paste sites — and HeroCard.test.tsx fails the build
          if the literal reappears anywhere under src/. Same pixels, one owner.
        */}
        <div
          data-reveal="1"
          className="hero-surface"
          style={{
            marginTop: 56,
            border: '1px solid rgba(255,255,255,0.7)', borderRadius: 20,
            padding: 'clamp(28px,4vw,44px)', display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', gap: 32, flexWrap: 'wrap',
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontFamily: "'Playfair Display',serif", fontSize: 'clamp(1.5rem, 2.4vw, 2rem)', fontWeight: 600, letterSpacing: '-0.015em', color: '#12201A' }}>
              Get the Journal, and a seat in the beta.
            </h3>
            <p style={{ margin: '10px 0 0', color: '#33443B', fontSize: 14, lineHeight: 1.7, maxWidth: '52ch' }}>
              One letter a month while we build. First in the inbox, first on the tree when beta
              invites go out. No spam. We&rsquo;re students too.
            </p>
          </div>

          {subscribed ? (
            <div style={{ textAlign: 'center', padding: '0 12px' }}>
              <div style={{ fontFamily: "'Playfair Display',serif", fontSize: 24, fontWeight: 600, color: '#12201A' }}>
                You&rsquo;re on the <em style={{ color: '#0C5638' }}>tree.</em>
              </div>
              <p style={{ margin: '6px 0 0', fontSize: 14, color: '#4b5563', fontStyle: 'italic' }}>
                See you in the inbox · The Team
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <form onSubmit={(e) => { e.preventDefault(); onSubscribe(); }} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <input
                  value={email}
                  onChange={(e) => onEmail(e.target.value)}
                  disabled={subscribing}
                  type="email"
                  placeholder="you@school.edu"
                  aria-label="Email address"
                  className="ld-emailinput"
                  style={{ width: 250, background: '#fdfcf9', border: '1px solid rgba(18,32,26,0.14)', borderRadius: 6, padding: '13px 16px', fontFamily: "'DM Sans',sans-serif", fontSize: 14, color: '#12201A', outline: 'none' }}
                />
                <button
                  type="submit"
                  disabled={subscribing}
                  className="ld-btn-solid"
                  style={{ background: '#0C5638', color: '#fff', border: 'none', borderRadius: 6, padding: '13px 22px', fontFamily: "'DM Sans',sans-serif", fontWeight: 600, fontSize: 14, cursor: subscribing ? 'not-allowed' : 'pointer', opacity: subscribing ? 0.6 : 1, whiteSpace: 'nowrap', transition: 'filter 200ms, opacity 200ms' }}
                >
                  {subscribing ? 'Signing you up…' : 'Join the list'}
                </button>
              </form>
              {error && (
                <p role="alert" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5, color: '#9c4b48', maxWidth: 330 }}>
                  {error}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
