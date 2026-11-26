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
import { LAB_TIER } from './LabShell';
import { GRAPH_EDGES, GRAPH_NODES } from './labData';
import { cn } from "@/lib/cn";

const RING = { you: '#38bdf8', them: '#fb923c', both: '#97c855', neither: '#f87171' } as const;
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
    <div className="ld-lab-split grid grid-cols-[1fr_300px] min-h-full box-border">
      <div className="py-4.5 px-5 flex flex-col gap-2.5 border-r border-r-paper-100">
        <div className="flex items-center justify-between">
          <span className="text-base font-semibold">MA 242 Study Room</span>
          <span className="font-sans text-xs tracking-[0.01em] text-moss-400">Invite · 7QK2</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-moss-500">Compare graphs with</span>
          <select
            value={partner}
            onChange={(e) => setPartner(e.target.value as Partner)}
            aria-label="Compare with"
            className="py-[7px] px-2.5 rounded-[8px] border border-moss-100 bg-bg-panel font-sans text-[12.5px] text-moss-700 cursor-pointer"
          >
            {PARTNERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>

        <div className="flex-1 min-h-45 rounded-[12px] border border-paper-200 bg-bg-panel relative overflow-hidden">
          <svg width="100%" height="100%" viewBox="0 0 420 220" preserveAspectRatio="xMidYMid meet">
            {GRAPH_EDGES.map(([a, b]) => (
              <line key={`${a}-${b}`} x1={NODE_BY_ID[a].x} y1={NODE_BY_ID[a].y} x2={NODE_BY_ID[b].x} y2={NODE_BY_ID[b].y} stroke="rgba(68,93,34,0.2)" strokeWidth="1" />
            ))}
            {GRAPH_NODES.map((n) => {
              const mineOk = RANK[n.mine as keyof typeof RANK] >= 3;
              const theirs = n.partner[partner] as keyof typeof RANK;
              const theirOk = RANK[theirs] >= 3;
              const key: keyof typeof RING = mineOk && theirOk ? 'both' : mineOk ? 'you' : theirOk ? 'them' : 'neither';
              const r = n.id === 'eig' ? 11 : 9;
              return (
                <g key={n.id}>
                  <circle cx={n.x} cy={n.y} r={r + 6} fill="none" stroke={RING[key]} strokeWidth="2" className="[transition:stroke_400ms_ease]" />
                  <circle cx={n.x} cy={n.y} r={r} fill={LAB_TIER[n.mine as keyof typeof LAB_TIER]} />
                  <text x={n.x} y={n.y + r + 15} textAnchor="middle" className="font-sans" fontSize="9" fill="#697062">{n.name}</text>
                </g>
              );
            })}
          </svg>
        </div>

        <div className="flex gap-3 flex-wrap">
          {LEGEND.map(([k, label]) => (
            <span key={k} className="flex items-center gap-[5px] text-[10.5px] text-moss-400">
              <span className="w-[9px] h-[9px] rounded-[99px]" style={{ border: `2px solid ${RING[k]}` }} />
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="flex flex-col bg-moss-25">
        <div className="flex-1 min-h-0 overflow-auto py-4 px-3.5 flex flex-col gap-[9px]">
          {msgs.map((m, i) => (
            <div key={i} className={cn("flex flex-col gap-0.5 [animation:labIn_260ms_ease_both]", m.mine ? "items-end" : "items-start")}>
              <span className="font-sans text-2xs tracking-[0.01em] text-moss-300">{m.mine ? 'you' : m.who}</span>
              <span
                className="py-[9px] px-3 rounded-[13px] text-[12.5px] leading-[1.5] max-w-57.5" style={{ ...(m.mine
                    ? { background: '#445D22', color: '#F6F8F4', borderBottomRightRadius: 4 }
                    : { background: '#FDFCF9', border: '1px solid #E0E6DA', color: '#3B4233', borderBottomLeftRadius: 4 }) }}
              >
                {m.text}
              </span>
            </div>
          ))}
          {typing && (
            <span className="flex items-center gap-1 text-xs text-moss-300">
              {partner} is typing
              {[0, 0.15, 0.3].map((d) => (
                <span key={d} className="w-1 h-1 rounded-[99px] bg-moss-300" style={{ animation: `labDot 1.2s ease-in-out ${d}s infinite` }} />
              ))}
            </span>
          )}
        </div>

        <div className="flex-[0_0_auto] border-t border-t-moss-75 p-2.5 flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); send(); } }}
            placeholder="Message the room…"
            aria-label="Message"
            className="flex-1 min-w-0 py-[9px] px-3 rounded-[9px] border border-moss-100 bg-bg-panel font-sans text-[12.5px] text-moss-700 outline-none"
          />
          <button onClick={send} type="button" className="ld-labsend py-[9px] px-[15px] rounded-[9px] border-0 [background:#445D22] text-bg-panel font-sans text-[12.5px] font-semibold cursor-pointer">
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
