/** Inline illustrations from the Claude Design onboarding handoff. Colors come
 * from the --ob-i* tokens in onboarding.css so they follow the theme. */
import React from "react";

export function CakeArt() {
  return (
    <svg viewBox="0 0 200 150" className="ob-cake" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.4", strokeLinecap: "round", strokeLinejoin: "round" }}>
<ellipse cx="100" cy="134" rx="66" ry="8" style={{ fill: "var(--ob-i2,#2B4638)" }}></ellipse>
<rect x="52" y="84" width="96" height="48" rx="6" style={{ fill: "var(--ob-i1,#10241A)" }}></rect>
<path d="M52 98 Q62 106 72 98 Q82 106 92 98 Q102 106 112 98 Q122 106 132 98 Q142 106 148 98 L148 90 Q148 84 142 84 L58 84 Q52 84 52 90 Z" style={{ fill: "var(--ob-i3,#3E8C60)" }}></path>
<circle cx="72" cy="118" r="2.6" style={{ fill: "var(--ob-i2,#2B4638)", stroke: "none" }}></circle><circle cx="100" cy="121" r="2.6" style={{ fill: "var(--ob-i2,#2B4638)", stroke: "none" }}></circle><circle cx="128" cy="117" r="2.6" style={{ fill: "var(--ob-i2,#2B4638)", stroke: "none" }}></circle>
<path d="M100 84 L100 54"></path>
<path d="M100 66 C100 66 86 64 83 52 C83 52 97 50 100 66 Z" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></path>
<path d="M100 58 C100 58 114 52 118 40 C118 40 104 40 100 58 Z" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></path>
<path d="M58 48 L58 60 M52 54 L64 54" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path><path d="M146 40 L146 50 M141 45 L151 45" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path>
</g></svg>
  );
}

export function TourArt() {
  return (
    <svg viewBox="0 0 440 190" className="ob-tour-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}>
<rect x="40" y="36" width="104" height="132" rx="8" transform="rotate(-6 92 102)" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect>
<rect x="52" y="30" width="104" height="132" rx="8" style={{ fill: "var(--ob-i1,#10241A)" }}></rect>
<path d="M70 56 L136 56 M70 72 L128 72 M70 104 L120 104 M70 120 L132 120 M70 136 L112 136" style={{ opacity: ".6" }}></path>
<path d="M70 88 L138 88" style={{ stroke: "var(--ob-ia,#8FD9A8)", strokeWidth: "3" }}></path>
<path d="M186 100 Q222 82 258 100" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path><path d="M248 90 L259 100 L246 108" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path>
<path d="M300 60 L350 44 L396 74 M300 60 L330 104 L396 74 M330 104 L380 124 L356 160 L300 146 L330 104" style={{ strokeWidth: "1.6", opacity: ".55" }}></path>
<circle cx="300" cy="60" r="8" style={{ fill: "var(--ob-i1,#10241A)" }}></circle><circle cx="350" cy="44" r="7" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle><circle cx="396" cy="74" r="9" style={{ fill: "var(--ob-i1,#10241A)" }}></circle><circle cx="330" cy="104" r="11" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle><circle cx="380" cy="124" r="7" style={{ fill: "var(--ob-i1,#10241A)" }}></circle><circle cx="300" cy="146" r="7" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle><circle cx="356" cy="160" r="6" style={{ fill: "var(--ob-i1,#10241A)" }}></circle>
</g></svg>
  );
}

export const FEATURES: { caption: string; art: React.ReactNode }[] = [
  {
    caption: "Quizzes that meet you where you struggle.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><rect x="30" y="6" width="60" height="58" rx="7" style={{ fill: "var(--ob-i1,#10241A)" }}></rect><path d="M40 18 L76 18" style={{ opacity: ".6" }}></path><rect x="40" y="26" width="40" height="8" rx="4" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect><rect x="40" y="38" width="40" height="8" rx="4" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></rect><rect x="40" y="50" width="40" height="8" rx="4" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect><path d="M96 38 L101 43 L110 32" style={{ stroke: "var(--ob-ia,#8FD9A8)", strokeWidth: "2.8" }}></path></g></svg>,
  },
  {
    caption: "Cards that know when you'll forget.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><rect x="28" y="14" width="56" height="40" rx="6" transform="rotate(-10 56 34)" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect><rect x="34" y="16" width="56" height="40" rx="6" style={{ fill: "var(--ob-i1,#10241A)" }}></rect><path d="M44 30 L78 30 M44 40 L68 40" style={{ opacity: ".6" }}></path><circle cx="100" cy="22" r="11" style={{ fill: "var(--ob-i1,#10241A)" }}></circle><path d="M100 22 L100 15 M100 22 L105 25" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path></g></svg>,
  },
  {
    caption: "Notes that feed the graph.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><path d="M24 8 L60 8 L70 18 L70 62 L24 62 Z" style={{ fill: "var(--ob-i1,#10241A)" }}></path><path d="M60 8 L60 18 L70 18"></path><path d="M32 30 L60 30 M32 40 L56 40 M32 50 L62 50" style={{ opacity: ".6" }}></path><path d="M74 36 Q84 30 90 36" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path><path d="M96 26 L106 40 L94 50" style={{ strokeWidth: "1.6", opacity: ".55" }}></path><circle cx="96" cy="26" r="4.5" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle><circle cx="106" cy="40" r="4.5" style={{ fill: "var(--ob-i2,#2B4638)" }}></circle><circle cx="94" cy="50" r="4.5" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle></g></svg>,
  },
  {
    caption: "A study guide built from your gaps.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><path d="M60 16 Q46 8 26 11 L26 60 Q46 57 60 65 Q74 57 94 60 L94 11 Q74 8 60 16 Z" style={{ fill: "var(--ob-i1,#10241A)" }}></path><path d="M60 16 L60 65"></path><path d="M34 24 L52 27 M34 34 L52 37 M68 37 L86 34 M68 47 L86 44" style={{ opacity: ".6" }}></path><path d="M34 44 L52 47" style={{ stroke: "var(--ob-ia,#8FD9A8)", strokeWidth: "3" }}></path><path d="M68 27 L86 24" style={{ stroke: "var(--ob-ia,#8FD9A8)", strokeWidth: "3" }}></path></g></svg>,
  },
  {
    caption: "Learn next to your classmates.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><path d="M18 62 Q18 44 36 42 Q54 44 54 62" style={{ fill: "var(--ob-i4,#0A1811)" }}></path><circle cx="36" cy="28" r="11" style={{ fill: "var(--ob-i1,#10241A)" }}></circle><path d="M25 30 Q23 16 36 16 Q49 16 47 28 Q42 22 34 24 Z" style={{ fill: "var(--ob-i4,#0A1811)" }}></path><path d="M66 62 Q66 44 84 42 Q102 44 102 62" style={{ fill: "var(--ob-i3,#3E8C60)" }}></path><circle cx="84" cy="28" r="11" style={{ fill: "var(--ob-sk,#9A6A48)" }}></circle><circle cx="78" cy="17" r="4.5" style={{ fill: "var(--ob-i4,#0A1811)" }}></circle><circle cx="86" cy="15" r="4.5" style={{ fill: "var(--ob-i4,#0A1811)" }}></circle><circle cx="93" cy="19" r="4.5" style={{ fill: "var(--ob-i4,#0A1811)" }}></circle><path d="M52 14 Q60 6 68 14" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path><circle cx="60" cy="22" r="2.4" style={{ fill: "var(--ob-ia,#8FD9A8)", stroke: "none" }}></circle></g></svg>,
  },
  {
    caption: "Your real grade, always current.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><rect x="26" y="6" width="68" height="58" rx="7" style={{ fill: "var(--ob-i1,#10241A)" }}></rect><path d="M36 18 L64 18" style={{ opacity: ".6" }}></path><path d="M36 54 L50 44 L64 47 L78 32 L86 26" style={{ stroke: "var(--ob-ia,#8FD9A8)", strokeWidth: "2.8" }}></path><circle cx="50" cy="44" r="3" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle><circle cx="64" cy="47" r="3" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle><circle cx="78" cy="32" r="3" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></circle><path d="M72 18 L86 18" style={{ stroke: "var(--ob-ia,#8FD9A8)", strokeWidth: "3" }}></path></g></svg>,
  },
  {
    caption: "Paste a syllabus. Get a semester.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><rect x="16" y="14" width="34" height="46" rx="4" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect><path d="M23 26 L43 26 M23 34 L39 34 M23 42 L43 42" style={{ opacity: ".6" }}></path><path d="M54 37 L64 37 M60 32 L65 37 L60 42" style={{ stroke: "var(--ob-ia,#8FD9A8)" }}></path><rect x="68" y="12" width="40" height="50" rx="5" style={{ fill: "var(--ob-i1,#10241A)" }}></rect><path d="M68 24 L108 24 M78 8 L78 16 M98 8 L98 16"></path><rect x="74" y="30" width="8" height="7" rx="1.5" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></rect><rect x="86" y="30" width="8" height="7" rx="1.5" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect><rect x="98" y="30" width="6" height="7" rx="1.5" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect><rect x="74" y="42" width="8" height="7" rx="1.5" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect><rect x="86" y="42" width="8" height="7" rx="1.5" style={{ fill: "var(--ob-ia,#8FD9A8)" }}></rect><rect x="98" y="42" width="6" height="7" rx="1.5" style={{ fill: "var(--ob-i2,#2B4638)" }}></rect></g></svg>,
  },
  {
    caption: "It asks. You answer.",
    art: <svg viewBox="0 0 120 70" className="ob-feature-art" aria-hidden="true"><g style={{ fill: "none", stroke: "var(--ob-il,#E6F2E8)", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }}><path d="M16 12 Q16 6 22 6 L62 6 Q68 6 68 12 L68 34 Q68 40 62 40 L36 40 L26 50 L28 40 L22 40 Q16 40 16 34 Z" style={{ fill: "var(--ob-i1,#10241A)" }}></path><path d="M36 17 Q36 12 42 12 Q48 12 48 17 Q48 21 42 23 L42 27" style={{ stroke: "var(--ob-ia,#8FD9A8)", strokeWidth: "2.6" }}></path><circle cx="42" cy="33" r="1.8" style={{ fill: "var(--ob-ia,#8FD9A8)", stroke: "none" }}></circle><path d="M104 32 Q104 26 98 26 L62 26 Q56 26 56 32 L56 52 Q56 58 62 58 L86 58 L96 66 L94 58 L98 58 Q104 58 104 52 Z" style={{ fill: "var(--ob-i2,#2B4638)" }}></path><path d="M66 38 L94 38 M66 46 L86 46" style={{ opacity: ".6" }}></path></g></svg>,
  },
];
