'use client';

/**
 * Feature lab · adaptive quiz.
 *
 * Ported from the `isQuiz` branch of `FeatureLab.dc.html`. Pick an option,
 * submit, read the explanation, advance; three questions then a result card.
 *
 * The adaptivity is the point of the demo: difficulty is derived from the
 * streak, not stored — first question MEDIUM, then HARD while you are on a
 * run and EASY the moment you break it.
 */

import { useState } from 'react';
import { LAB_TIER } from './LabShell';
import { QUESTIONS } from './labData';
import { cn } from "@/lib/cn";

type Phase = 'active' | 'review' | 'results';

export function QuizDemo() {
  const [qi, setQi] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('active');
  const [answers, setAnswers] = useState<boolean[]>([]);
  const [streak, setStreak] = useState(0);

  const q = QUESTIONS[Math.min(qi, QUESTIONS.length - 1)];
  const reviewing = phase === 'review';
  const done = phase === 'results';
  const correctCount = answers.filter(Boolean).length;
  const right = reviewing && q.options.some((o) => o.label === picked && 'correct' in o && o.correct);

  const diff = qi === 0 ? 'Medium' : streak > 0 ? 'Hard' : 'Easy';
  const [diffBg, diffFg] =
    diff === 'Hard' ? ['#b25855', '#9c4b48'] : diff === 'Easy' ? ['#5a7834', '#4a622b'] : ['#c89b5e', '#8a6636'];
  const tier = correctCount >= 2 ? 'learning' : 'struggling';

  const submit = () => {
    if (reviewing) {
      if (qi === QUESTIONS.length - 1) setPhase('results');
      else { setQi(qi + 1); setPicked(null); setPhase('active'); }
      return;
    }
    if (!picked) return;
    const ok = q.options.some((o) => o.label === picked && 'correct' in o && o.correct);
    setAnswers((a) => [...a, ok]);
    setStreak(ok ? streak + 1 : 0);
    setPhase('review');
  };

  const retake = () => { setQi(0); setPicked(null); setPhase('active'); setAnswers([]); setStreak(0); };

  if (done) {
    return (
      <div className="py-5.5 px-6.5 flex flex-col gap-3.5 min-h-full box-border">
        <div className="flex-1 flex flex-col items-center justify-center gap-4 [animation:labIn_320ms_ease_both]">
          <span className="font-serif text-[54px] font-semibold leading-none">
            {correctCount} / {QUESTIONS.length}
          </span>
          <span className="font-sans text-md tracking-[0.01em] text-moss-400">
            {Math.round((correctCount / QUESTIONS.length) * 100)}% CORRECT
          </span>
          <div className="flex items-center gap-[9px] py-[9px] px-4 rounded-[99px] bg-leaf-50 border border-moss-100">
            <span className="text-md text-moss-700">Eigenvalues mastery</span>
            <span className="font-sans text-md font-bold text-brand-forest">
              41% → {41 + correctCount * 7}%  (+{correctCount * 7})
            </span>
          </div>
          <div className="flex gap-2.5 mt-1.5">
            <button onClick={retake} type="button" className="py-2.5 px-5 rounded-md border border-moss-100 bg-bg-panel font-sans text-md text-moss-700 cursor-pointer">
              Retake
            </button>
            <button onClick={retake} type="button" className="py-2.5 px-5 rounded-md border-0 bg-brand-forest text-bg-panel font-sans text-md font-semibold cursor-pointer">
              Learn weak areas
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="py-5.5 px-6.5 flex flex-col gap-3.5 min-h-full box-border">
      <div className="flex items-center justify-between">
        <span className="font-sans text-sm tracking-[0.01em] text-moss-400">
          QUESTION {Math.min(qi + 1, QUESTIONS.length)} of {QUESTIONS.length}
        </span>
        <span className="py-1 px-[11px] rounded-[99px] font-sans text-[11.5px] tracking-[0.01em] [transition:all_300ms]" style={{ border: `1px solid ${diffBg}`, background: `${diffBg}1f`, color: diffFg }}>
          {diff}
        </span>
      </div>

      <div className="flex items-center gap-[7px]">
        <span className="w-2 h-2 rounded-[99px]" style={{ background: LAB_TIER[tier] }} />
        <span className="text-md font-semibold text-moss-700">Eigenvalues</span>
        <span className="font-sans text-[9.5px] text-moss-300">MA 242</span>
        <span className="ml-auto font-sans text-[11.5px] text-moss-400">
          MASTERY {41 + correctCount * 7}%
        </span>
      </div>

      <div>
        <p className="m-0 font-serif text-[20px] leading-[1.4] text-moss-900">{q.text}</p>
        <div role="radiogroup" className="mt-4 flex flex-col gap-2">
          {q.options.map((o) => {
            const isPicked = o.label === picked;
            const correct = 'correct' in o && o.correct;
            let bd = '#E3E0D5', bg = '#FDFCF9', fg = '#3B4233', mark = '', markCol = '';
            if (reviewing && correct) { bd = '#68951F'; bg = '#EAF1E4'; fg = '#445D22'; mark = 'Correct'; markCol = '#445D22'; }
            else if (reviewing && isPicked) { bd = '#b25855'; bg = 'rgba(178,88,85,0.09)'; fg = '#9c4b48'; mark = 'Your pick'; markCol = '#9c4b48'; }
            else if (isPicked) { bd = '#68951F'; bg = '#EAF1E4'; fg = '#445D22'; }
            return (
              <button
                key={o.label}
                type="button"
                onClick={() => { if (!reviewing) setPicked(o.label); }}
                className={cn("text-left flex gap-2.5 items-start py-3 px-3.5 rounded-md font-sans text-base [transition:all_180ms]", reviewing ? "cursor-default" : "cursor-pointer")} style={{ border: `1px solid ${bd}`, background: bg, color: fg }}
              >
                <span className={cn("font-sans text-sm", isPicked || (reviewing && correct) ? "text-leaf-500" : "text-moss-300")}>{o.label}.</span>
                <span>{o.text}</span>
                <span className="ml-auto font-sans text-md tracking-[0.01em]" style={{ color: markCol }}>{mark}</span>
              </button>
            );
          })}
        </div>
      </div>

      {reviewing && (
        <div className="rounded-[12px] bg-moss-25 border border-moss-75 py-3.5 px-4 [animation:labIn_300ms_ease_both]">
          <span className={cn("font-sans text-[11.5px] tracking-[0.01em]", right ? "text-brand-forest" : "text-[#9c4b48]")}>
            {right ? 'Correct' : 'Not quite'}
          </span>
          <p className="mt-[7px] mx-0 mb-0 text-[13.5px] leading-[1.65] text-moss-700">{q.explain}</p>
        </div>
      )}

      <div className="mt-auto flex items-center justify-between border-t border-t-paper-100 pt-3.5">
        <span className="text-sm text-moss-400">
          {streak > 0 ? `${streak} right in a row — next question moves up` : 'Difficulty follows your last answer'}
        </span>
        <button onClick={submit} type="button" className="ld-labprimary py-[11px] px-6 rounded-md border-0 [background:#445D22] text-bg-panel font-sans text-[13.5px] font-semibold cursor-pointer [transition:background_200ms]">
          {reviewing ? (qi === QUESTIONS.length - 1 ? 'See results' : 'Next question') : 'Submit answer'}
        </button>
      </div>
    </div>
  );
}
