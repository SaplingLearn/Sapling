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
import { cn } from "@/lib/cn";

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
    <section id="newsletter" className="ld-journal relative pt-30 px-6 pb-25 z-1">
      <DragField section="newsletter" />

      <div className="max-w-287.5 my-0 mx-auto">
        {/* the blurb sits under the heading at every width — beside it, on a
            laptop, it read as a stray caption floating off to the right */}
        <FadeIn className="ld-journal-head" style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 18, marginBottom: 56 }}>
          <div>
            <h2 className="m-0 font-display text-[length:clamp(2.2rem,_4.4vw,_3.6rem)] font-semibold leading-[1.05] tracking-[-0.02em] text-moss-900">
              The story of Sapling, <em className="text-brand-forest">as it grows.</em>
            </h2>
          </div>
          <p className="m-0 max-w-[56ch] text-moss-500 text-[15px] leading-[1.7]">
            Why we built it, where it&rsquo;s headed, and what we&rsquo;re learning about learning,
            written by the four of us, once a month.
          </p>
        </FadeIn>

        <FadeIn className="ld-journal-cards" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 22 }}>
          {POSTS.map((p, i) => (
            <div key={p.title} className="flex [animation:cardFloat_7.5s_ease-in-out_infinite_both]" style={{ animationDelay: POST_FLOAT_DELAYS[i] }}>
              <a
                href={`/news/${p.slug}`}
                className="ld-post flex flex-col w-full [background:#FDFCF9] border border-[rgba(25,31,19,0.09)] rounded-lg pt-3.5 px-3.5 pb-5 text-inherit"
              >
                <div className="relative w-full rounded-[11px] overflow-hidden bg-[#EEF1EC] aspect-[860/574]">
                  <ArticleArt art={p.art} sizes="(max-width: 900px) 100vw, 33vw" />
                </div>
                <div className="flex items-center justify-between mt-4 py-0 px-1.5">
                  <span className="font-sans text-[11.5px] text-brand-forest">{p.tag}</span>
                  <span className="font-sans text-[9.5px] text-moss-500">{p.date}</span>
                </div>
                <h3 className="mt-3 mx-1.5 mb-0 font-display text-2xl font-semibold leading-[1.22] tracking-[-0.01em]">
                  {p.title}
                </h3>
                <p className="mt-3 mx-1.5 mb-4.5 text-moss-500 text-[13.5px] leading-[1.7] flex-1">{p.excerpt}</p>
                <div className="my-0 mx-1.5 pt-3.5 border-t border-t-moss-50">
                  <span className="font-sans text-sm tracking-[0.01em] text-brand-forest">READ · {p.time}</span>
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
          className="hero-surface ld-newsletter"
          style={{
            marginTop: 56,
            border: '1px solid rgba(255,255,255,0.7)', borderRadius: 20,
            padding: 'clamp(28px,4vw,44px)', display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', gap: 32, flexWrap: 'wrap',
          }}
        >
          <div>
            <h3 className="m-0 font-display text-[length:clamp(1.5rem,_2.4vw,_2rem)] font-semibold tracking-[-0.015em] text-moss-900">
              Get the Journal, and a seat in the beta.
            </h3>
            <p className="mt-2.5 mx-0 mb-0 text-moss-700 text-base leading-[1.7] max-w-[52ch]">
              One letter a month while we build. First in the inbox, first on the tree when beta
              invites go out. No spam. We&rsquo;re students too.
            </p>
          </div>

          {subscribed ? (
            <div className="text-center py-0 px-3">
              <div className="font-display text-[24px] font-semibold text-moss-900">
                You&rsquo;re on the <em className="text-brand-forest">tree.</em>
              </div>
              <p className="mt-1.5 mx-0 mb-0 text-base text-[#4b5563] italic">
                See you in the inbox · The Team
              </p>
            </div>
          ) : (
            <div className="ld-newsletter-form flex flex-col gap-2">
              <form onSubmit={(e) => { e.preventDefault(); onSubscribe(); }} className="flex gap-2.5 items-center">
                <input
                  value={email}
                  onChange={(e) => onEmail(e.target.value)}
                  disabled={subscribing}
                  type="email"
                  placeholder="you@school.edu"
                  aria-label="Email address"
                  className="ld-emailinput w-62.5 [background:#fdfcf9] border border-[rgba(25,31,19,0.14)] rounded-sm py-[13px] px-4 font-sans text-base text-moss-900 outline-none"
                />
                <button
                  type="submit"
                  disabled={subscribing}
                  className={cn("ld-btn-solid", "[background:#445D22] text-accent-fg border-0 rounded-sm py-[13px] px-5.5 font-sans font-semibold text-base whitespace-nowrap [transition:filter_200ms,_opacity_200ms]", subscribing ? "cursor-not-allowed" : "cursor-pointer", subscribing ? "opacity-60" : "opacity-100")}
                >
                  {subscribing ? 'Signing you up…' : 'Join the list'}
                </button>
              </form>
              {error && (
                <p role="alert" className="m-0 text-[12.5px] leading-[1.5] text-[#9c4b48] max-w-82.5">
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
