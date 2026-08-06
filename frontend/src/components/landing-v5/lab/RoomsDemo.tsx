'use client';

/**
 * Feature lab · study rooms.
 *
 * Ported from the `isRooms` branch of `FeatureLab.dc.html`. A shared graph
 * beside a live chat: swap partner and every node's ring recolours to show
 * who has mastered what.
 *
 * The ring encodes the pair, not the person — you / them / both / neither —
 * which is the whole argument for studying next to someone. Only `mastered`
 * counts as knowing it, so the rank comparison is `>= 3`, not "better than".
 */

import { useEffect, useRef, useState } from 'react';
import { LAB_TIER, MONO } from './LabShell';
import { GRAPH_EDGES, GRAPH_NODES } from './labData';

const RING = { you: '#38bdf8', them: '#fb923c', both: '#34d399', neither: '#f87171' } as const;
const RANK = { unexplored: 0, struggling: 1, learning: 2, mastered: 3 } as const;
const PARTNERS = ['maya', 'jack', 'priya'] as const;
type Partner = (typeof PARTNERS)[number];

const LEGEND: [keyof typeof RING, string][] = [
  ['you', 'You know it'], ['them', 'They know it'], ['both', 'Both mastered'], ['neither', 'Neither yet'],
];

const NODE_BY_ID = Object.fromEntries(GRAPH_NODES.map((n) => [n.id, n]));

export function RoomsDemo() {
  const [partner, setPartner] = useState<Partner>('maya');
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [msgs, setMsgs] = useState<{ who: string; text: string; mine: boolean }[]>([
    { who: 'maya', text: 'stuck on AVL-style rotations for eigenbases — anyone?', mine: false },
    { who: 'you', text: 'same. comparing graphs now', mine: true },
  ]);
  const typeT = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (typeT.current) clearTimeout(typeT.current); }, []);

  const send = () => {
    const t = input.trim();
    if (!t) return;
    setMsgs((m) => [...m, { who: 'you', text: t, mine: true }]);
    setInput('');
    setTyping(true);
    if (typeT.current) clearTimeout(typeT.current);
    typeT.current = setTimeout(() => {
      const reply = `my ${partner.charAt(0).toUpperCase() + partner.slice(1)} graph has eigenvalues green — want me to quiz you on it?`;
      setTyping(false);
      setMsgs((m) => [...m, { who: partner, text: reply, mine: false }]);
    }, 1600);
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', minHeight: '100%', boxSizing: 'border-box' }}>
      <div style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 10, borderRight: '1px solid #ECE9DE' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>MA 242 Study Room</span>
          <span style={{ ...MONO, fontSize: 9, letterSpacing: '0.14em', color: '#8B9891' }}>INVITE · 7QK2</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: '#61726A' }}>Compare graphs with</span>
          <select
            value={partner}
            onChange={(e) => setPartner(e.target.value as Partner)}
            aria-label="Compare with"
            style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid #DCE7DE', background: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 12.5, color: '#33443B', cursor: 'pointer' }}
          >
            {PARTNERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>

        <div style={{ flex: 1, minHeight: 180, borderRadius: 12, border: '1px solid #E8E5DA', background: '#FDFCF9', position: 'relative', overflow: 'hidden' }}>
          <svg width="100%" height="100%" viewBox="0 0 420 220" preserveAspectRatio="xMidYMid meet">
            {GRAPH_EDGES.map(([a, b]) => (
              <line key={`${a}-${b}`} x1={NODE_BY_ID[a].x} y1={NODE_BY_ID[a].y} x2={NODE_BY_ID[b].x} y2={NODE_BY_ID[b].y} stroke="rgba(12,86,56,0.2)" strokeWidth="1" />
            ))}
            {GRAPH_NODES.map((n) => {
              const mineOk = RANK[n.mine as keyof typeof RANK] >= 3;
              const theirs = n.partner[partner] as keyof typeof RANK;
              const theirOk = RANK[theirs] >= 3;
              const key: keyof typeof RING = mineOk && theirOk ? 'both' : mineOk ? 'you' : theirOk ? 'them' : 'neither';
              const r = n.id === 'eig' ? 11 : 9;
              return (
                <g key={n.id}>
                  <circle cx={n.x} cy={n.y} r={r + 6} fill="none" stroke={RING[key]} strokeWidth="2" style={{ transition: 'stroke 400ms ease' }} />
                  <circle cx={n.x} cy={n.y} r={r} fill={LAB_TIER[n.mine as keyof typeof LAB_TIER]} />
                  <text x={n.x} y={n.y + r + 15} textAnchor="middle" fontFamily="DM Sans" fontSize="9" fill="#61726A">{n.name}</text>
                </g>
              );
            })}
          </svg>
        </div>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {LEGEND.map(([k, label]) => (
            <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10.5, color: '#8B9891' }}>
              <span style={{ width: 9, height: 9, borderRadius: 99, border: `2px solid ${RING[k]}` }} />
              {label}
            </span>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', background: '#F6F8F4' }}>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 9 }}>
          {msgs.map((m, i) => (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2, animation: 'labIn 260ms ease both', alignItems: m.mine ? 'flex-end' : 'flex-start' }}>
              <span style={{ ...MONO, fontSize: 8.5, letterSpacing: '0.1em', color: '#9AA5A0' }}>{m.mine ? 'you' : m.who}</span>
              <span
                style={{
                  padding: '9px 12px', borderRadius: 13, fontSize: 12.5, lineHeight: 1.5, maxWidth: 230,
                  ...(m.mine
                    ? { background: '#0C5638', color: '#F6F8F4', borderBottomRightRadius: 4 }
                    : { background: '#FDFCF9', border: '1px solid #DCE7DE', color: '#33443B', borderBottomLeftRadius: 4 }),
                }}
              >
                {m.text}
              </span>
            </div>
          ))}
          {typing && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#9AA5A0' }}>
              {partner} is typing
              {[0, 0.15, 0.3].map((d) => (
                <span key={d} style={{ width: 4, height: 4, borderRadius: 99, background: '#9AA5A0', animation: `labDot 1.2s ease-in-out ${d}s infinite` }} />
              ))}
            </span>
          )}
        </div>

        <div style={{ flex: '0 0 auto', borderTop: '1px solid #E3EBE5', padding: 10, display: 'flex', gap: 8 }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); send(); } }}
            placeholder="Message the room…"
            aria-label="Message"
            style={{ flex: 1, minWidth: 0, padding: '9px 12px', borderRadius: 9, border: '1px solid #DCE7DE', background: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 12.5, color: '#33443B', outline: 'none' }}
          />
          <button onClick={send} type="button" className="ld-labsend" style={{ padding: '9px 15px', borderRadius: 9, border: 'none', background: '#0C5638', color: '#FDFCF9', fontFamily: "'DM Sans',sans-serif", fontSize: 12.5, fontWeight: 600, cursor: 'pointer' }}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
