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
import { MONO } from './LabShell';
import { GB_CATS, GB_ROWS, LETTERS } from './labData';

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
    <div style={{ padding: '20px 26px', display: 'flex', flexDirection: 'column', gap: 14, minHeight: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 46, fontWeight: 600, lineHeight: 1, transition: 'color 300ms' }}>
            {grade.toFixed(1)}
          </span>
          <span style={{ padding: '5px 12px', borderRadius: 8, background: '#E6F2E8', border: '1px solid #0E9E5A', ...MONO, fontSize: 13, letterSpacing: '0.1em', color: '#0C5638' }}>
            {letter}
          </span>
        </div>
        <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.14em', color: '#8B9891' }}>MA 242 · SPRING 2026</span>
      </div>

      <span style={{ fontSize: 12, color: '#8B9891' }}>
        Type a score to see the grade move — weights came from your syllabus.
      </span>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8, overflow: 'auto' }}>
        {GB_ROWS.map((r, i) => {
          const raw = parseFloat(earned[i]);
          // Clamped identically to the weighted calculation above. Without it,
          // typing 500 into a row worth 50 printed "1000%" beside an overall
          // grade that had already clamped the same entry to 100%.
          const v = isNaN(raw) ? null : Math.max(0, Math.min(raw, r.possible));
          const pct = v === null ? null : Math.round((v / r.possible) * 100);
          const pctColor = pct === null ? '#C3CCC6' : pct >= 90 ? '#0C5638' : pct >= 80 ? '#c89b5e' : '#b25855';
          return (
            <div key={r.title} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px', borderRadius: 11, border: '1px solid #E8E5DA', background: '#FDFCF9' }}>
              <span style={{ width: 9, height: 9, borderRadius: 3, flex: '0 0 auto', background: r.cat === 'PSETS' ? '#0E9E5A' : '#c89b5e' }} />
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#12201A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.title}</span>
                <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.1em', color: '#8B9891' }}>{r.cat}</span>
              </div>
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  value={earned[i]}
                  onChange={(e) => {
                    // Strip non-numerics, then keep only the FIRST decimal
                    // point. `[^0-9.]` alone accepted "1.2.3", which parseFloat
                    // reads as 1.2 — the field showed one number and the grade
                    // was computed from another.
                    const digits = e.target.value.replace(/[^0-9.]/g, '');
                    const dot = digits.indexOf('.');
                    const val = dot === -1
                      ? digits
                      : digits.slice(0, dot + 1) + digits.slice(dot + 1).replace(/\./g, '');
                    setEarned((arr) => arr.map((v2, j) => (j === i ? val : v2)));
                  }}
                  inputMode="decimal"
                  aria-label={`Points earned, ${r.title}`}
                  style={{ width: 56, padding: '7px 8px', borderRadius: 8, border: '1px solid #DCE7DE', background: '#F6F8F4', ...MONO, fontSize: 12.5, textAlign: 'right', color: '#12201A', outline: 'none' }}
                />
                <span style={{ ...MONO, fontSize: 12, color: '#9AA5A0' }}>/ {r.possible}</span>
                <span style={{ width: 44, textAlign: 'right', ...MONO, fontSize: 12, color: pctColor }}>
                  {pct === null ? '—' : `${pct}%`}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 7, borderTop: '1px solid #ECE9DE', paddingTop: 12 }}>
        {cats.map((c) => (
          <div key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 74, fontSize: 12, color: '#33443B' }}>{c.name}</span>
            <span style={{ ...MONO, fontSize: 10, color: '#9AA5A0', width: 30 }}>{c.weight}</span>
            <span style={{ flex: 1, height: 7, borderRadius: 99, background: '#E3EBE5', overflow: 'hidden' }}>
              <span style={{ display: 'block', height: '100%', background: '#0E9E5A', transition: 'width 400ms cubic-bezier(0.22,1,0.36,1)', width: `${c.pct === null ? 0 : Math.max(0, Math.min(100, c.pct))}%` }} />
            </span>
            <span style={{ width: 52, textAlign: 'right', ...MONO, fontSize: 11, color: '#0C5638' }}>
              {c.pct === null ? 'not yet' : `${c.pct.toFixed(1)}%`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
