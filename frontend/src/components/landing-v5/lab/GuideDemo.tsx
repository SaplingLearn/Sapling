'use client';

/**
 * Feature lab · study guides.
 *
 * Ported from the `isGuide` branch of `FeatureLab.dc.html`. Pick a course and
 * an exam, generate, and the guide is assembled from that course's fixture —
 * topics ordered by weight, heaviest on the concept you miss most.
 *
 * Changing either select drops back to the empty state on purpose: a guide
 * built for one exam should not sit under another exam's heading.
 */

import { useEffect, useRef, useState } from 'react';
import { LAB_TIER, MONO } from './LabShell';
import { GUIDES } from './labData';

type Phase = 'empty' | 'loading' | 'guide';
type CourseKey = keyof typeof GUIDES;

/**
 * The two cached guides in the sidebar.
 *
 * Every `pick` MUST be a verbatim member of `GUIDES[course].exams`: opening a
 * recent item assigns it straight to the exam `<select>`, and an unknown value
 * left the select showing nothing while the heading below printed the phantom
 * exam. The previous entries ('Midterm 1 · Sep 30', 'Quiz 2 · Oct 03') existed
 * in neither course's list.
 */
const RECENT = [
  { i: 0, exam: 'MA 242 · Midterm 2', meta: 'GENERATED SEP 28', course: 'MA 242' as CourseKey, pick: 'Midterm 2 · Oct 24' },
  { i: 1, exam: 'CS 201 · Midterm 1', meta: 'GENERATED OCT 03', course: 'CS 201' as CourseKey, pick: 'Midterm 1 · Oct 17' },
];

const SELECT: React.CSSProperties = {
  padding: '9px 12px', borderRadius: 9, border: '1px solid #DCE7DE', background: '#FDFCF9',
  fontFamily: "'DM Sans',sans-serif", fontSize: 13, color: '#33443B', cursor: 'pointer',
};

export function GuideDemo() {
  const [course, setCourse] = useState<CourseKey>('MA 242');
  const [exam, setExam] = useState('Midterm 2 · Oct 24');
  const [phase, setPhase] = useState<Phase>('empty');
  const [stamp, setStamp] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => clearTimeout(timer.current ?? undefined), []);

  // `course` is a CourseKey, so this is always present — the `?? GUIDES['MA
  // 242']` fallback that used to sit here implied otherwise and disagreed with
  // the direct `GUIDES[course].exams` read further down.
  const set = GUIDES[course];

  const generate = () => {
    setPhase('loading');
    clearTimeout(timer.current ?? undefined);
    timer.current = setTimeout(() => {
      setPhase('guide');
      setStamp('GENERATED ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }).toUpperCase());
    }, 900);
  };

  const openRecent = (r: (typeof RECENT)[number]) => {
    setCourse(r.course);
    setExam(r.pick);
    setPhase('loading');
    clearTimeout(timer.current ?? undefined);
    timer.current = setTimeout(() => { setPhase('guide'); setStamp('FROM CACHE'); }, 500);
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px', minHeight: '100%', boxSizing: 'border-box' }}>
      <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 12, borderRight: '1px solid #ECE9DE' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            value={course}
            onChange={(e) => {
              const c = e.target.value as CourseKey;
              setCourse(c);
              setExam(GUIDES[c].exams[0]);
              setPhase('empty');
            }}
            aria-label="Course"
            style={SELECT}
          >
            {Object.keys(GUIDES).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select
            value={exam}
            onChange={(e) => { setExam(e.target.value); setPhase('empty'); }}
            aria-label="Exam"
            style={SELECT}
          >
            {set.exams.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
          <button
            onClick={generate}
            type="button"
            className="ld-labprimary"
            style={{ marginLeft: 'auto', padding: '10px 18px', borderRadius: 9, border: 'none', background: '#12201A', color: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          >
            {phase === 'guide' ? 'Regenerate' : 'Generate guide'}
          </button>
        </div>

        {phase === 'loading' && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
            <span data-anim style={{ width: 26, height: 26, borderRadius: 99, border: '3px solid #E3EBE5', borderTopColor: '#0E9E5A', animation: 'labSpin 700ms linear infinite' }} />
            <span style={{ fontSize: 12.5, color: '#8B9891' }}>Reading your library — 11 documents…</span>
          </div>
        )}

        {phase === 'guide' && (
          <div data-anim style={{ flex: 1, overflow: 'auto', borderRadius: 12, border: '1px solid #E8E5DA', background: '#FDFCF9', padding: '18px 20px', animation: 'labIn 320ms ease both' }}>
            <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.2em', color: '#8B9891' }}>{course.toUpperCase()} · STUDY GUIDE</span>
            <h4 style={{ margin: '8px 0 0', fontFamily: "'Playfair Display',serif", fontSize: 20, fontWeight: 600 }}>{exam}</h4>
            <p style={{ margin: '8px 0 0', fontSize: 13, lineHeight: 1.7, color: '#61726A' }}>{set.overview}</p>
            <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
              {set.topics.map((t) => (
                <div key={t.name}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 99, background: LAB_TIER[t.tier as keyof typeof LAB_TIER] }} />
                    <span style={{ fontSize: 14, fontWeight: 600, color: '#12201A' }}>{t.name}</span>
                    <span style={{ marginLeft: 'auto', ...MONO, fontSize: 9.5, color: '#8B9891' }}>{t.weight}</span>
                  </div>
                  <p style={{ margin: '4px 0 0 16px', fontSize: 12, fontStyle: 'italic', color: '#8B9891' }}>{t.importance}</p>
                  <ul style={{ margin: '6px 0 0 16px', paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {t.bullets.map((b) => (
                      <li key={b} style={{ fontSize: 12.5, lineHeight: 1.6, color: '#33443B' }}>{b}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <span style={{ display: 'block', marginTop: 16, ...MONO, fontSize: 9, letterSpacing: '0.14em', color: '#9AA5A0' }}>{stamp}</span>
          </div>
        )}

        {phase === 'empty' && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6, color: '#9AA5A0' }}>
            <span style={{ fontSize: 14 }}>No guide yet</span>
            <span style={{ fontSize: 12 }}>Pick a course and exam, then Generate Guide.</span>
          </div>
        )}
      </div>

      <div style={{ padding: '20px 16px', background: '#F6F8F4', display: 'flex', flexDirection: 'column', gap: 9 }}>
        <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.18em', color: '#8B9891' }}>RECENT GUIDES</span>
        {RECENT.map((r) => (
          <button
            key={r.i}
            onClick={() => openRecent(r)}
            type="button"
            className="ld-labrecent"
            style={{ textAlign: 'left', padding: '10px 12px', borderRadius: 10, border: '1px solid #DCE7DE', background: '#FDFCF9', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 2, transition: 'all 180ms' }}
          >
            <span style={{ fontSize: 12.5, fontWeight: 600, color: '#12201A' }}>{r.exam}</span>
            <span style={{ ...MONO, fontSize: 9, color: '#8B9891' }}>{r.meta}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
