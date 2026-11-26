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
import { TUTOR } from './labData';
import { cn } from "@/lib/cn";

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
    <div className="flex flex-col min-h-full box-border">
      <div className="flex-[0_0_auto] pt-3.5 px-5.5 pb-3 border-b border-b-paper-100 flex items-center gap-2.5 flex-wrap">
        <div className="flex gap-1 p-[3px] rounded-[9px] bg-moss-25 border border-moss-75">
          {MODES.map((k) => {
            const on = mode === k;
            return (
              <button
                key={k}
                onClick={() => switchMode(k)}
                type="button"
                aria-pressed={on}
                className={cn("py-[7px] px-3.5 rounded-[7px] border-0 font-sans text-[11.5px] tracking-[0.01em] cursor-pointer [transition:all_200ms]", on ? "bg-moss-900" : "bg-transparent", on ? "text-bg-panel" : "text-moss-500", on ? "font-semibold" : "font-normal")}
              >
                {TUTOR[k].label}
              </button>
            );
          })}
        </div>
        <span className="ml-auto flex items-center gap-[7px]">
          <span className="w-[7px] h-[7px] rounded-[99px]" style={{ background: T.tone }} />
          <span className="font-sans text-xs tracking-[0.01em] text-moss-400">{T.topic}</span>
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-auto py-4 px-5.5 flex flex-col gap-2.5">
        <span className="text-sm text-moss-400">{T.blurb}</span>

        {msgs.map((m, i) => (
          <div key={i} className={cn("flex gap-[9px] [animation:labIn_460ms_cubic-bezier(0.22,1,0.36,1)_both]", m.isBot ? "justify-start" : "justify-end")}>
            {m.isBot && (
              <span className="w-6.5 h-6.5 flex-[0_0_auto] rounded-[99px] bg-leaf-50 border border-sap-200 flex items-center justify-center">
                <svg viewBox="0 0 16 16" width="12" height="12" fill="#445D22">
                  <path d="M8 0.9c.55 3.35 1.8 4.6 5.15 5.15C9.8 6.6 8.55 7.85 8 11.2 7.45 7.85 6.2 6.6 2.85 6.05 6.2 5.5 7.45 4.25 8 .9z" />
                </svg>
              </span>
            )}
            <span
              className="py-[11px] px-3.5 text-md leading-[1.6] max-w-[74%]" style={{ ...(m.isBot
                  ? { background: '#F6F8F4', border: '1px solid #E6EAE2', borderRadius: '14px 14px 14px 4px', color: '#191F13' }
                  : { background: '#445D22', color: '#EAF1E4', borderRadius: '14px 14px 4px 14px' }) }}
            >
              {m.text}
            </span>
          </div>
        ))}

        {thinking && (
          <span className="flex items-center gap-[5px] pl-[35px]">
            {[0, 0.15, 0.3].map((d) => (
              <span key={d} className="w-[5px] h-[5px] rounded-[99px] bg-moss-300" style={{ animation: `typingDot 1.2s ease-in-out ${d}s infinite` }} />
            ))}
          </span>
        )}

        {sources.length > 0 && !thinking && (
          <div className="ml-[35px] flex flex-col gap-[5px]">
            <span className="font-sans text-2xs tracking-[0.01em] text-moss-300">Grounded in your uploads</span>
            <div className="flex gap-1.5 flex-wrap">
              {sources.map((src) => (
                <span key={src} className="flex items-center gap-[5px] py-1 px-[9px] rounded-sm bg-moss-25 border border-moss-100 font-sans text-[9px] text-moss-700">
                  <span className="w-[5px] h-[5px] rounded-[99px] bg-leaf-500" />
                  {src}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex-[0_0_auto] border-t border-t-paper-100 pt-3 px-5.5 pb-3.5 flex flex-col gap-[9px]">
        <div className="flex gap-[7px] flex-wrap">
          {current && !thinking && current.replies.map((r, i) => (
            <button
              key={r.text}
              onClick={() => pick(i)}
              type="button"
              className="ld-labreply py-2 px-[13px] rounded-[99px] border border-moss-100 [background:#FDFCF9] font-sans text-[12.5px] text-moss-700 cursor-pointer [transition:all_180ms]"
            >
              {r.text}
            </button>
          ))}
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="font-sans text-2xs tracking-[0.01em] text-moss-300">
            {current
              ? (mode === 'teachback' ? 'It listens for what you skipped' : 'It never hands over the answer')
              : 'Session complete · Mastery written back to your graph'}
          </span>
          <button onClick={reset} type="button" className="ld-labrecent py-[7px] px-3.5 rounded-[8px] border border-moss-100 [background:#FDFCF9] font-sans text-sm text-moss-500 cursor-pointer">
            Start over
          </button>
        </div>
      </div>
    </div>
  );
}
