'use client';

/**
 * Journal + newsletter.
 *
 * Ported from `Sapling Landing v5.dc.html`. Three editorial cards over an
 * email capture. Two cards carry a photo; the third renders a knowledge-graph
 * illustration inline instead.
 *
 * The source uses its `image-slot` web component (a drag-to-fill authoring
 * affordance) for the photos. Here they come from `ArticleArt` against the
 * assets already in `public/`, keeping the source's 860/574 aspect so the
 * card geometry is unchanged. That component also owns the graph
 * illustration, which used to be a local `GraphThumb` here — the article
 * pages and /news cards need it too (#601).
 *
 * Each card opens its article at /news/[slug]. Everything a card renders
 * comes from that article: the source's comment and like counts were
 * hardcoded against nothing, and went with #601.
 */

import { ArticleArt } from '@/components/journal/ArticleArt';
import { POSTS, POST_FLOAT_DELAYS } from '@/lib/landing/content';
import { DragField } from './DragField';
import { FadeIn } from '@/components/landing/anim';

const MONO: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

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
        <FadeIn style={{ display: 'grid', gridTemplateColumns: '7fr 4fr', gap: 48, alignItems: 'end', marginBottom: 56 }}>
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
        </FadeIn>

        <FadeIn style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 22 }}>
          {POSTS.map((p, i) => (
            <div key={p.title} style={{ display: 'flex', animation: 'cardFloat 7.5s ease-in-out infinite both', animationDelay: POST_FLOAT_DELAYS[i] }}>
              <a
                href={`/news/${p.slug}`}
                className="ld-post"
                style={{ display: 'flex', flexDirection: 'column', width: '100%', background: '#FDFCF9', border: '1px solid rgba(18,32,26,0.09)', borderRadius: 16, padding: '14px 14px 20px', color: 'inherit' }}
              >
                <div style={{ position: 'relative', width: '100%', borderRadius: 11, overflow: 'hidden', background: '#EEF1EC', aspectRatio: '860 / 574' }}>
                  <ArticleArt art={p.art} sizes="(max-width: 900px) 100vw, 33vw" />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 16, padding: '0 6px' }}>
                  <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.26em', color: '#0C5638', textTransform: 'uppercase' }}>{p.tag}</span>
                  <span style={{ ...MONO, fontSize: 9.5, color: '#61726A' }}>{p.date}</span>
                </div>
                <h3 style={{ margin: '12px 6px 0', fontFamily: "'Playfair Display',serif", fontSize: 22, fontWeight: 600, lineHeight: 1.22, letterSpacing: '-0.01em' }}>
                  {p.title}
                </h3>
                <p style={{ margin: '12px 6px 18px', color: '#61726A', fontSize: 13.5, lineHeight: 1.7, flex: 1 }}>{p.excerpt}</p>
                <div style={{ margin: '0 6px', paddingTop: 14, borderTop: '1px solid #EBF1EC' }}>
                  <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.2em', color: '#0C5638' }}>READ · {p.time}</span>
                </div>
              </a>
            </div>
          ))}
        </FadeIn>

        {/*
          The newsletter panel's gradient is the shared hero surface. The
          source inlines the literal, but #288 consolidated that exact value
          behind `--surface-hero` / `.hero-surface` after it had drifted at
          four of its five paste sites — and HeroCard.test.tsx fails the build
          if the literal reappears anywhere under src/. Same pixels, one owner.
        */}
        <FadeIn
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
        </FadeIn>
      </div>
    </section>
  );
}
