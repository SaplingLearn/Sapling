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
import { LAB_TIER, MONO, PRIMARY_BTN } from './LabShell';
import { QUESTIONS } from './labData';

type Phase = 'active' | 'review' | 'results';

/**
 * Whether `label` names the correct option of `q`.
 *
 * The `'correct' in o` narrowing exists because only the right answer carries
 * the flag. This was written out twice — once for the review banner, once in
 * `submit()` — and the two had to agree for the streak and the banner to
 * match.
 */
function isCorrectPick(q: (typeof QUESTIONS)[number], label: string | null): boolean {
  return q.options.some((o) => o.label === label && 'correct' in o && o.correct);
}

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
  const right = reviewing && isCorrectPick(q, picked);

  const diff = qi === 0 ? 'MEDIUM' : streak > 0 ? 'HARD' : 'EASY';
  const [diffBg, diffFg] =
    diff === 'HARD' ? ['#b25855', '#9c4b48'] : diff === 'EASY' ? ['#3a7d4e', '#2f6640'] : ['#c89b5e', '#8a6636'];
  const tier = correctCount >= 2 ? 'learning' : 'struggling';

  const submit = () => {
    if (reviewing) {
      if (qi === QUESTIONS.length - 1) setPhase('results');
      else { setQi(qi + 1); setPicked(null); setPhase('active'); }
      return;
    }
    if (!picked) return;
    const ok = isCorrectPick(q, picked);
    setAnswers((a) => [...a, ok]);
    // Functional updater: reading `streak` from the render closure meant a
    // second submit in the same commit batch computed from a stale value.
    setStreak((s) => (ok ? s + 1 : 0));
    setPhase('review');
  };

  const retake = () => { setQi(0); setPicked(null); setPhase('active'); setAnswers([]); setStreak(0); };

  if (done) {
    return (
      <div style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column', gap: 14, minHeight: '100%', boxSizing: 'border-box' }}>
        <div data-anim style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, animation: 'labIn 320ms ease both' }}>
          <span style={{ fontFamily: "'Playfair Display',serif", fontSize: 54, fontWeight: 600, lineHeight: 1 }}>
            {correctCount} / {QUESTIONS.length}
          </span>
          <span style={{ ...MONO, fontSize: 11, letterSpacing: '0.2em', color: '#8B9891' }}>
            {Math.round((correctCount / QUESTIONS.length) * 100)}% CORRECT
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '9px 16px', borderRadius: 99, background: '#E6F2E8', border: '1px solid #DCE7DE' }}>
            <span style={{ fontSize: 13, color: '#33443B' }}>Eigenvalues mastery</span>
            <span style={{ ...MONO, fontSize: 13, fontWeight: 700, color: '#0C5638' }}>
              41% → {41 + correctCount * 7}%  (+{correctCount * 7})
            </span>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
            <button onClick={retake} type="button" style={{ padding: '10px 20px', borderRadius: 10, border: '1px solid #DCE7DE', background: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 13, color: '#33443B', cursor: 'pointer' }}>
              Retake
            </button>
            <button onClick={retake} type="button" style={{ padding: '10px 20px', borderRadius: 10, border: 'none', background: '#0C5638', color: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              Learn weak areas
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column', gap: 14, minHeight: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.18em', color: '#8B9891' }}>
          QUESTION {Math.min(qi + 1, QUESTIONS.length)} OF {QUESTIONS.length}
        </span>
        <span style={{ padding: '4px 11px', borderRadius: 99, ...MONO, fontSize: 9.5, letterSpacing: '0.12em', border: `1px solid ${diffBg}`, background: `${diffBg}1f`, color: diffFg, transition: 'all 300ms' }}>
          {diff}
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <span style={{ width: 8, height: 8, borderRadius: 99, background: LAB_TIER[tier] }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#33443B' }}>Eigenvalues</span>
        <span style={{ ...MONO, fontSize: 9.5, color: '#9AA5A0' }}>MA 242</span>
        <span style={{ marginLeft: 'auto', ...MONO, fontSize: 9.5, color: '#8B9891' }}>
          MASTERY {41 + correctCount * 7}%
        </span>
      </div>

      <div>
        <p style={{ margin: 0, fontFamily: "'Playfair Display',serif", fontSize: 20, lineHeight: 1.4, color: '#12201A' }}>{q.text}</p>
        <div role="radiogroup" aria-label="Answer options" style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {q.options.map((o) => {
            const isPicked = o.label === picked;
            const correct = 'correct' in o && o.correct;
            let bd = '#E3E0D5', bg = '#FDFCF9', fg = '#33443B', mark = '', markCol = '';
            if (reviewing && correct) { bd = '#0E9E5A'; bg = '#E6F2E8'; fg = '#0C5638'; mark = 'CORRECT'; markCol = '#0C5638'; }
            else if (reviewing && isPicked) { bd = '#b25855'; bg = 'rgba(178,88,85,0.09)'; fg = '#9c4b48'; mark = 'YOUR PICK'; markCol = '#9c4b48'; }
            else if (isPicked) { bd = '#0E9E5A'; bg = '#E6F2E8'; fg = '#0C5638'; }
            return (
              <button
                key={o.label}
                type="button"
                // The container declares radiogroup, which suppresses the
                // implicit button roles of its children — assistive tech
                // announced an empty group with no options in it.
                role="radio"
                aria-checked={isPicked}
                onClick={() => { if (!reviewing) setPicked(o.label); }}
                style={{ textAlign: 'left', display: 'flex', gap: 10, alignItems: 'flex-start', padding: '12px 14px', borderRadius: 10, fontFamily: "'DM Sans',sans-serif", fontSize: 14, transition: 'all 180ms', border: `1px solid ${bd}`, background: bg, color: fg, cursor: reviewing ? 'default' : 'pointer' }}
              >
                <span style={{ ...MONO, fontSize: 12, color: isPicked || (reviewing && correct) ? '#0E9E5A' : '#9AA5A0' }}>{o.label}.</span>
                <span>{o.text}</span>
                <span style={{ marginLeft: 'auto', ...MONO, fontSize: 11, letterSpacing: '0.14em', color: markCol }}>{mark}</span>
              </button>
            );
          })}
        </div>
      </div>

      {reviewing && (
        <div data-anim style={{ borderRadius: 12, background: '#F6F8F4', border: '1px solid #E3EBE5', padding: '14px 16px', animation: 'labIn 300ms ease both' }}>
          <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.2em', color: right ? '#0C5638' : '#9c4b48' }}>
            {right ? 'CORRECT' : 'NOT QUITE'}
          </span>
          <p style={{ margin: '7px 0 0', fontSize: 13.5, lineHeight: 1.65, color: '#33443B' }}>{q.explain}</p>
        </div>
      )}

      <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid #ECE9DE', paddingTop: 14 }}>
        <span style={{ fontSize: 12, color: '#8B9891' }}>
          {streak > 0 ? `${streak} right in a row — next question moves up` : 'Difficulty follows your last answer'}
        </span>
        <button onClick={submit} type="button" className="ld-labprimary" style={PRIMARY_BTN}>
          {reviewing ? (qi === QUESTIONS.length - 1 ? 'See results' : 'Next question') : 'Submit answer'}
        </button>
      </div>
    </div>
  );
}
