'use client';

/**
 * Feature lab · gradebook.
 *
 * Ported from the `isGrades` branch of `FeatureLab.dc.html`. Every score is
 * editable and the weighted grade and letter move as you type.
 *
 * The weighting only counts categories that have a score. `Final` carries 25%
 * but has no rows yet, so it is excluded from the denominator rather than
 * treated as a zero — otherwise the demo would open on an F.
 */

import { useState } from 'react';
import { GB_CATS, GB_ROWS, LETTERS } from './labData';
import { cn } from "@/lib/cn";

export function GradesDemo() {
  const [earned, setEarned] = useState<string[]>(GB_ROWS.map((r) => String(r.earned)));

  // ── weighted grade ──
  const byCat: Record<string, { e: number; p: number }> = {};
  GB_ROWS.forEach((r, i) => {
    const raw = parseFloat(earned[i]);
    const v = isNaN(raw) ? 0 : Math.max(0, Math.min(raw, r.possible));
    const b = (byCat[r.cat] ||= { e: 0, p: 0 });
    b.e += v;
    b.p += r.possible;
  });

  let num = 0;
  let den = 0;
  const cats = GB_CATS.map((c) => {
    const b = byCat[c.key];
    const pct = b && b.p ? (b.e / b.p) * 100 : null;
    if (pct !== null) { num += pct * c.weight; den += c.weight; }
    return { name: c.name, weight: `${Math.round(c.weight * 100)}%`, pct };
  });
  const grade = den ? num / den : 0;
  // bands run high to low, so the first match is the letter
  const letter = (LETTERS.find(([min]) => grade >= min) ?? LETTERS[LETTERS.length - 1])[1];

  return (
    <div className="py-5 px-6.5 flex flex-col gap-3.5 min-h-full box-border">
      <div className="flex items-end justify-between">
        <div className="flex items-baseline gap-3">
          <span className="font-serif text-[46px] font-semibold leading-none [transition:color_300ms]">
            {grade.toFixed(1)}
          </span>
          <span className="py-[5px] px-3 rounded-[8px] bg-leaf-50 border border-leaf-500 font-sans text-md tracking-[0.01em] text-brand-forest">
            {letter}
          </span>
        </div>
        <span className="font-sans text-[11.5px] tracking-[0.01em] text-moss-400">MA 242 · Spring 2026</span>
      </div>

      <span className="text-sm text-moss-400">
        Type a score to see the grade move — weights came from your syllabus.
      </span>

      <div className="flex-1 flex flex-col gap-2 overflow-auto">
        {GB_ROWS.map((r, i) => {
          const raw = parseFloat(earned[i]);
          const pct = isNaN(raw) ? null : Math.round((raw / r.possible) * 100);
          const pctColor = pct === null ? '#C7CBC2' : pct >= 90 ? '#445D22' : pct >= 80 ? '#c89b5e' : '#b25855';
          return (
            <div key={r.title} className="flex items-center gap-3 py-[11px] px-3.5 rounded-[11px] border border-paper-200 bg-bg-panel">
              <span className={cn("w-[9px] h-[9px] rounded-[3px] flex-[0_0_auto]", r.cat === 'Psets' ? "bg-leaf-500" : "bg-state-progress")} />
              <div className="flex flex-col min-w-0">
                <span className="text-md font-semibold text-moss-900 whitespace-nowrap overflow-hidden text-ellipsis">{r.title}</span>
                <span className="font-sans text-xs tracking-[0.01em] text-moss-400">{r.cat}</span>
              </div>
              <div className="ml-auto flex items-center gap-1.5">
                <input
                  value={earned[i]}
                  onChange={(e) => {
                    const val = e.target.value.replace(/[^0-9.]/g, '');
                    setEarned((arr) => arr.map((v, j) => (j === i ? val : v)));
                  }}
                  inputMode="decimal"
                  aria-label={`Points earned, ${r.title}`}
                  className="w-14 py-[7px] px-2 rounded-[8px] border border-moss-100 bg-moss-25 font-sans text-[12.5px] text-right text-moss-900 outline-none"
                />
                <span className="font-sans text-sm text-moss-300">/ {r.possible}</span>
                <span className="w-11 text-right font-sans text-sm" style={{ color: pctColor }}>
                  {pct === null ? '—' : `${pct}%`}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-col gap-[7px] border-t border-t-paper-100 pt-3">
        {cats.map((c) => (
          <div key={c.name} className="flex items-center gap-2.5">
            <span className="w-18.5 text-sm text-moss-700">{c.name}</span>
            <span className="font-sans text-2xs text-moss-300 w-7.5">{c.weight}</span>
            <span className="flex-1 h-[7px] rounded-[99px] bg-moss-75 overflow-hidden">
              <span className="block h-full bg-leaf-500 [transition:width_400ms_cubic-bezier(0.22,1,0.36,1)]" style={{ width: `${c.pct === null ? 0 : Math.max(0, Math.min(100, c.pct))}%` }} />
            </span>
            <span className="w-13 text-right font-sans text-xs text-brand-forest">
              {c.pct === null ? 'not yet' : `${c.pct.toFixed(1)}%`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
