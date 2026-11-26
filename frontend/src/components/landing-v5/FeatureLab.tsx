'use client';

/**
 * The feature lab — a gallery card expanded full-bleed.
 *
 * Ported from `Sapling Landing v5.dc.html`. A scrim fades in over 420ms, then
 * a cream panel expands from the clicked card's rect (the FLIP is run by
 * `engine/flip.ts` through `registerPanel`), showing the feature's copy on the
 * left and a live demo on the right, with a rail along the bottom for
 * switching between the eight tools without closing.
 *
 * Escape and a scrim click both close it back down.
 *
 * The demo pane mounts the real interactive demo for the open tool — see
 * lab/, ported from the `FeatureLab` design component the source pulls in
 * through `<dc-import>`.
 */

import { GAL, LAB_KIND } from '@/lib/landing/content';
import { FeatureLabDemo } from './lab';
import { cn } from "@/lib/cn";

export function FeatureLab({
  index,
  panelRef,
  onClose,
  onPick,
}: {
  /** Which gallery card is open, or -1 for closed. */
  index: number;
  panelRef: (el: HTMLDivElement | null) => void;
  onClose: () => void;
  onPick: (i: number) => void;
}) {
  if (index < 0) return null;
  const g = GAL[index];
  if (!g) return null;

  return (
    <div className="fixed inset-0 z-80">
      <div
        onClick={onClose}
        className="absolute inset-0 bg-[rgba(21,29,10,0.62)] [animation:panelFade_420ms_ease_both]"
      />

      <div
        ref={panelRef}
        className="absolute inset-0 bg-bg-panel overflow-hidden flex flex-col [will-change:transform]"
      >
        <div className="ld-lab-grid flex-1 min-h-0 grid grid-cols-[minmax(320px,4fr)_7fr] [animation:panelFade_420ms_ease_160ms_both]">
          <div className="ld-lab-copy py-[clamp(28px,5vh,56px)] px-[clamp(28px,4vw,56px)] flex flex-col border-r border-r-paper-100 overflow-auto">
            <span className="font-sans text-[12.5px] text-brand-forest">
              {g.num} · {g.kicker}
            </span>
            <h3 className="mt-4 mx-0 mb-0 font-display text-[length:clamp(1.9rem,3.2vw,2.9rem)] font-semibold leading-[1.06] tracking-[-0.018em] text-moss-900">
              {g.title}
            </h3>
            <p className="mt-4.5 mx-0 mb-0 text-moss-700 text-[15px] leading-[1.75] max-w-[44ch]">{g.desc}</p>

            <div className="ld-lab-bullets mt-6.5 flex flex-col gap-3.5">
              {g.bullets.map((b, i) => (
                <div key={i} className="flex items-start gap-3">
                  <span className="shrink-0 w-5.5 h-5.5 rounded-[99px] bg-leaf-50 flex items-center justify-center mt-px">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#445D22" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  </span>
                  <span className="text-base leading-[1.65] text-moss-700">{b.t}</span>
                </div>
              ))}
            </div>

          </div>

          <div className="ld-lab-demo [background:#F2F4F0] py-[clamp(20px,3.4vh,40px)] px-[clamp(20px,2.6vw,44px)] flex items-center justify-center min-w-0">
            <div className="ld-lab-demo-frame relative w-full h-full max-h-165 rounded-[20px] overflow-hidden border border-[#E2E6DF] [background:#FDFCF9] [box-shadow:0_30px_70px_-30px_rgba(25,31,19,0.32)]">
              <div className="absolute inset-0">
                <FeatureLabDemo kind={LAB_KIND[g.kind]} />
              </div>
            </div>
          </div>
        </div>

        <div
          className="ld-lab-rail flex-[0_0_auto] border-t border-t-paper-100 [background:#F6F8F4] py-3 px-[clamp(20px,3vw,40px)] flex gap-2.5 overflow-x-auto [animation:panelFade_420ms_ease_260ms_both]"
        >
          {GAL.map((r, i) => {
            const on = i === index;
            return (
              <button
                key={r.kind}
                data-rail={i}
                type="button"
                onClick={() => onPick(i)}
                className={cn(cn("ld-rail", "flex-[0_0_auto] flex flex-col gap-0.5 text-left py-[9px] px-[15px] rounded-[11px] cursor-pointer font-sans [transition:all_220ms_cubic-bezier(0.22,1,0.36,1)]", on ? "[background:#445D22]" : "[background:#FDFCF9]", on ? "text-bg-panel" : "text-moss-700"), on ? "border border-brand-forest" : "border border-paper-200")}
              >
                <span className={cn("font-sans text-2xs tracking-[0.01em]", on ? "text-[rgba(253,252,249,0.7)]" : "text-moss-300")}>
                  {r.num}
                </span>
                <span className="text-[12.5px] font-semibold whitespace-nowrap">{r.kicker}</span>
              </button>
            );
          })}
        </div>

        <button
          onClick={onClose}
          aria-label="Close"
          className="ld-labclose absolute top-5 right-5 w-10.5 h-10.5 rounded-[99px] border border-[rgba(25,31,19,0.12)] [background:#FDFCF9] text-moss-900 cursor-pointer flex items-center justify-center [transition:all_250ms] z-3 [animation:panelFade_420ms_ease_240ms_both]"
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
