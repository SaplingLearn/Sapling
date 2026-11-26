'use client';

/**
 * Feature lab · calendar.
 *
 * Ported from the `isCal` branch of `FeatureLab.dc.html`. October 2026 with
 * three existing items; upload the syllabus and six more appear, dated.
 *
 * That upload is the demo's whole argument — the month goes from sparse to
 * full in one action, which is what "paste a syllabus, get a semester" means.
 *
 * The leading blanks come from the real weekday of 1 Oct 2026, computed once
 * from a fixed date rather than `new Date()`, so the grid never shifts.
 */

import { useEffect, useRef, useState } from 'react';
import { CAL_BASE, CAL_SYLLABUS, TYPE } from './labData';
import { cn } from "@/lib/cn";

type View = 'month' | 'week' | 'day';
const VIEWS: { key: View; label: string }[] = [
  { key: 'month', label: 'Month' }, { key: 'week', label: 'Week' }, { key: 'day', label: 'Day' },
];
const DOWS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
/** Weekday 1 Oct 2026 falls on; month index 9 is October. */
const LEAD_BLANKS = new Date(2026, 9, 1).getDay();

export function CalendarDemo() {
  const [view, setView] = useState<View>('month');
  const [day, setDay] = useState(24);
  const [uploaded, setUploaded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const items = [...CAL_BASE, ...(uploaded ? CAL_SYLLABUS : [])];

  const cells: { day: number | ''; chips: typeof items; blank: boolean }[] = [];
  for (let i = 0; i < LEAD_BLANKS; i++) cells.push({ day: '', chips: [], blank: true });
  for (let d = 1; d <= 31; d++) cells.push({ day: d, chips: items.filter((a) => a.day === d), blank: false });

  const shown = view === 'month'
    ? cells
    : cells.filter((c) => !c.blank && (view === 'week' ? (c.day as number) >= 19 && (c.day as number) <= 25 : c.day === day));

  const sideItems = items.filter((a) => a.day === day);

  const upload = () => {
    if (uploaded || uploading) return;
    setUploading(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { setUploading(false); setUploaded(true); }, 1100);
  };

  return (
    <div className="ld-lab-split grid grid-cols-[1fr_250px] min-h-full box-border">
      <div className="py-4.5 px-5.5 flex flex-col gap-3 border-r border-r-paper-100">
        <div className="flex items-center gap-2.5">
          <span className="font-serif text-[20px] font-semibold">October 2026</span>
          <div className="ml-auto flex gap-1 p-[3px] rounded-[9px] bg-moss-25 border border-moss-75">
            {VIEWS.map((v) => {
              const on = view === v.key;
              return (
                <button
                  key={v.key}
                  onClick={() => setView(v.key)}
                  type="button"
                  aria-pressed={on}
                  className={cn("py-1.5 px-[13px] rounded-[7px] border-0 font-sans text-sm cursor-pointer [transition:all_180ms]", on ? "bg-moss-900" : "bg-transparent", on ? "text-bg-panel" : "text-moss-500", on ? "font-semibold" : "font-normal")}
                >
                  {v.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-[repeat(7,1fr)] gap-[5px]">
          {DOWS.map((d, i) => (
            <span key={i} className="font-sans text-2xs tracking-[0.01em] text-moss-300 text-center">{d}</span>
          ))}
        </div>

        <div className="flex-1 grid grid-cols-[repeat(7,1fr)] gap-[5px] [align-content:start]">
          {shown.map((c, i) => {
            const selected = c.day === day;
            return (
              <button
                key={i}
                onClick={() => { if (!c.blank) setDay(c.day as number); }}
                type="button"
                className="relative min-h-11 rounded-[8px] p-[5px] flex flex-col gap-[3px] items-start font-sans [transition:all_160ms]" style={{ ...(c.blank
                    ? { background: 'transparent', border: 'none', cursor: 'default' }
                    : {
                        border: `1px solid ${selected ? '#68951F' : '#EDF0EA'}`,
                        background: selected ? '#EAF1E4' : '#FDFCF9',
                        cursor: 'pointer',
                      }) }}
              >
                <span className={cn("font-sans text-[9px]", selected ? "text-brand-forest" : "text-moss-300")}>{c.day}</span>
                {c.chips.map((ch, j) => (
                  <span key={j} className="w-full h-[5px] rounded-[2px] [animation:labIn_300ms_ease_both]" style={{ background: TYPE[ch.type as keyof typeof TYPE] }} />
                ))}
              </button>
            );
          })}
        </div>
      </div>

      <div className="py-4.5 px-4 bg-moss-25 flex flex-col gap-2.5">
        <span className="font-sans text-xs tracking-[0.01em] text-moss-400">OCTOBER {day}</span>

        {sideItems.map((a, i) => (
          <div key={i} className="py-2.5 px-3 rounded-md bg-bg-panel border border-moss-100 flex flex-col gap-[3px] [animation:labIn_280ms_ease_both]">
            <div className="flex items-center gap-[7px]">
              <span className="w-2 h-2 rounded-[2px] flex-[0_0_auto]" style={{ background: TYPE[a.type as keyof typeof TYPE] }} />
              <span className="text-[12.5px] font-semibold text-moss-900">{a.title}</span>
            </div>
            <span className="font-sans text-xs tracking-[0.01em] text-moss-400">
              {a.course} · {a.type}
            </span>
          </div>
        ))}

        {sideItems.length === 0 && (
          <span className="text-sm text-moss-300">Nothing due. Click another day.</span>
        )}

        <div className="mt-auto flex flex-col gap-2">
          <button
            onClick={upload}
            type="button"
            className="ld-labupload py-2.5 px-3 rounded-[9px] border border-dashed border-leaf-500 [background:#EAF1E4] font-sans text-[11.5px] tracking-[0.01em] text-brand-forest cursor-pointer"
          >
            {uploading ? 'Reading syllabus…' : uploaded ? 'Syllabus applied' : '+ Upload ma242_syllabus.pdf'}
          </button>
          <span className="text-xs leading-[1.6] text-moss-300">
            {uploaded
              ? '6 assignments extracted and synced to Google Calendar.'
              : 'One upload fills the month — every pset, quiz, and exam, dated.'}
          </span>
        </div>
      </div>
    </div>
  );
}
