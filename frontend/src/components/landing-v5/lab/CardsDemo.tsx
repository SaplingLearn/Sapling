'use client';

/**
 * Feature lab · spaced repetition.
 *
 * Ported from the `isCards` branch of `FeatureLab.dc.html`. Click the card
 * (or press space) to flip it, then rate 1/2/3 and the interval follows:
 * 10 minutes, 1 day, 4 days.
 *
 * The keyboard shortcuts are part of the demo, not an accessibility
 * afterthought — the real review surface is driven the same way, and the hint
 * line says so.
 */

import { useCallback, useEffect, useState } from 'react';
import { DECK, RATE_DUE, RATE_LABEL, RATE_TONE } from './labData';
import { cn } from "@/lib/cn";

type RateKey = '1' | '2' | '3';
const RATES: RateKey[] = ['1', '2', '3'];

export function CardsDemo() {
  const [idx, setIdx] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [log, setLog] = useState<{ q: string; key: RateKey }[]>([]);

  const done = idx >= DECK.length;
  const card = DECK[Math.min(idx, DECK.length - 1)];

  // Plain reads from the render closure, with the key listener re-bound on
  // the values it depends on. Deciding inside a state updater (and firing a
  // timeout from one) double-runs under StrictMode and drops the advance.
  const flip = useCallback(() => {
    if (idx < DECK.length) setFlipped((f) => !f);
  }, [idx]);

  const rate = useCallback((key: RateKey) => {
    if (idx >= DECK.length || !flipped) return;
    setLog((l) => [...l, { q: DECK[idx].q, key }]);
    setFlipped(false);
    // the card turns back before the next one arrives, so it reads as a deal
    const t = setTimeout(() => setIdx((i) => i + 1), 300);
    return () => clearTimeout(t);
  }, [idx, flipped]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === ' ') { e.preventDefault(); flip(); }
      else if (RATES.includes(e.key as RateKey)) rate(e.key as RateKey);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [flip, rate]);

  return (
    <div className="pt-4.5 px-6.5 pb-5 flex flex-col gap-3 h-full box-border">
      <div className="flex-[0_0_auto] flex items-center justify-between gap-4">
        <div className="flex items-center gap-[9px]">
          <span className="w-2 h-2 rounded-[99px] bg-state-struggle" />
          <span className="text-base font-semibold text-moss-900">Eigenvalues</span>
          <span className="py-[3px] px-2 rounded-sm bg-moss-25 border border-moss-75 font-sans text-xs tracking-[0.01em] text-moss-500">MA 242</span>
        </div>
        <div className="flex items-center gap-3.5">
          <span className="font-sans text-[11.5px] tracking-[0.01em] text-moss-400">
            DUE TODAY · {DECK.length - Math.min(idx, DECK.length)} LEFT
          </span>
          <span className="text-[12.5px] text-moss-500">
            Card {done ? DECK.length : idx + 1} of {DECK.length}
          </span>
        </div>
      </div>

      <span className="flex-[0_0_auto] h-[5px] rounded-[99px] bg-moss-75 overflow-hidden">
        <span className="block h-full rounded-[99px] bg-leaf-500 [transition:width_400ms_cubic-bezier(0.22,1,0.36,1)]" style={{ width: `${Math.round((Math.min(idx, DECK.length) / DECK.length) * 100)}%` }} />
      </span>

      {done ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3.5 [animation:labIn_320ms_ease_both]">
          <span className="font-serif text-4xl font-semibold">Deck complete</span>
          <div className="flex flex-col gap-2 w-[min(340px,100%)]">
            {log.map((l, i) => (
              <div key={i} className="flex items-center justify-between py-[9px] px-[13px] rounded-[9px] bg-moss-25 border border-moss-75">
                <span className="text-[12.5px] text-moss-700 max-w-3/5 overflow-hidden text-ellipsis whitespace-nowrap">{l.q}</span>
                <span className="font-sans text-[10.5px]" style={{ color: RATE_TONE[l.key] }}>
                  {RATE_LABEL[l.key]} · {RATE_DUE[l.key]}
                </span>
              </div>
            ))}
          </div>
          <button
            onClick={() => { setIdx(0); setFlipped(false); setLog([]); }}
            type="button"
            className="mt-1 py-2.5 px-5.5 rounded-md border-0 bg-brand-forest text-bg-panel font-sans text-md font-semibold cursor-pointer"
          >
            Study again
          </button>
        </div>
      ) : (
        <>
          <div onClick={flip} className="relative flex-[1_1_auto] min-h-50 cursor-pointer">
            <div className="absolute inset-0 flex items-center justify-center [perspective:1600px]">
              <div className={cn("relative w-full max-w-150 aspect-video max-h-full [transform-style:preserve-3d] [transition:transform_560ms_cubic-bezier(0.4,0,0.2,1)]", flipped ? "[transform:rotateY(180deg)]" : "[transform:rotateY(0deg)]")}>
                <div className="absolute inset-0 [backface-visibility:hidden] rounded-[18px] bg-bg-panel border border-paper-300 [box-shadow:0_18px_40px_-18px_rgba(25,31,19,0.28)] py-7.5 px-8.5 flex flex-col items-center justify-center text-center gap-3.5">
                  <span className="font-sans text-xs tracking-[0.01em] text-moss-300">Front</span>
                  <span className="font-serif text-[length:clamp(20px,2.3vw,27px)] font-semibold leading-[1.3] text-moss-900">{card.q}</span>
                  <span className="absolute bottom-4 left-0 right-0 text-[11.5px] text-[#B8BDB4]">click to reveal</span>
                </div>
                <div className="absolute inset-0 [backface-visibility:hidden] [transform:rotateY(180deg)] rounded-[18px] bg-brand-forest border border-brand-forest [box-shadow:0_18px_40px_-18px_rgba(68,93,34,0.5)] py-7.5 px-8.5 flex flex-col items-center justify-center text-center gap-3.5">
                  <span className="font-sans text-xs tracking-[0.01em] text-[#B1D28B]">Back</span>
                  <span className="font-serif text-[length:clamp(18px,2.1vw,24px)] font-medium leading-[1.4] text-moss-25">{card.a}</span>
                  <span className="absolute bottom-4 left-0 right-0 font-sans text-xs tracking-[0.01em] text-[rgba(234,241,228,0.5)]">How did that go?</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex-[0_0_auto] flex flex-col gap-2 items-center">
            <div className={cn("flex gap-2.5 w-full max-w-140 [transition:opacity_250ms]", flipped ? "opacity-100" : "opacity-35", flipped ? "pointer-events-auto" : "pointer-events-none")}>
              {RATES.map((k) => (
                <button
                  key={k}
                  onClick={() => rate(k)}
                  type="button"
                  className="ld-labrate flex-1 flex flex-col items-center gap-0.5 py-[11px] px-0 rounded-[11px] font-sans cursor-pointer [transition:all_180ms]"
                  style={{ border: `1px solid ${RATE_TONE[k]}66`, background: `${RATE_TONE[k]}12` }}
                >
                  <span className="text-[13.5px] font-semibold" style={{ color: RATE_TONE[k] }}>
                    {RATE_LABEL[k]} <b className="font-sans text-2xs text-moss-300 font-normal">{k}</b>
                  </span>
                  <span className="font-sans text-2xs" style={{ color: `${RATE_TONE[k]}cc` }}>next in {RATE_DUE[k]}</span>
                </button>
              ))}
            </div>
            <span className="text-[11.5px] text-moss-300">
              {flipped ? 'Rate it: 1 Forgot, 2 Hard, 3 Easy' : 'Click the card or press space to reveal'}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
