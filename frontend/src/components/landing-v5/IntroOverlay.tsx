'use client';

import { SaplingWordmark } from '@/components/SaplingWordmark';
import { cn } from "@/lib/cn";

export function IntroOverlay({
  heroMounted,
  introGone,
  loadPct,
}: {
  heroMounted: boolean;
  introGone: boolean;
  loadPct: number;
}) {
  return (
    <div
      aria-hidden="true"
      className={cn("fixed inset-0 z-60 items-center justify-center bg-[#f2f4f0] [background-image:radial-gradient(ellipse_100%_70%_at_50%_30%,_rgba(255,255,255,0.9)_0%,_transparent_62%)] [transition:opacity_700ms_cubic-bezier(0.22,1,0.36,1)]", introGone ? "hidden" : "flex", heroMounted ? "opacity-0" : "opacity-100", heroMounted ? "pointer-events-none" : "pointer-events-auto")}
    >
      <div className="flex flex-col items-center">
        <img src="/design/sapling/originals/logo-symbol.svg" alt="" aria-hidden="true" width={46} height={65} />
        <div
          className="mt-[13px] font-serif font-bold text-[33px] tracking-[-0.025em] text-brand-forest leading-none whitespace-nowrap [animation:s1Word_2.4s_cubic-bezier(0.22,1,0.36,1)_both]"
        >
          <SaplingWordmark width={146} />
        </div>
        <div
          className="mt-3 w-36.5 h-px [background:linear-gradient(90deg,_rgba(68,93,34,0.55),_rgba(123,158,81,0.25))] [transform-origin:left_center] [animation:s1Rule_2.4s_cubic-bezier(0.22,1,0.36,1)_both]"
        />
        <div
          className="mt-3.5 flex items-baseline gap-[9px] font-sans text-sm tracking-[0.01em] text-moss-300 [animation:s1Word_2.4s_cubic-bezier(0.22,1,0.36,1)_both]"
        >
          <span>Loading</span>
          {/* zero-padded to three digits so the lockup never reflows as it counts */}
          <span className="text-moss-500">{String(Math.min(100, loadPct)).padStart(3, '0')}</span>
        </div>
      </div>
    </div>
  );
}
