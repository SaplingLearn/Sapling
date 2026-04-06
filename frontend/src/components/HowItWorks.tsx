'use client';

import { useRef, useState } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useMotionValueEvent,
  MotionValue,
} from 'framer-motion';

// ─── Graph data (shared by step 2 & 3) ───────────────────────────────────────

const NODES = [
  { id: 0, x: 138, y: 78,  label: 'CS 210'    },
  { id: 1, x: 205, y: 115, label: 'Arrays'    },
  { id: 2, x: 268, y: 76,  label: 'Sorting'   },
  { id: 3, x: 205, y: 58,  label: 'Loops'     },
  { id: 4, x: 138, y: 148, label: 'Functions' },
  { id: 5, x: 270, y: 152, label: 'Recursion' },
  { id: 6, x: 165, y: 192, label: 'OOP'       },
  { id: 7, x: 245, y: 196, label: 'Memory'    },
  { id: 8, x: 318, y: 115, label: 'Big-O'     },
];
const EDGES: [number, number][] = [
  [0,1],[1,2],[1,3],[0,4],[2,5],[1,5],[4,6],[5,7],[2,8],[6,7],[3,2],[4,1],
];
const MASTERY_ORDER = [0, 3, 1, 4, 2, 6]; // nodes that turn green, in order

// ─── Sapling stages ───────────────────────────────────────────────────────────

function SeedSVG({ active }: { active: boolean }) {
  // Logo paths scaled 3× from 64×64 viewBox, base anchored to soil at y=215
  // Transform: new_x = (old_x − 32) × 3 + 100,  new_y = (old_y − 54) × 3 + 215
  return (
    <svg viewBox="0 0 200 280" fill="none" className="w-full h-full">
      {/* Soil — y=215 matches sprout & tree */}
      <ellipse cx="100" cy="215" rx="72" ry="10" fill="#92683A" opacity="0.22" />
      <rect x="28" y="215" width="144" height="48" rx="5" fill="#92683A" opacity="0.09" />
      {/* Logo elements scaled to ~55% — anchor at soil (100,215) so base stays planted */}
      <g style={{ transformOrigin: '100px 215px', transform: 'scale(0.55)' }}>
        {/* Stem */}
        <motion.path d="M100 215 L100 137"
          stroke="#1a5c2a" strokeWidth="5" strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={active ? { pathLength: 1 } : { pathLength: 0 }}
          transition={{ duration: 0.55, ease: 'easeOut' }}
        />
        {/* Left leaf */}
        <motion.path d="M100 167 C100 167 58 155 52 119 C52 119 94 113 100 167 Z"
          fill="#1a5c2a"
          initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
          transition={{ duration: 0.55, delay: 0.42, ease: [0.34, 1.56, 0.64, 1] }}
          style={{ transformOrigin: '100px 167px' }}
        />
        {/* Right leaf */}
        <motion.path d="M100 143 C100 143 142 125 154 89 C154 89 112 89 100 143 Z"
          fill="#2d8a47"
          initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
          transition={{ duration: 0.55, delay: 0.58, ease: [0.34, 1.56, 0.64, 1] }}
          style={{ transformOrigin: '100px 143px' }}
        />
        {/* Tip bud */}
        <motion.circle cx="100" cy="131" r="7" fill="#1a5c2a"
          initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
          transition={{ duration: 0.38, delay: 0.32, ease: [0.34, 1.56, 0.64, 1] }}
          style={{ transformOrigin: '100px 131px' }}
        />
      </g>
    </svg>
  );
}

function SproutSVG({ active }: { active: boolean }) {
  return (
    <svg viewBox="0 0 200 280" fill="none" className="w-full h-full">
      {/* Soil — same y=215 as seed */}
      <ellipse cx="100" cy="215" rx="72" ry="10" fill="#92683A" opacity="0.22" />
      <rect x="28" y="215" width="144" height="55" rx="5" fill="#92683A" opacity="0.09" />
      {/* Roots */}
      {[
        { d: 'M100 218 Q82 232 72 248', delay: 0 },
        { d: 'M100 218 Q118 233 126 252', delay: 0.2 },
        { d: 'M100 220 Q98 236 91 252', delay: 0.4 },
      ].map((r, i) => (
        <motion.path key={i} d={r.d}
          stroke="#92683A" strokeWidth={i === 2 ? 1.5 : 2} strokeLinecap="round"
          opacity={i === 2 ? 0.35 : 0.55}
          initial={{ pathLength: 0 }}
          animate={active ? { pathLength: 1 } : { pathLength: 0 }}
          transition={{ duration: 0.7, delay: r.delay, ease: 'easeOut' }}
        />
      ))}
      {/* Stem */}
      <motion.path d="M100 215 L100 138"
        stroke="#1B6C42" strokeWidth="3.5" strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={active ? { pathLength: 1 } : { pathLength: 0 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
      />
      {/* Left leaf */}
      <motion.path d="M100 163 Q73 148 70 126 Q89 132 100 163"
        fill="#1B6C42" opacity="0.9"
        initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
        transition={{ duration: 0.55, delay: 0.5, ease: [0.34, 1.56, 0.64, 1] }}
        style={{ transformOrigin: '100px 163px' }}
      />
      {/* Right leaf */}
      <motion.path d="M100 152 Q127 136 130 114 Q111 122 100 152"
        fill="#2D8F5C" opacity="0.9"
        initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
        transition={{ duration: 0.55, delay: 0.65, ease: [0.34, 1.56, 0.64, 1] }}
        style={{ transformOrigin: '100px 152px' }}
      />
      {/* Tip bud */}
      <motion.circle cx="100" cy="136" r="5.5" fill="#3BAF6C"
        initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
        transition={{ duration: 0.4, delay: 0.4, ease: [0.34, 1.56, 0.64, 1] }}
        style={{ transformOrigin: '100px 136px' }}
      />
    </svg>
  );
}

function TreeSVG({ active }: { active: boolean }) {
  const roots = [
    { d: 'M340 358 L340 405 Q338 415 332 425',            sw: 2.5, delay: 0    },
    { d: 'M340 358 Q325 380 305 402 Q295 406 285 404',    sw: 2,   delay: 0.12 },
    { d: 'M340 358 Q355 380 375 402 Q385 406 395 403',    sw: 2,   delay: 0.14 },
    { d: 'M340 358 Q332 382 322 405',                     sw: 1.5, delay: 0.24 },
    { d: 'M340 358 Q348 382 358 404',                     sw: 1.5, delay: 0.26 },
  ];

  const stemAndBranches = [
    { d: 'M338 358 Q337 330 337 300 Q338 270 340 240 Q341 220 342 205', sw: 4.5, delay: 0.1,  color: '#5a3e28' },
    { d: 'M337 310 Q322 300 310 297',  sw: 2.5, delay: 0.38, color: '#5a3e28' },
    { d: 'M339 275 Q355 265 368 262',  sw: 2.5, delay: 0.44, color: '#5a3e28' },
    { d: 'M340 245 Q328 236 318 232',  sw: 2,   delay: 0.50, color: '#5a3e28' },
  ];

  const leaves: { cx: number; cy: number; rx: number; ry: number; rot: number; c: string; delay: number }[] = [
    { cx: 342, cy: 185, rx: 12, ry: 20, rot: 0,   c: '#3a8060', delay: 0.62 },
    { cx: 328, cy: 198, rx: 11, ry: 18, rot: -30, c: '#2d6b4f', delay: 0.66 },
    { cx: 356, cy: 198, rx: 11, ry: 18, rot: 30,  c: '#4a9470', delay: 0.66 },
    { cx: 308, cy: 226, rx: 10, ry: 17, rot: -40, c: '#3a8060', delay: 0.70 },
    { cx: 318, cy: 238, rx:  9, ry: 15, rot: 20,  c: '#2d6b4f', delay: 0.72 },
    { cx: 378, cy: 255, rx: 11, ry: 18, rot: 35,  c: '#3a8060', delay: 0.70 },
    { cx: 365, cy: 268, rx:  9, ry: 15, rot: -15, c: '#4a9470', delay: 0.73 },
    { cx: 375, cy: 248, rx: 10, ry: 16, rot: 60,  c: '#2d6b4f', delay: 0.74 },
    { cx: 300, cy: 290, rx: 11, ry: 18, rot: -35, c: '#3a8060', delay: 0.74 },
    { cx: 312, cy: 302, rx:  9, ry: 15, rot: 15,  c: '#4a9470', delay: 0.77 },
    { cx: 296, cy: 300, rx: 10, ry: 16, rot: -55, c: '#2d6b4f', delay: 0.78 },
  ];

  // Anchor soil at (100,215) matching SeedSVG/SproutSVG — user SVG soil top is at y=362, center x=340
  const treeTransform = 'translate(100,215) scale(0.72,0.55) translate(-340,-362)';

  return (
    <svg viewBox="0 0 200 280" fill="none" className="w-full h-full">
      {/* Soil — identical to SeedSVG & SproutSVG */}
      <ellipse cx="100" cy="215" rx="72" ry="10" fill="#92683A" opacity="0.22" />
      <rect x="28" y="215" width="144" height="48" rx="5" fill="#92683A" opacity="0.09" />

      <g transform={treeTransform}>
        {/* Roots */}
        {roots.map((r, i) => (
          <motion.path key={i} d={r.d}
            stroke="#9e8a70" strokeWidth={r.sw} strokeLinecap="round" fill="none"
            initial={{ pathLength: 0 }} animate={active ? { pathLength: 1 } : { pathLength: 0 }}
            transition={{ duration: 0.5, delay: r.delay, ease: 'easeOut' }}
          />
        ))}

        {/* Stem + branches */}
        {stemAndBranches.map((s, i) => (
          <motion.path key={i} d={s.d}
            stroke={s.color} strokeWidth={s.sw} strokeLinecap="round" fill="none"
            initial={{ pathLength: 0 }} animate={active ? { pathLength: 1 } : { pathLength: 0 }}
            transition={{ duration: 0.5, delay: s.delay, ease: 'easeOut' }}
          />
        ))}

        {/* Leaves */}
        {leaves.map((l, i) => (
          <motion.ellipse key={i}
            cx={l.cx} cy={l.cy} rx={l.rx} ry={l.ry}
            fill={l.c}
            transform={`rotate(${l.rot} ${l.cx} ${l.cy})`}
            initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
            transition={{ duration: 0.4, delay: l.delay, ease: [0.34, 1.56, 0.64, 1] }}
            style={{ transformOrigin: `${l.cx}px ${l.cy}px` }}
          />
        ))}

        {/* Top bud */}
        <motion.circle cx="342" cy="168" r="4" fill="#3a8060"
          initial={{ scale: 0 }} animate={active ? { scale: 1 } : { scale: 0 }}
          transition={{ duration: 0.35, delay: 0.60, ease: [0.34, 1.56, 0.64, 1] }}
          style={{ transformOrigin: '342px 168px' }}
        />
      </g>
    </svg>
  );
}

// ─── App window chrome ────────────────────────────────────────────────────────

function AppWindow({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="relative w-full rounded-2xl overflow-hidden shadow-2xl border border-black/8"
      style={{ background: 'var(--bg-panel, #f8fbf8)', aspectRatio: '4/2.8' }}
    >
      {/* Title bar */}
      <div className="flex items-center gap-1.5 px-4 h-10 border-b border-black/6"
        style={{ background: 'rgba(255,255,255,0.7)' }}>
        <div className="w-3 h-3 rounded-full bg-[#FF5F57]" />
        <div className="w-3 h-3 rounded-full bg-[#FEBC2E]" />
        <div className="w-3 h-3 rounded-full bg-[#28C840]" />
        <div className="flex-1 mx-4 rounded-full h-5 flex items-center px-3"
          style={{ background: 'rgba(0,0,0,0.05)' }}>
          <span className="text-[10px] opacity-50 font-jetbrains" style={{ color: 'var(--brand-text2)' }}>
            saplinglearn.com
          </span>
        </div>
      </div>
      {/* Content */}
      <div className="relative" style={{ height: 'calc(100% - 40px)' }}>
        {children}
      </div>
    </div>
  );
}

// ─── App screen: Step 1 ───────────────────────────────────────────────────────

const COURSE_CHIPS = ['CS 210', 'MA 242', 'SM 275'];

function Step1Content({ active }: { active: boolean }) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-8 gap-3">
      {/* Google button */}
      <motion.div
        className="w-full max-w-[230px] bg-white rounded-xl py-2.5 flex items-center justify-center gap-2.5 shadow-sm text-sm font-medium overflow-hidden relative"
        style={{ border: '1px solid rgba(0,0,0,0.1)', color: 'var(--brand-text1)' }}
        initial={{ opacity: 0, y: 12 }}
        animate={active ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
        transition={{ duration: 0.4, delay: 0.1 }}
      >
        {/* Shimmer sweep */}
        <motion.div
          className="absolute inset-0 bg-gradient-to-r from-transparent via-white/60 to-transparent -translate-x-full"
          animate={active ? { translateX: ['−100%', '200%'] } : {}}
          transition={{ duration: 0.9, delay: 0.5 }}
        />
        <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24">
          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
        </svg>
        Continue with Google
      </motion.div>

      {/* School & year */}
      {(['🎓 Boston University', '📅 Sophomore'] as const).map((label, i) => (
        <motion.div key={label}
          className="w-full max-w-[230px] rounded-xl px-3 py-2 text-xs"
          style={{ background: 'rgba(0,0,0,0.04)', border: '1px solid rgba(0,0,0,0.07)', color: 'var(--brand-text2)' }}
          initial={{ opacity: 0, y: 10 }}
          animate={active ? { opacity: 1, y: 0 } : { opacity: 0, y: 10 }}
          transition={{ duration: 0.35, delay: 0.28 + i * 0.14 }}
        >
          {label}
        </motion.div>
      ))}

      {/* Course chips */}
      <div className="flex flex-wrap gap-2 justify-center max-w-[230px]">
        {COURSE_CHIPS.map((chip, i) => (
          <motion.div key={chip}
            className="rounded-full px-3 py-1 text-xs font-medium flex items-center gap-1.5"
            style={{ background: 'rgba(27,108,66,0.1)', color: '#1B6C42' }}
            initial={{ scale: 0, opacity: 0 }}
            animate={active ? { scale: 1, opacity: 1 } : { scale: 0, opacity: 0 }}
            transition={{ duration: 0.38, delay: 0.58 + i * 0.14, ease: [0.34, 1.56, 0.64, 1] }}
          >
            <svg className="w-3 h-3" viewBox="0 0 12 12">
              <motion.path d="M2 6 L5 9 L10 3"
                stroke="#1B6C42" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none"
                initial={{ pathLength: 0 }}
                animate={active ? { pathLength: 1 } : { pathLength: 0 }}
                transition={{ duration: 0.28, delay: 0.72 + i * 0.14 }}
              />
            </svg>
            {chip}
          </motion.div>
        ))}
      </div>
    </div>
  );
}

// ─── App screen: Step 2 ───────────────────────────────────────────────────────

function Step2Content({ active, showGraph }: { active: boolean; showGraph: boolean }) {
  return (
    <div className="h-full relative">
      {/* Upload dropzone — fades out once graph is ready */}
      <motion.div
        className="absolute inset-0 flex items-center justify-center"
        initial={{ opacity: 1 }}
        animate={active && !showGraph ? { opacity: 1 } : { opacity: 0 }}
        transition={{ duration: 0.4 }}
      >
        <motion.div
          className="w-[192px] h-[128px] rounded-2xl flex flex-col items-center justify-center gap-3"
          style={{ border: '2px dashed rgba(27,108,66,0.3)', background: 'rgba(27,108,66,0.03)' }}
          animate={active ? {
            borderColor: ['rgba(27,108,66,0.3)', 'rgba(27,108,66,0.55)', 'rgba(27,108,66,0.3)'],
          } : {}}
          transition={{ duration: 2.2, repeat: Infinity, delay: 0.4 }}
        >
          {/* PDF icon drops in */}
          <motion.div
            initial={{ y: -24, opacity: 0 }}
            animate={active ? { y: 0, opacity: 1 } : { y: -24, opacity: 0 }}
            transition={{ duration: 0.5, delay: 0.25, ease: [0.34, 1.56, 0.64, 1] }}
          >
            <svg className="w-9 h-9" viewBox="0 0 36 36" fill="none">
              <rect x="4" y="2" width="22" height="30" rx="3.5" fill="#EF4444" opacity="0.92" />
              <path d="M22 2 L26 8 L22 8 Z" fill="#B91C1C" />
              <rect x="4" y="14" width="22" height="18" rx="0" fill="#DC2626" opacity="0.18" />
              <text x="15" y="24" textAnchor="middle" fill="white" fontSize="8" fontWeight="bold" fontFamily="monospace">PDF</text>
            </svg>
          </motion.div>

          <span className="text-[10px] font-jetbrains" style={{ color: 'var(--brand-text2)' }}>syllabus.pdf</span>

          {/* Progress ring */}
          <svg viewBox="0 0 28 28" className="w-7 h-7 -rotate-90">
            <circle cx="14" cy="14" r="10" fill="none" stroke="#1B6C42" strokeOpacity="0.15" strokeWidth="2.5" />
            <motion.circle cx="14" cy="14" r="10" fill="none" stroke="#1B6C42" strokeWidth="2.5"
              strokeLinecap="round"
              strokeDasharray={62.8}
              initial={{ strokeDashoffset: 62.8 }}
              animate={active ? { strokeDashoffset: 0 } : { strokeDashoffset: 62.8 }}
              transition={{ duration: 1.3, delay: 0.55, ease: 'easeInOut' }}
            />
          </svg>
        </motion.div>
      </motion.div>

      {/* Graph — only appears after user scrolls deeper into step 2 */}
      <motion.div
        className="absolute inset-0"
        initial={{ opacity: 0 }}
        animate={showGraph ? { opacity: 1 } : { opacity: 0 }}
        transition={{ duration: 0.5 }}
      >
        <svg viewBox="88 42 252 168" className="w-full h-full">
          {EDGES.map(([a, b], i) => {
            const na = NODES[a], nb = NODES[b];
            return (
              <motion.path key={i}
                d={`M ${na.x} ${na.y} L ${nb.x} ${nb.y}`}
                stroke="#1B6C42" strokeOpacity="0.22" strokeWidth="1.2"
                initial={{ pathLength: 0 }}
                animate={showGraph ? { pathLength: 1 } : { pathLength: 0 }}
                transition={{ duration: 0.4, delay: 0.15 + i * 0.07 }}
              />
            );
          })}
          {NODES.map((n, i) => (
            <g key={i}>
              <motion.circle cx={n.x} cy={n.y} r={12.5}
                fill="#1B6C42" fillOpacity="0.07"
                stroke="#1B6C42" strokeOpacity="0.28" strokeWidth="1.3"
                initial={{ scale: 0 }}
                animate={showGraph ? { scale: 1 } : { scale: 0 }}
                transition={{ duration: 0.38, delay: 0.25 + i * 0.07, ease: [0.34, 1.56, 0.64, 1] }}
                style={{ transformOrigin: `${n.x}px ${n.y}px` }}
              />
              <motion.text x={n.x} y={n.y + 1}
                textAnchor="middle" dominantBaseline="middle"
                fontSize="5.5" fill="#1B6C42" fontFamily="monospace"
                initial={{ opacity: 0 }}
                animate={showGraph ? { opacity: 0.75 } : { opacity: 0 }}
                transition={{ duration: 0.3, delay: 0.45 + i * 0.07 }}
              >
                {n.label}
              </motion.text>
            </g>
          ))}
        </svg>
      </motion.div>
    </div>
  );
}

// ─── App screen: Step 3 ───────────────────────────────────────────────────────

function Step3Content({ active }: { active: boolean }) {
  return (
    <div className="h-full relative">
      <div className="absolute inset-0 scale-[0.72] origin-center">
      <svg viewBox="88 42 252 168" className="absolute inset-0 w-full h-full">
        {/* Edges */}
        {EDGES.map(([a, b], i) => {
          const na = NODES[a], nb = NODES[b];
          return (
            <path key={i} d={`M ${na.x} ${na.y} L ${nb.x} ${nb.y}`}
              stroke="#1B6C42" strokeOpacity="0.18" strokeWidth="1.2"
            />
          );
        })}
        {/* Nodes */}
        {NODES.map((n, i) => {
          const masteryIdx = MASTERY_ORDER.indexOf(i);
          const willMaster = masteryIdx !== -1;
          return (
            <g key={i}>
              {/* Ripple burst on mastery */}
              {willMaster && (
                <motion.circle cx={n.x} cy={n.y} r={14}
                  fill="none" stroke="#1B6C42" strokeWidth="1"
                  initial={{ scale: 0, opacity: 0 }}
                  animate={active ? { scale: [0, 2.2, 0], opacity: [0.7, 0.3, 0] } : { scale: 0, opacity: 0 }}
                  transition={{ duration: 0.65, delay: 0.35 + masteryIdx * 0.22 }}
                  style={{ transformOrigin: `${n.x}px ${n.y}px` }}
                />
              )}
              <motion.circle cx={n.x} cy={n.y} r={13}
                stroke={willMaster ? '#1B6C42' : '#9CA3AF'}
                strokeWidth="1.4"
                initial={{ fill: '#9CA3AF', fillOpacity: 0.08, strokeOpacity: 0.22 }}
                animate={active && willMaster ? {
                  fill: '#1B6C42',
                  fillOpacity: [0.08, 0.3, 0.14],
                  strokeOpacity: 0.55,
                } : {}}
                transition={{ duration: 0.5, delay: 0.3 + masteryIdx * 0.22 }}
              />
              <text x={n.x} y={n.y + 1}
                textAnchor="middle" dominantBaseline="middle"
                fontSize="5.5" fontFamily="monospace"
                fill={willMaster ? '#1B6C42' : '#9CA3AF'}
                opacity={0.85}
              >
                {n.label}
              </text>
            </g>
          );
        })}
      </svg>
      </div>

      {/* Quiz card */}
      <motion.div
        className="absolute bottom-4 right-4 w-36 rounded-xl shadow-lg p-3"
        style={{ background: 'var(--bg-panel, #f8fbf8)', border: '1px solid rgba(27,108,66,0.14)' }}
        initial={{ x: 56, opacity: 0 }}
        animate={active ? { x: 0, opacity: 1 } : { x: 56, opacity: 0 }}
        transition={{ duration: 0.55, delay: 1.6, ease: [0.34, 1.56, 0.64, 1] }}
      >
        <p className="text-[9px] leading-snug mb-2.5" style={{ color: 'var(--brand-text2)' }}>
          Time complexity of binary search?
        </p>
        <div className="flex flex-col gap-1">
          {['O(n)', 'O(log n)', 'O(n²)'].map((opt, i) => (
            <div key={opt}
              className="rounded-lg px-2 py-1 text-[9px] font-medium"
              style={i === 1
                ? { background: 'rgba(27,108,66,0.12)', color: '#1B6C42' }
                : { background: 'rgba(0,0,0,0.04)', color: 'var(--brand-text2)' }
              }
            >
              {i === 1 && '✓ '}{opt}
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}

// ─── Step indicator (vertical) ────────────────────────────────────────────────

function StepIndicator({ scrollYProgress, activeStep }: {
  scrollYProgress: MotionValue<number>;
  activeStep: number;
}) {
  const bar1H = useTransform(scrollYProgress, [0, 0.38], ['0%', '100%']);
  const bar2H = useTransform(scrollYProgress, [0.38, 0.72], ['0%', '100%']);

  return (
    <div className="absolute right-5 lg:right-8 top-1/2 -translate-y-1/2 flex flex-col items-center gap-2 z-20 hidden sm:flex">
      {[1, 2, 3].map((s, i) => (
        <div key={s} className="flex flex-col items-center gap-2">
          <motion.div
            className="w-2 h-2 rounded-full"
            style={{ background: activeStep >= s ? '#1B6C42' : 'rgba(156,163,175,0.4)' }}
            animate={{ scale: activeStep === s ? 1.4 : 1 }}
            transition={{ duration: 0.3 }}
          />
          {i < 2 && (
            <div className="w-px h-9 overflow-hidden" style={{ background: 'rgba(156,163,175,0.2)' }}>
              <motion.div className="w-full" style={{
                height: i === 0 ? bar1H : bar2H,
                background: '#1B6C42',
              }} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Main export ──────────────────────────────────────────────────────────────

const STEPS = [
  {
    num: '01',
    title: 'Sign Up & Add Courses',
    desc: 'Connect with Google in one click. Tell us your school and year. Add your classes. Takes 30 seconds.',
  },
  {
    num: '02',
    title: 'Upload Your Materials',
    desc: 'Drop in a syllabus, textbook PDF, or lecture notes. Our AI reads everything, extracts concepts, and builds your knowledge map instantly.',
  },
  {
    num: '03',
    title: 'Start Growing',
    desc: 'Follow your personalized learning path. Take adaptive quizzes. Watch your knowledge graph come alive, node by node turning green.',
  },
];

// scroll input ranges (matching the non-overlapping windows we tuned)
const TEXT_RANGES = [
  { in: [0, 0.05, 0.28, 0.38], yIn: [30, 0, 0, -30] },
  { in: [0.38, 0.48, 0.62, 0.72], yIn: [30, 0, 0, -30] },
  { in: [0.72, 0.82, 1, 1], yIn: [30, 0, 0, 0] },
];

const BG_COLORS = [
  'rgba(0,0,0,0)',
  'rgba(120,53,15,0.035)',
  'rgba(20,83,45,0.05)',
  'rgba(20,83,45,0.08)',
];

export default function HowItWorks() {
  const containerRef = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ['start start', 'end end'],
  });

  const [activeStep, setActiveStep] = useState(1);
  const [showStep2Graph, setShowStep2Graph] = useState(false);
  useMotionValueEvent(scrollYProgress, 'change', (v) => {
    setActiveStep(v < 0.38 ? 1 : v < 0.72 ? 2 : 3);
    setShowStep2Graph(v > 0.55);
  });

  // Text
  const textOpacities = TEXT_RANGES.map(r => useTransform(scrollYProgress, r.in, [0, 1, 1, 0])); // eslint-disable-line react-hooks/rules-of-hooks
  const textYs = TEXT_RANGES.map(r => useTransform(scrollYProgress, r.in, r.yIn)); // eslint-disable-line react-hooks/rules-of-hooks

  const panelOpacity = useTransform(scrollYProgress, [0, 0.05, 0.82, 1], [0, 1, 1, 0]);

  // Background
  const bgColor = useTransform(scrollYProgress, [0, 0.38, 0.72, 1], BG_COLORS);

  const SaplingComponents = [SeedSVG, SproutSVG, TreeSVG];

  return (
    <section ref={containerRef} id="how-it-works" className="landing-section relative" style={{ height: '510vh' }}>
      <motion.div className="sticky top-0 h-screen w-full overflow-hidden" style={{ backgroundColor: bgColor }}>
        <div className="h-full max-w-[1600px] mx-auto px-9 lg:px-[72px] flex flex-col lg:flex-row items-center gap-12 lg:gap-32 pt-16 lg:pt-0 lg:-translate-y-20">

          {/* ── Left: Sapling + text ──────────────────────────────────── */}
          <div className="flex-1 flex flex-col items-center lg:items-start justify-center h-full py-8 lg:py-0 lg:-ml-8 lg:translate-y-16">
            {/* Sapling illustration */}
            <motion.div className="relative w-56 h-72 lg:w-64 lg:h-80 mb-12 lg:mb-[60px] flex-shrink-0" style={{ opacity: panelOpacity }}>
              {SaplingComponents.map((SVG, i) => (
                <motion.div key={i} className="absolute inset-0"
                  animate={{ opacity: activeStep === i + 1 ? 1 : 0 }}
                  transition={{ duration: 0.35 }}
                >
                  <SVG active={activeStep === i + 1} />
                </motion.div>
              ))}
            </motion.div>

            {/* Step text layers */}
            <div className="relative w-full max-w-[600px] lg:max-w-2xl" style={{ minHeight: 240 }}>
              {STEPS.map((step, i) => (
                <motion.div
                  key={i}
                  className="absolute inset-x-0 top-0 text-center lg:text-left"
                  style={{ opacity: textOpacities[i], y: textYs[i] }}
                >
                  <span className="font-jetbrains text-[15px] tracking-[0.3em] text-[#1B6C42] uppercase mb-[15px] block font-medium">
                    Step {step.num}
                  </span>
                  <h3 className="font-playfair text-[38px] lg:text-[45px] font-semibold tracking-tight leading-tight mb-5"
                    style={{ color: 'var(--brand-text1)' }}>
                    {step.title}
                  </h3>
                  <p className="font-inter text-xl leading-relaxed font-light"
                    style={{ color: 'var(--brand-text2)' }}>
                    {step.desc}
                  </p>
                </motion.div>
              ))}
            </div>
          </div>

          {/* ── Right: App window ─────────────────────────────────────── */}
          <motion.div className="flex-[1.68] w-full max-w-2xl lg:max-w-none flex-shrink-0 lg:translate-y-28" style={{ opacity: panelOpacity }}>
            <AppWindow>
              {([
                <Step1Content key={0} active={activeStep === 1} />,
                <Step2Content key={1} active={activeStep === 2} showGraph={showStep2Graph} />,
                <Step3Content key={2} active={activeStep === 3} />,
              ] as const).map((el, i) => (
                <motion.div key={i} className="absolute inset-0"
                  animate={{ opacity: activeStep === i + 1 ? 1 : 0 }}
                  transition={{ duration: 0.35 }}
                >
                  <motion.div
                    className="h-full origin-center"
                    animate={{ scale: i === 0 ? 1.18 : i === 1 ? (showStep2Graph ? 0.72 : 1.18) : 1 }}
                    transition={{ duration: 0.4 }}
                  >
                    {el}
                  </motion.div>
                </motion.div>
              ))}
            </AppWindow>
          </motion.div>
        </div>

        {/* Step indicator */}
        <StepIndicator scrollYProgress={scrollYProgress} activeStep={activeStep} />
      </motion.div>
    </section>
  );
}
