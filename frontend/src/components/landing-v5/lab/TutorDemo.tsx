'use client';

/**
 * Feature lab · AI tutor.
 *
 * Ported from the `isTutor` branch of `FeatureLab.dc.html`. Three modes over
 * the same concept, each a scripted branching exchange: pick a reply, the
 * tutor thinks for 1.5s, then answers and advances a step.
 *
 * Every branch is authored — including the wrong ones, which is the point.
 * Socratic answers a bad guess with a better question rather than the answer,
 * and TeachBack names the step you skipped. Switching mode resets the thread,
 * because the scripts do not share a position.
 */

import { useEffect, useRef, useState } from 'react';
import { MONO } from './LabShell';
import { TUTOR } from './labData';

type Mode = keyof typeof TUTOR;
const MODES: Mode[] = ['socratic', 'expository', 'teachback'];

interface Msg { text: string; isBot: boolean }

export function TutorDemo() {
  const [mode, setMode] = useState<Mode>('socratic');
  const [step, setStep] = useState(0);
  const [log, setLog] = useState<Msg[]>([]);
  const [thinking, setThinking] = useState(false);
  const [sources, setSources] = useState<readonly string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const T = TUTOR[mode];
  const current = T.steps[step] ?? null;
  const msgs: Msg[] = [{ text: T.open, isBot: true }, ...log];

  const reset = () => {
    if (timer.current) clearTimeout(timer.current);
    setStep(0); setLog([]); setThinking(false); setSources([]);
  };

  const switchMode = (m: Mode) => { setMode(m); reset(); };

  const pick = (i: number) => {
    if (thinking || !current) return;
    const reply = current.replies[i];
    if (!reply) return;
    setLog((l) => [...l, { text: reply.text, isBot: false }]);
    setThinking(true);
    setSources([]);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setThinking(false);
      setLog((l) => [...l, { text: reply.bot, isBot: true }]);
      setStep((s) => s + 1);
      setSources(('sources' in reply && reply.sources) || ('sources' in T && T.sources) || []);
    }, 1500);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', boxSizing: 'border-box' }}>
      <div style={{ flex: '0 0 auto', padding: '14px 22px 12px', borderBottom: '1px solid #ECE9DE', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4, padding: 3, borderRadius: 9, background: '#F6F8F4', border: '1px solid #E3EBE5' }}>
          {MODES.map((k) => {
            const on = mode === k;
            return (
              <button
                key={k}
                onClick={() => switchMode(k)}
                type="button"
                aria-pressed={on}
                style={{ padding: '7px 14px', borderRadius: 7, border: 'none', ...MONO, fontSize: 9.5, letterSpacing: '0.14em', cursor: 'pointer', transition: 'all 200ms', background: on ? '#12201A' : 'transparent', color: on ? '#FDFCF9' : '#61726A', fontWeight: on ? 600 : 400 }}
              >
                {TUTOR[k].label}
              </button>
            );
          })}
        </div>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 7 }}>
          <span style={{ width: 7, height: 7, borderRadius: 99, background: T.tone }} />
          <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.14em', color: '#8B9891' }}>{T.topic}</span>
        </span>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '16px 22px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <span style={{ fontSize: 12, color: '#8B9891' }}>{T.blurb}</span>

        {msgs.map((m, i) => (
          <div key={i} style={{ display: 'flex', gap: 9, animation: 'labIn 460ms cubic-bezier(0.22,1,0.36,1) both', justifyContent: m.isBot ? 'flex-start' : 'flex-end' }}>
            {m.isBot && (
              <span style={{ width: 26, height: 26, flex: '0 0 auto', borderRadius: 99, background: '#E6F2E8', border: '1px solid #C3D8B3', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg viewBox="0 0 16 16" width="12" height="12" fill="#0C5638">
                  <path d="M8 0.9c.55 3.35 1.8 4.6 5.15 5.15C9.8 6.6 8.55 7.85 8 11.2 7.45 7.85 6.2 6.6 2.85 6.05 6.2 5.5 7.45 4.25 8 .9z" />
                </svg>
              </span>
            )}
            <span
              style={{
                padding: '11px 14px', fontSize: 13, lineHeight: 1.6, maxWidth: '74%',
                ...(m.isBot
                  ? { background: '#F6F8F4', border: '1px solid #E3EBE5', borderRadius: '14px 14px 14px 4px', color: '#12201A' }
                  : { background: '#0C5638', color: '#E6F2E8', borderRadius: '14px 14px 4px 14px' }),
              }}
            >
              {m.text}
            </span>
          </div>
        ))}

        {thinking && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 5, paddingLeft: 35 }}>
            {[0, 0.15, 0.3].map((d) => (
              <span key={d} style={{ width: 5, height: 5, borderRadius: 99, background: '#9AA5A0', animation: `typingDot 1.2s ease-in-out ${d}s infinite` }} />
            ))}
          </span>
        )}

        {sources.length > 0 && !thinking && (
          <div style={{ marginLeft: 35, display: 'flex', flexDirection: 'column', gap: 5 }}>
            <span style={{ ...MONO, fontSize: 8.5, letterSpacing: '0.2em', color: '#9AA5A0' }}>GROUNDED IN YOUR UPLOADS</span>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {sources.map((src) => (
                <span key={src} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 9px', borderRadius: 6, background: '#F6F8F4', border: '1px solid #DCE7DE', ...MONO, fontSize: 9, color: '#33443B' }}>
                  <span style={{ width: 5, height: 5, borderRadius: 99, background: '#0E9E5A' }} />
                  {src}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div style={{ flex: '0 0 auto', borderTop: '1px solid #ECE9DE', padding: '12px 22px 14px', display: 'flex', flexDirection: 'column', gap: 9 }}>
        <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
          {current && !thinking && current.replies.map((r, i) => (
            <button
              key={r.text}
              onClick={() => pick(i)}
              type="button"
              className="ld-labreply"
              style={{ padding: '8px 13px', borderRadius: 99, border: '1px solid #DCE7DE', background: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 12.5, color: '#33443B', cursor: 'pointer', transition: 'all 180ms' }}
            >
              {r.text}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ ...MONO, fontSize: 8.5, letterSpacing: '0.14em', color: '#9AA5A0' }}>
            {current
              ? (mode === 'teachback' ? 'IT LISTENS FOR WHAT YOU SKIPPED' : 'IT NEVER HANDS OVER THE ANSWER')
              : 'SESSION COMPLETE · MASTERY WRITTEN BACK TO YOUR GRAPH'}
          </span>
          <button onClick={reset} type="button" className="ld-labrecent" style={{ padding: '7px 14px', borderRadius: 8, border: '1px solid #DCE7DE', background: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 12, color: '#61726A', cursor: 'pointer' }}>
            Start over
          </button>
        </div>
      </div>
    </div>
  );
}
