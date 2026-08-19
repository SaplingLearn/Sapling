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
import { MONO } from './LabShell';
import { CAL_BASE, CAL_SYLLABUS, TYPE } from './labData';

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
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 250px', minHeight: '100%', boxSizing: 'border-box' }}>
      <div style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 12, borderRight: '1px solid #ECE9DE' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 20, fontWeight: 600 }}>October 2026</span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, padding: 3, borderRadius: 9, background: '#F6F8F4', border: '1px solid #E3EBE5' }}>
            {VIEWS.map((v) => {
              const on = view === v.key;
              return (
                <button
                  key={v.key}
                  onClick={() => setView(v.key)}
                  type="button"
                  aria-pressed={on}
                  style={{ padding: '6px 13px', borderRadius: 7, border: 'none', fontFamily: "'DM Sans',sans-serif", fontSize: 12, cursor: 'pointer', transition: 'all 180ms', background: on ? '#12201A' : 'transparent', color: on ? '#FDFCF9' : '#61726A', fontWeight: on ? 600 : 400 }}
                >
                  {v.label}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 5 }}>
          {DOWS.map((d, i) => (
            <span key={i} style={{ ...MONO, fontSize: 8.5, letterSpacing: '0.12em', color: '#9AA5A0', textAlign: 'center' }}>{d}</span>
          ))}
        </div>

        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 5, alignContent: 'start' }}>
          {shown.map((c, i) => {
            const selected = c.day === day;
            return (
              <button
                key={i}
                onClick={() => { if (!c.blank) setDay(c.day as number); }}
                type="button"
                // The lead-in placeholders had `cursor:'default'` and nothing
                // else, so they stayed enabled and focusable: a keyboard user
                // Tabbed through up to six empty buttons before reaching Oct 1.
                disabled={c.blank}
                aria-hidden={c.blank || undefined}
                // Toggle semantics: exactly one day is the selected one, and
                // border colour alone did not say which.
                aria-pressed={c.blank ? undefined : selected}
                style={{
                  position: 'relative', minHeight: 44, borderRadius: 8, padding: 5,
                  display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start',
                  fontFamily: "'DM Sans',sans-serif", transition: 'all 160ms',
                  ...(c.blank
                    ? { background: 'transparent', border: 'none', cursor: 'default' }
                    : {
                        border: `1px solid ${selected ? '#0E9E5A' : '#EBF1EC'}`,
                        background: selected ? '#E6F2E8' : '#FDFCF9',
                        cursor: 'pointer',
                      }),
                }}
              >
                <span style={{ ...MONO, fontSize: 9, color: selected ? '#0C5638' : '#9AA5A0' }}>{c.day}</span>
                {c.chips.map((ch, j) => (
                  <span data-anim key={j} style={{ width: '100%', height: 5, borderRadius: 2, animation: 'labIn 300ms ease both', background: TYPE[ch.type as keyof typeof TYPE] }} />
                ))}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ padding: '18px 16px', background: '#F6F8F4', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.18em', color: '#8B9891' }}>OCTOBER {day}</span>

        {sideItems.map((a, i) => (
          <div data-anim key={i} style={{ padding: '10px 12px', borderRadius: 10, background: '#FDFCF9', border: '1px solid #DCE7DE', display: 'flex', flexDirection: 'column', gap: 3, animation: 'labIn 280ms ease both' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, flex: '0 0 auto', background: TYPE[a.type as keyof typeof TYPE] }} />
              <span style={{ fontSize: 12.5, fontWeight: 600, color: '#12201A' }}>{a.title}</span>
            </div>
            <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.08em', color: '#8B9891' }}>
              {a.course} · {a.type.toUpperCase()}
            </span>
          </div>
        ))}

        {sideItems.length === 0 && (
          <span style={{ fontSize: 12, color: '#9AA5A0' }}>Nothing due. Click another day.</span>
        )}

        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <button
            onClick={upload}
            type="button"
            className="ld-labupload"
            style={{ padding: '10px 12px', borderRadius: 9, border: '1px dashed #0E9E5A', background: '#E6F2E8', ...MONO, fontSize: 9.5, letterSpacing: '0.1em', color: '#0C5638', cursor: 'pointer' }}
          >
            {uploading ? 'READING SYLLABUS…' : uploaded ? 'SYLLABUS APPLIED' : '+ UPLOAD MA242_SYLLABUS.PDF'}
          </button>
          <span style={{ fontSize: 11, lineHeight: 1.6, color: '#9AA5A0' }}>
            {uploaded
              ? '6 assignments extracted and synced to Google Calendar.'
              : 'One upload fills the month — every pset, quiz, and exam, dated.'}
          </span>
        </div>
      </div>
    </div>
  );
}
