'use client';

import { cn } from "@/lib/cn";

/**
 * The browser-chrome frame every feature-lab demo sits in.
 *
 * Ported from `FeatureLab.dc.html`: three dots, the fake route, and an
 * INTERACTIVE badge, over a scrolling body. The badge is not decoration —
 * these demos really do respond, which is what the panel's
 * "TRY IT · THIS ONE ACTUALLY WORKS" line is promising.
 */

export const LABEL: React.CSSProperties = { fontFamily: "var(--font-suse), 'SUSE', system-ui, sans-serif" };

/** Lab-local tier swatches; see labData.ts for why they differ from the graph's. */
export const LAB_TIER = {
  mastered: '#5a7834', learning: '#c89b5e', struggling: '#b25855', unexplored: '#C7CBC2',
} as const;

export function LabShell({ route, children }: { route: string; children: React.ReactNode }) {
  return (
    <div className="w-full h-full overflow-hidden font-sans text-moss-900 bg-bg-panel flex flex-col">
      <div className="flex-[0_0_auto] h-9.5 border-b border-b-paper-100 bg-moss-25 flex items-center gap-2.5 py-0 px-3.5">
        <span className="flex gap-[5px]">
          {[0, 1, 2].map((i) => (
            <span key={i} className="w-2 h-2 rounded-[99px] bg-paper-300" />
          ))}
        </span>
        <span className="font-sans text-[11.5px] tracking-[0.01em] text-moss-400">{route}</span>
        <span className="ml-auto font-sans text-xs tracking-[0.01em] text-brand-forest bg-leaf-50 border border-moss-100 rounded-[99px] py-[3px] px-[9px]">
          Interactive
        </span>
      </div>
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </div>
  );
}

/**
 * Shared button styles the demos reuse.
 *
 * The primary sits on the brand green at rest. It used to be near-black ink
 * (#191F13) and turn green only on hover, which is the reverse of every other
 * primary in the lab — the flashcard "Flip", the quiz's own "Retake", the room
 * "Send" are all #445D22 from the start. Assessment's "Submit answer" is the
 * one button that runs through this shared style, so it was the one reading as
 * a different, darker control than the ones beside it.
 */
export const PRIMARY_BTN: React.CSSProperties = {
  padding: '11px 24px', borderRadius: 10, border: 'none', background: '#445D22',
  color: '#FDFCF9', fontFamily: "var(--font-suse), 'SUSE', system-ui, sans-serif", fontSize: 13.5,
  fontWeight: 600, cursor: 'pointer', transition: 'background 200ms',
};

export const GHOST_BTN: React.CSSProperties = {
  padding: '10px 20px', borderRadius: 10, border: '1px solid #E0E6DA',
  background: '#FDFCF9', fontFamily: "var(--font-suse), 'SUSE', system-ui, sans-serif", fontSize: 13,
  color: '#3B4233', cursor: 'pointer',
};

/** The segmented control used by the tutor and calendar demos. */
export function Segmented<T extends string>({
  options, value, onChange,
}: {
  options: readonly { key: T; label: string }[];
  value: T;
  onChange: (k: T) => void;
}) {
  return (
    <div className="flex gap-0.5 p-[3px] rounded-[9px] bg-moss-25 border border-moss-75">
      {options.map((o) => {
        const on = o.key === value;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            type="button"
            aria-pressed={on}
            className={cn("py-1.5 px-[13px] rounded-[7px] border-0 cursor-pointer font-sans text-[11.5px] tracking-[0.01em] [transition:all_200ms]", on ? "bg-moss-900" : "bg-transparent", on ? "text-bg-panel" : "text-moss-500", on ? "font-semibold" : "font-normal")}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
