'use client';

/**
 * Gallery.
 *
 * Ported from `Gallery.dc.html`. A filterable grid of `<figure>` tiles, each
 * a 16/10 frame with its route badged over the top-left corner and a caption
 * pairing the screen's title with its group.
 *
 * Tiles stagger in: `animation-delay` steps 50ms per tile and caps at 400ms,
 * so a filter that returns twelve results still settles quickly.
 *
 * The frames are empty. The source fills them with its `image-slot` drop
 * zone ("Drop a screenshot of …"), which is an authoring affordance rather
 * than page content, and the import ships no screenshots. The route badge
 * stays, so each tile still says what it is.
 */

import { useState } from 'react';
import Link from 'next/link';
import { CompanionShell } from '@/components/companion/CompanionShell';
import { ZoomableShot } from '@/components/companion/ZoomableShot';
import { GALLERY_FILTERS, GALLERY_SHOTS } from '@/lib/landing/companionContent';
import { cn } from "@/lib/cn";

export default function GalleryPage() {
  const [filter, setFilter] = useState('all');
  const shots = GALLERY_SHOTS.filter((s) => filter === 'all' || s.cat === filter);

  return (
    <CompanionShell current="/gallery">
      <div>
        <span className="block font-sans text-sm text-text-muted [animation:fadeUp_600ms_ease_both]">
          Inside the product
        </span>
        <h1 className="mt-3.5 mx-0 mb-0 font-display font-medium text-[48px] leading-[1.15] tracking-[-0.015em] [animation:fadeUp_700ms_ease_60ms_both]">
          Gallery
        </h1>
        <p className="mt-6 mx-0 mb-0 font-serif text-lg leading-[1.6] text-ink-600 max-w-[62ch] [animation:fadeUp_700ms_ease_140ms_both]">
          Every screen in Sapling, as it actually looks. One course, one semester, and the same
          graph behind all of it.
        </p>

        <div className="mt-8.5 flex gap-2 flex-wrap [animation:fadeUp_700ms_ease_200ms_both]">
          {GALLERY_FILTERS.map((f) => {
            const on = f.key === filter;
            return (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                type="button"
                aria-pressed={on}
                className={cn("py-2 px-[15px] rounded-[99px] cursor-pointer font-sans text-md font-medium [transition:all_200ms]", on ? "border border-brand-forest" : "border border-[rgba(42,39,31,0.16)]", on ? "bg-brand-forest" : "bg-transparent", on ? "text-ink-0" : "text-text-muted")}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        <div className="mt-6.5 grid grid-cols-[repeat(auto-fill,_minmax(320px,1fr))] gap-5.5">
          {shots.map((s, i) => (
            <figure
              key={s.slot}
              className="m-0 flex flex-col gap-3 [animation:fadeUp_600ms_ease_both]" style={{ animationDelay: `${Math.min(i * 50, 400)}ms` }}
            >
              <ZoomableShot
                src={`/gallery/${s.slot}.png`}
                alt={`The ${s.title} screen in Sapling`}
                title={s.title}
                caption={s.body}
                route={s.route}
              />
              <figcaption className="flex flex-col gap-[5px]">
                <span className="flex items-baseline gap-[9px]">
                  <span className="text-[15px] font-semibold text-ink-800 tracking-[-0.01em]">{s.title}</span>
                  <span className="font-sans text-xs leading-none text-brand-forest-bright">{s.group}</span>
                </span>
                <span className="font-serif text-base leading-[1.6] text-ink-600">{s.body}</span>
              </figcaption>
            </figure>
          ))}
        </div>

        <div className="mt-13 rounded-[18px] bg-ink-0 border border-[rgba(42,39,31,0.10)] p-[clamp(26px,4vw,40px)] flex items-center justify-between gap-6 flex-wrap">
          <div className="max-w-[46ch]">
            <span className="block font-sans text-sm text-brand-forest-bright">
              Rather try it than look at it
            </span>
            <p className="mt-2.5 mx-0 mb-0 font-serif text-[15.5px] leading-[1.65] text-ink-600">
              Every screen here is playable on the home page. Open any tool in the toolkit and it
              runs a real scenario.
            </p>
          </div>
          <Link href="/#gallery" className="cp-cta [background:var(--brand-forest)] text-accent-fg rounded-[8px] py-[13px] px-6 text-[14.5px] font-semibold whitespace-nowrap">
            Open the toolkit
          </Link>
        </div>

      </div>
    </CompanionShell>
  );
}
