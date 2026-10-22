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

  const diff = qi === 0 ? 'MEDIUM' : streak > 0 ? 'HARD' : 'EASY';
  const [diffBg, diffFg] =
    diff === 'HARD' ? ['#b25855', '#9c4b48'] : diff === 'EASY' ? ['#5a7834', '#4a622b'] : ['#c89b5e', '#8a6636'];
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
      <div style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column', gap: 14, minHeight: '100%', boxSizing: 'border-box' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, animation: 'labIn 320ms ease both' }}>
          <span style={{ fontFamily: "var(--font-aleo), 'Aleo', Georgia, serif", fontSize: 54, fontWeight: 600, lineHeight: 1 }}>
            {correctCount} / {QUESTIONS.length}
          </span>
          <span style={{ ...MONO, fontSize: 11, letterSpacing: '0.2em', color: '#91978B' }}>
            {Math.round((correctCount / QUESTIONS.length) * 100)}% CORRECT
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '9px 16px', borderRadius: 99, background: '#EAF1E4', border: '1px solid #E0E6DA' }}>
            <span style={{ fontSize: 13, color: '#3B4233' }}>Eigenvalues mastery</span>
            <span style={{ ...MONO, fontSize: 13, fontWeight: 700, color: '#445D22' }}>
              41% → {41 + correctCount * 7}%  (+{correctCount * 7})
            </span>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
            <button onClick={retake} type="button" style={{ padding: '10px 20px', borderRadius: 10, border: '1px solid #E0E6DA', background: '#FDFCF9', fontFamily: "var(--font-suse), 'SUSE', system-ui, sans-serif", fontSize: 13, color: '#3B4233', cursor: 'pointer' }}>
              Retake
            </button>
            <button onClick={retake} type="button" style={{ padding: '10px 20px', borderRadius: 10, border: 'none', background: '#445D22', color: '#FDFCF9', fontFamily: "var(--font-suse), 'SUSE', system-ui, sans-serif", fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
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
        <span style={{ ...MONO, fontSize: 10, letterSpacing: '0.18em', color: '#91978B' }}>
          QUESTION {Math.min(qi + 1, QUESTIONS.length)} OF {QUESTIONS.length}
        </span>
        <span style={{ padding: '4px 11px', borderRadius: 99, ...MONO, fontSize: 9.5, letterSpacing: '0.12em', border: `1px solid ${diffBg}`, background: `${diffBg}1f`, color: diffFg, transition: 'all 300ms' }}>
          {diff}
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <span style={{ width: 8, height: 8, borderRadius: 99, background: LAB_TIER[tier] }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#3B4233' }}>Eigenvalues</span>
        <span style={{ ...MONO, fontSize: 9.5, color: '#9FA49A' }}>MA 242</span>
        <span style={{ marginLeft: 'auto', ...MONO, fontSize: 9.5, color: '#91978B' }}>
          MASTERY {41 + correctCount * 7}%
        </span>
      </div>

      <div>
        <p style={{ margin: 0, fontFamily: "var(--font-aleo), 'Aleo', Georgia, serif", fontSize: 20, lineHeight: 1.4, color: '#191F13' }}>{q.text}</p>
        <div role="radiogroup" style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {q.options.map((o) => {
            const isPicked = o.label === picked;
            const correct = 'correct' in o && o.correct;
            let bd = '#E3E0D5', bg = '#FDFCF9', fg = '#3B4233', mark = '', markCol = '';
            if (reviewing && correct) { bd = '#68951F'; bg = '#EAF1E4'; fg = '#445D22'; mark = 'CORRECT'; markCol = '#445D22'; }
            else if (reviewing && isPicked) { bd = '#b25855'; bg = 'rgba(178,88,85,0.09)'; fg = '#9c4b48'; mark = 'YOUR PICK'; markCol = '#9c4b48'; }
            else if (isPicked) { bd = '#68951F'; bg = '#EAF1E4'; fg = '#445D22'; }
            return (
              <button
                key={o.label}
                type="button"
                onClick={() => { if (!reviewing) setPicked(o.label); }}
                style={{ textAlign: 'left', display: 'flex', gap: 10, alignItems: 'flex-start', padding: '12px 14px', borderRadius: 10, fontFamily: "var(--font-suse), 'SUSE', system-ui, sans-serif", fontSize: 14, transition: 'all 180ms', border: `1px solid ${bd}`, background: bg, color: fg, cursor: reviewing ? 'default' : 'pointer' }}
              >
                <span style={{ ...MONO, fontSize: 12, color: isPicked || (reviewing && correct) ? '#68951F' : '#9FA49A' }}>{o.label}.</span>
                <span>{o.text}</span>
                <span style={{ marginLeft: 'auto', ...MONO, fontSize: 11, letterSpacing: '0.14em', color: markCol }}>{mark}</span>
              </button>
            );
          })}
        </div>
      </div>

      {reviewing && (
        <div style={{ borderRadius: 12, background: '#F6F8F4', border: '1px solid #E6EAE2', padding: '14px 16px', animation: 'labIn 300ms ease both' }}>
          <span style={{ ...MONO, fontSize: 9.5, letterSpacing: '0.2em', color: right ? '#445D22' : '#9c4b48' }}>
            {right ? 'CORRECT' : 'NOT QUITE'}
          </span>
          <p style={{ margin: '7px 0 0', fontSize: 13.5, lineHeight: 1.65, color: '#3B4233' }}>{q.explain}</p>
        </div>
      )}

      <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid #ECE9DE', paddingTop: 14 }}>
        <span style={{ fontSize: 12, color: '#91978B' }}>
          {streak > 0 ? `${streak} right in a row — next question moves up` : 'Difficulty follows your last answer'}
        </span>
        <button onClick={submit} type="button" className="ld-labprimary" style={PRIMARY_BTN}>
          {reviewing ? (qi === QUESTIONS.length - 1 ? 'See results' : 'Next question') : 'Submit answer'}
        </button>
      </div>
    </div>
  );
}
