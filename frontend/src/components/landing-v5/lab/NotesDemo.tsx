'use client';

/**
 * Feature lab · notetaker.
 *
 * Ported from the `isNotes` branch of `FeatureLab.dc.html`. Type in the note
 * and the save indicator debounces to SAVED after 800ms; SUMMARIZE and
 * EXTRACT CONCEPTS both run against whatever you actually typed.
 *
 * The extraction is regex over the body — deliberately so. It is a demo of
 * the shape of the feature, and it stays honest by finding nothing when you
 * clear the note rather than printing a canned list.
 */

import { useEffect, useRef, useState } from 'react';
import { LAB_TIER } from './LabShell';
import { cn } from "@/lib/cn";

const INITIAL_TITLE = 'Lecture 7 — Eigenvalues';
const INITIAL_BODY = [
  'λ scales v, it never turns it.',
  'Solve det(A − λI) = 0 for λ, then null(A − λI) for the eigenspace.',
  'Repeated eigenvalues do not guarantee enough independent eigenvectors.',
].join('\n');

/** Concept matchers, in the order the source lists them. */
const MATCHERS: { name: string; tier: keyof typeof LAB_TIER; hit: RegExp }[] = [
  { name: 'Eigenvalues', tier: 'struggling', hit: /eigen|λ|\blambda\b/ },
  { name: 'Determinant', tier: 'learning', hit: /det\(|determinant/ },
  { name: 'Null space', tier: 'unexplored', hit: /null|kernel/ },
  { name: 'Diagonalization', tier: 'unexplored', hit: /diagonal/ },
  { name: 'Eigenvectors', tier: 'struggling', hit: /eigenvector|independent/ },
];

export function NotesDemo() {
  const [title, setTitle] = useState(INITIAL_TITLE);
  const [body, setBody] = useState(INITIAL_BODY);
  const [saved, setSaved] = useState(true);
  const [busy, setBusy] = useState(false);
  const [concepts, setConcepts] = useState<{ name: string; tier: keyof typeof LAB_TIER }[]>([]);
  const [summary, setSummary] = useState('');
  const saveT = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (saveT.current) clearTimeout(saveT.current); }, []);

  const touchSave = () => {
    setSaved(false);
    if (saveT.current) clearTimeout(saveT.current);
    saveT.current = setTimeout(() => setSaved(true), 800);
  };

  const extract = () => {
    if (busy) return;
    setBusy(true);
    setTimeout(() => {
      const lower = body.toLowerCase();
      const found = MATCHERS.filter((m) => m.hit.test(lower)).map((m) => ({ name: m.name, tier: m.tier }));
      setConcepts(found.length ? found : [{ name: 'No concepts found', tier: 'unexplored' }]);
      setBusy(false);
    }, 700);
  };

  const summarize = () => {
    if (busy) return;
    setBusy(true);
    setTimeout(() => {
      const lines = body.split('\n').map((l) => l.trim()).filter(Boolean);
      setSummary(
        lines.length
          ? `This note works through ${title.replace(/^[^—]*—\s*/, '').toLowerCase()} in ${lines.length} claims — the key one being: ${lines[0].replace(/\.$/, '')}.`
          : 'Nothing to summarize yet — write a line or two first.',
      );
      setBusy(false);
    }, 700);
  };

  return (
    <div className="ld-lab-split grid grid-cols-[1fr_240px] min-h-full box-border">
      <div className="py-5 px-6 flex flex-col gap-2.5 border-r border-r-paper-100">
        <div className="flex items-center justify-between gap-3">
          <input
            value={title}
            onChange={(e) => { setTitle(e.target.value); touchSave(); }}
            aria-label="Note title"
            className="flex-1 border-0 outline-none bg-transparent font-serif text-2xl font-semibold text-moss-900 p-0"
          />
          <span className={cn("font-sans text-xs tracking-[0.01em] whitespace-nowrap", saved ? "text-[#5a7834]" : "text-moss-300")}>
            {saved ? 'Saved' : 'Saving…'}
          </span>
        </div>

        <textarea
          value={body}
          onChange={(e) => { setBody(e.target.value); touchSave(); }}
          aria-label="Note body"
          spellCheck={false}
          className="flex-1 min-h-47.5 resize-none border border-paper-200 rounded-[12px] bg-bg-panel py-3.5 px-4 font-sans text-base leading-[1.8] text-moss-700 outline-none"
        />

        <div className="flex gap-2 flex-wrap">
          <button onClick={summarize} type="button" className="ld-labaction py-[9px] px-3.5 rounded-[9px] border border-moss-100 [background:#FDFCF9] font-sans text-[11.5px] tracking-[0.01em] text-brand-forest cursor-pointer [transition:all_180ms]">Summarize</button>
          <button onClick={extract} type="button" className="ld-labaction py-[9px] px-3.5 rounded-[9px] border border-moss-100 [background:#FDFCF9] font-sans text-[11.5px] tracking-[0.01em] text-brand-forest cursor-pointer [transition:all_180ms]">Extract concepts</button>
          <button
            onClick={() => setSummary('Lowest-mastery linked concept is Eigenvalues (41%) — /quiz?concept=eigenvalues would open next.')}
            type="button"
            className="ld-labaction py-[9px] px-3.5 rounded-[9px] border border-moss-100 [background:#FDFCF9] font-sans text-[11.5px] tracking-[0.01em] text-brand-forest cursor-pointer [transition:all_180ms]"
          >
            Generate quiz
          </button>
        </div>

        {summary && (
          <div className="rounded-[11px] bg-moss-25 border border-moss-75 py-[13px] px-[15px] [animation:labIn_280ms_ease_both]">
            <span className="font-sans text-xs tracking-[0.01em] text-moss-400">Summary</span>
            <p className="mt-1.5 mx-0 mb-0 text-md leading-[1.65] text-moss-700">{summary}</p>
          </div>
        )}
      </div>

      <div className="py-5 px-4.5 bg-moss-25 flex flex-col gap-2.5">
        <span className="font-sans text-xs tracking-[0.01em] text-moss-400">Linked concepts</span>
        {busy && (
          <span className="flex items-center gap-[7px] text-sm text-moss-400">
            <span className="w-3 h-3 rounded-[99px] border-2 border-moss-100 border-t-leaf-500 [animation:labSpin_700ms_linear_infinite]" />
            reading the note…
          </span>
        )}
        {concepts.map((c) => (
          <span key={c.name} className="flex items-center gap-2 py-2 px-[11px] rounded-[99px] bg-bg-panel border border-moss-100 text-sm text-moss-700 [animation:labIn_300ms_ease_both]">
            <span className="w-[7px] h-[7px] rounded-[99px] flex-[0_0_auto]" style={{ background: LAB_TIER[c.tier] }} />
            {c.name}
          </span>
        ))}
        <span className="mt-auto text-xs leading-[1.6] text-moss-300">
          {concepts.length
            ? `${concepts.length} concepts linked to your MA 242 graph.`
            : 'Concepts you extract are linked to your graph, not just tagged on the note.'}
        </span>
      </div>
    </div>
  );
}
