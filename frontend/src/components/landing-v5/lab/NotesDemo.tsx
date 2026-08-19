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
import { LAB_TIER, MONO } from './LabShell';

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

const ACTION_BTN: React.CSSProperties = {
  padding: '9px 14px', borderRadius: 9, border: '1px solid #DCE7DE', background: '#FDFCF9',
  ...MONO, fontSize: 9.5, letterSpacing: '0.1em', color: '#0C5638',
  cursor: 'pointer', transition: 'all 180ms',
};

export function NotesDemo() {
  const [title, setTitle] = useState(INITIAL_TITLE);
  const [body, setBody] = useState(INITIAL_BODY);
  const [saved, setSaved] = useState(true);
  const [busy, setBusy] = useState(false);
  const [concepts, setConcepts] = useState<{ name: string; tier: keyof typeof LAB_TIER }[]>([]);
  /**
   * True once an extraction has run and matched nothing.
   *
   * The "No concepts found" sentinel used to be pushed into `concepts` itself,
   * so the footer counted it and printed "1 concepts linked to your MA 242
   * graph" for a note with no concepts at all.
   */
  const [noneFound, setNoneFound] = useState(false);
  const [summary, setSummary] = useState('');
  const saveT = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Both fake-latency timers call setState 700ms later, so both had to be
  // cancellable on unmount — same reason `saveT` already is.
  const extractT = useRef<ReturnType<typeof setTimeout> | null>(null);
  const summarizeT = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    clearTimeout(saveT.current ?? undefined);
    clearTimeout(extractT.current ?? undefined);
    clearTimeout(summarizeT.current ?? undefined);
  }, []);

  const touchSave = () => {
    setSaved(false);
    clearTimeout(saveT.current ?? undefined);
    saveT.current = setTimeout(() => setSaved(true), 800);
  };

  const extract = () => {
    if (busy) return;
    setBusy(true);
    clearTimeout(extractT.current ?? undefined);
    extractT.current = setTimeout(() => {
      const lower = body.toLowerCase();
      const found = MATCHERS.filter((m) => m.hit.test(lower)).map((m) => ({ name: m.name, tier: m.tier }));
      setConcepts(found);
      setNoneFound(found.length === 0);
      setBusy(false);
    }, 700);
  };

  const summarize = () => {
    if (busy) return;
    setBusy(true);
    clearTimeout(summarizeT.current ?? undefined);
    summarizeT.current = setTimeout(() => {
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
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 240px', minHeight: '100%', boxSizing: 'border-box' }}>
      <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 10, borderRight: '1px solid #ECE9DE' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <input
            value={title}
            onChange={(e) => { setTitle(e.target.value); touchSave(); }}
            aria-label="Note title"
            style={{ flex: 1, border: 'none', outline: 'none', background: 'transparent', fontFamily: "'Playfair Display',serif", fontSize: 22, fontWeight: 600, color: '#12201A', padding: 0 }}
          />
          <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.16em', whiteSpace: 'nowrap', color: saved ? '#3a7d4e' : '#9AA5A0' }}>
            {saved ? 'SAVED' : 'SAVING…'}
          </span>
        </div>

        <textarea
          value={body}
          onChange={(e) => { setBody(e.target.value); touchSave(); }}
          aria-label="Note body"
          spellCheck={false}
          style={{ flex: 1, minHeight: 190, resize: 'none', border: '1px solid #E8E5DA', borderRadius: 12, background: '#FDFCF9', padding: '14px 16px', fontFamily: "'DM Sans',sans-serif", fontSize: 14, lineHeight: 1.8, color: '#33443B', outline: 'none' }}
        />

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={summarize} type="button" className="ld-labaction" style={ACTION_BTN}>SUMMARIZE</button>
          <button onClick={extract} type="button" className="ld-labaction" style={ACTION_BTN}>EXTRACT CONCEPTS</button>
          <button
            onClick={() => setSummary('Lowest-mastery linked concept is Eigenvalues (41%) — /quiz?concept=eigenvalues would open next.')}
            type="button"
            className="ld-labaction"
            style={ACTION_BTN}
          >
            GENERATE QUIZ
          </button>
        </div>

        {summary && (
          <div data-anim style={{ borderRadius: 11, background: '#F6F8F4', border: '1px solid #E3EBE5', padding: '13px 15px', animation: 'labIn 280ms ease both' }}>
            <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.2em', color: '#8B9891' }}>SUMMARY</span>
            <p style={{ margin: '6px 0 0', fontSize: 13, lineHeight: 1.65, color: '#33443B' }}>{summary}</p>
          </div>
        )}
      </div>

      <div style={{ padding: '20px 18px', background: '#F6F8F4', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.18em', color: '#8B9891' }}>LINKED CONCEPTS</span>
        {busy && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: '#8B9891' }}>
            <span data-anim style={{ width: 12, height: 12, borderRadius: 99, border: '2px solid #DCE7DE', borderTopColor: '#0E9E5A', animation: 'labSpin 700ms linear infinite' }} />
            reading the note…
          </span>
        )}
        {concepts.map((c) => (
          <span data-anim key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', borderRadius: 99, background: '#FDFCF9', border: '1px solid #DCE7DE', fontSize: 12, color: '#33443B', animation: 'labIn 300ms ease both' }}>
            <span style={{ width: 7, height: 7, borderRadius: 99, flex: '0 0 auto', background: LAB_TIER[c.tier] }} />
            {c.name}
          </span>
        ))}
        {/* Rendered on its own, so the footer count below never includes it. */}
        {noneFound && !busy && (
          <span data-anim style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', borderRadius: 99, background: '#FDFCF9', border: '1px dashed #DCE7DE', fontSize: 12, color: '#9AA5A0', animation: 'labIn 300ms ease both' }}>
            No concepts found
          </span>
        )}
        <span style={{ marginTop: 'auto', fontSize: 11, lineHeight: 1.6, color: '#9AA5A0' }}>
          {concepts.length
            ? `${concepts.length} ${concepts.length === 1 ? 'concept' : 'concepts'} linked to your MA 242 graph.`
            : 'Concepts you extract are linked to your graph, not just tagged on the note.'}
        </span>
      </div>
    </div>
  );
}
