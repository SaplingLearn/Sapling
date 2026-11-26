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
import { LAB_TIER } from './LabShell';
import { GUIDES } from './labData';

type Phase = 'empty' | 'loading' | 'guide';
type CourseKey = keyof typeof GUIDES;

const RECENT = [
  { i: 0, exam: 'MA 242 · Midterm 1', meta: 'Generated Sep 28', course: 'MA 242' as CourseKey, pick: 'Midterm 1 · Sep 30' },
  { i: 1, exam: 'CS 201 · Quiz 2', meta: 'Generated Oct 03', course: 'CS 201' as CourseKey, pick: 'Quiz 2 · Oct 03' },
];

export function GuideDemo() {
  const [course, setCourse] = useState<CourseKey>('MA 242');
  const [exam, setExam] = useState('Midterm 2 · Oct 24');
  const [phase, setPhase] = useState<Phase>('empty');
  const [stamp, setStamp] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const set = GUIDES[course] ?? GUIDES['MA 242'];

  const generate = () => {
    setPhase('loading');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setPhase('guide');
      setStamp('Generated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    }, 900);
  };

  const openRecent = (r: (typeof RECENT)[number]) => {
    setCourse(r.course);
    setExam(r.pick);
    setPhase('loading');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { setPhase('guide'); setStamp('From cache'); }, 500);
  };

  return (
    <div className="ld-lab-split grid grid-cols-[1fr_220px] min-h-full box-border">
      <div className="py-5 px-6 flex flex-col gap-3 border-r border-r-paper-100">
        <div className="flex gap-2.5 items-center flex-wrap">
          <select
            value={course}
            onChange={(e) => {
              const c = e.target.value as CourseKey;
              setCourse(c);
              setExam(GUIDES[c].exams[0]);
              setPhase('empty');
            }}
            aria-label="Course"
            className="py-[9px] px-3 rounded-[9px] border border-moss-100 bg-bg-panel font-sans text-md text-moss-700 cursor-pointer"
          >
            {Object.keys(GUIDES).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select
            value={exam}
            onChange={(e) => { setExam(e.target.value); setPhase('empty'); }}
            aria-label="Exam"
            className="py-[9px] px-3 rounded-[9px] border border-moss-100 bg-bg-panel font-sans text-md text-moss-700 cursor-pointer"
          >
            {set.exams.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
          <button
            onClick={generate}
            type="button"
            className="ld-labprimary ml-auto py-2.5 px-4.5 rounded-[9px] border-0 [background:#191F13] text-bg-panel font-sans text-md font-semibold cursor-pointer"
          >
            {phase === 'guide' ? 'Regenerate' : 'Generate guide'}
          </button>
        </div>

        {phase === 'loading' && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3">
            <span className="w-6.5 h-6.5 rounded-[99px] border-3 border-moss-75 border-t-leaf-500 [animation:labSpin_700ms_linear_infinite]" />
            <span className="text-[12.5px] text-moss-400">Reading your library — 11 documents…</span>
          </div>
        )}

        {phase === 'guide' && (
          <div className="flex-1 overflow-auto rounded-[12px] border border-paper-200 bg-bg-panel py-4.5 px-5 [animation:labIn_320ms_ease_both]">
            <span className="font-sans text-xs tracking-[0.01em] text-moss-400">{course} · STUDY GUIDE</span>
            <h4 className="mt-2 mx-0 mb-0 font-display text-[20px] font-semibold">{exam}</h4>
            <p className="mt-2 mx-0 mb-0 text-md leading-[1.7] text-moss-500">{set.overview}</p>
            <div className="mt-4 flex flex-col gap-3.5">
              {set.topics.map((t) => (
                <div key={t.name}>
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-[99px]" style={{ background: LAB_TIER[t.tier as keyof typeof LAB_TIER] }} />
                    <span className="text-base font-semibold text-moss-900">{t.name}</span>
                    <span className="ml-auto font-sans text-[9.5px] text-moss-400">{t.weight}</span>
                  </div>
                  <p className="mt-1 mr-0 mb-0 ml-4 text-sm italic text-moss-400">{t.importance}</p>
                  <ul className="mt-1.5 mr-0 mb-0 ml-4 pl-4 flex flex-col gap-[3px]">
                    {t.bullets.map((b) => (
                      <li key={b} className="text-[12.5px] leading-[1.6] text-moss-700">{b}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <span className="block mt-4 font-sans text-xs tracking-[0.01em] text-moss-300">{stamp}</span>
          </div>
        )}

        {phase === 'empty' && (
          <div className="flex-1 flex flex-col items-center justify-center gap-1.5 text-moss-300">
            <span className="text-base">No guide yet</span>
            <span className="text-sm">Pick a course and exam, then Generate Guide.</span>
          </div>
        )}
      </div>

      <div className="py-5 px-4 bg-moss-25 flex flex-col gap-[9px]">
        <span className="font-sans text-xs tracking-[0.01em] text-moss-400">Recent guides</span>
        {RECENT.map((r) => (
          <button
            key={r.i}
            onClick={() => openRecent(r)}
            type="button"
            className="ld-labrecent text-left py-2.5 px-3 rounded-md border border-moss-100 [background:#FDFCF9] cursor-pointer flex flex-col gap-0.5 [transition:all_180ms]"
          >
            <span className="text-[12.5px] font-semibold text-moss-900">{r.exam}</span>
            <span className="font-sans text-[9px] text-moss-400">{r.meta}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
