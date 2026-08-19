"use client";
import React from "react";
import type { RarityTier } from "@/lib/types";
import { discFor } from "./levels";

// Built-in icon art, keyed by slug. Each entry is the inner SVG for a
// 48-unit viewBox; `c` is the main fill and `l` the secondary. Ported
// verbatim from the design's iconPaths() (Achievements.dc.html, line ~875).
// Slugs with no entry fall through to the emoji.
const ICON_PATHS: Record<string, (c: string, l: string) => string> = {
  "first-steps": (c, l) => `<rect x="22.4" y="19" width="3.2" height="21" rx="1.6" fill="${c}"/><path d="M24 30c-2-8-9-11-16-10 0 8 7 12 16 10Z" fill="${l}"/><path d="M24 26c2-9 9-12 16-11 0 8-7 12-16 11Z" fill="${c}"/><circle cx="24" cy="17.5" r="2.8" fill="${c}"/>`,
  "flash": (c, l) => `<rect x="8" y="14" width="20" height="26" rx="3" fill="${l}"/><rect x="18" y="9" width="21" height="27" rx="3" fill="${c}"/><path d="M31 14l-8 11h5l-4 9 9-12h-5z" fill="${l}"/>`,
  "bookworm": (c, l) => `<rect x="10" y="30" width="27" height="7" rx="1.6" fill="${c}"/><rect x="13" y="22.5" width="23" height="7" rx="1.6" fill="${l}"/><rect x="11.5" y="15" width="25" height="7" rx="1.6" fill="${c}"/><rect x="29" y="15" width="3.4" height="10" fill="${l}"/>`,
  "on-fire": (c, l) => `<path d="M24 6c5 6-1 11-1 15 0 3 2 4 4 3 2-1 2-4 1-7 5 3 8 8 8 13a12 12 0 0 1-24 0c0-6 4-9 6-13 2-4 4-6 3-11Z" fill="${c}"/><path d="M24 40a6 6 0 0 0 3-11c0 3-2 4-3 3-1 3-4 2-4 0-2 2-2 3-2 4a6 6 0 0 0 6 4Z" fill="${l}"/>`,
  "early-bird": (c, l) => `<rect x="7" y="31" width="34" height="3.4" rx="1.7" fill="${c}"/><path d="M13 31a11 11 0 0 1 22 0Z" fill="${c}"/><g fill="${l}"><rect x="22.4" y="8" width="3.2" height="7" rx="1.6"/><rect x="10" y="15" width="3.2" height="7" rx="1.6" transform="rotate(-42 11.6 18.5)"/><rect x="34.8" y="15" width="3.2" height="7" rx="1.6" transform="rotate(42 36.4 18.5)"/></g>`,
  "night-owl": (c, l) => `<path d="M32 11a13.5 13.5 0 1 0 7 21A11 11 0 0 1 32 11Z" fill="${c}"/><path d="M15.5 12l1.9 3.9 4.3.6-3.1 3 .7 4.3-3.8-2-3.8 2 .7-4.3-3.1-3 4.3-.6z" fill="${l}"/>`,
  "deep-focus": (c, l) => `<rect x="14" y="8" width="20" height="3.4" rx="1.7" fill="${c}"/><rect x="14" y="36.6" width="20" height="3.4" rx="1.7" fill="${c}"/><path d="M17 11.4h14c0 7-6 8.5-6 12.6 0 4.1 6 5.6 6 12.6H17c0-7 6-8.5 6-12.6 0-4.1-6-5.6-6-12.6Z" fill="${l}"/><path d="M24 25c-3 1-4.5 3.2-4.5 6.4h9c0-3.2-1.5-5.4-4.5-6.4Z" fill="${c}"/><path d="M21.5 12.5h5v2.6L24 18l-2.5-2.9z" fill="${c}"/>`,
  "quiz-master": (c, l) => `<path d="M19.5 8h9v2.4h-1.3v7.4l7.2 15.4a3 3 0 0 1-2.7 4.3H16.3a3 3 0 0 1-2.7-4.3l7.2-15.4V10.4H19.5z" fill="${c}"/><path d="M18 27.5h12l3.4 7.2a2 2 0 0 1-1.8 2.9H16.4a2 2 0 0 1-1.8-2.9z" fill="${l}"/><circle cx="21" cy="31.5" r="1.6" fill="${c}"/><circle cx="27" cy="33.5" r="1.2" fill="${c}"/>`,
  "marathon": (c, l) => `<path d="M24 7l7.5 11h-4.2l5.5 8.5h-4l5.5 8.5H17.7l5.5-8.5h-4l5.5-8.5h-4.2z" fill="${c}"/><rect x="22.2" y="34" width="3.6" height="6" rx="1" fill="${l}"/>`,
  "wildfire": () => `<g fill="#5a3a24"><path d="M12.5 12.6h1.7v27.9h-1.7z"/><path d="M13.4 20.4l-4.2-3.6M13.4 26.4l4.4-3.8" stroke="#5a3a24" stroke-width="1.3" stroke-linecap="round"/><path d="M19.3 8.4H21v32.1h-1.7z"/><path d="M20.2 15.4l-4.8-3.8M20.2 21.4l5.2-4.2M20.2 28l-4.6-3.6" stroke="#5a3a24" stroke-width="1.3" stroke-linecap="round"/></g><g fill="#3f7f43"><path d="M32.4 33.4h1.9v7.1h-1.9z"/><path d="M33.4 9.4l7.6 12.6H25.8zM33.4 17.4l8.6 13.1H24.8zM33.4 25.4l9.6 14.1H23.8z"/></g><g fill="#4f9450"><path d="M40.6 31h1.7v9.5h-1.7z"/><path d="M41.4 21.4l5.6 9.2H35.8zM41.4 28.4l6.6 10.6H34.8z"/></g><path d="M24.6 14.6c4.2 6.2-.6 9.8 1 13.9 1.4-2 3.5-2 4.1.5 1.2 5.2-2.8 8.9-3.4 11.5H13.4c-2-6.1 2.5-8.6 4-13.2 1.6 3.1 3.7 2.5 3.5-1.4-.2-4.1 1.1-6.8 2.2-9.9zM34.9 23.4c3.1 5.1 5.6 8.2 5.6 12.3 0 1.9-.9 3.4-2 4.7h-8.6c3.1-4.1 3.6-9.2 5-17zM12.9 28.9c1.7 2.5 2.5 4.5 2.5 7.2 0 1.6-.6 3.1-1.4 4.4H8.3c1.9-3.1 3.2-6.9 4.6-11.6z" fill="#e8622a"/><path d="M24.1 21.6c2.7 4.1-.4 6.8.8 9.9 1-1.6 2.5-1.4 2.9.4.9 4.5-2.6 6.9-3.3 8.6h-6.9c-1.4-4.1 1.7-6.2 2.7-9.3 1.2 2.3 2.7 1.6 2.5-1-.2-2.7.2-4.7.6-7.2zM37.4 30.2c1.6 2.6 2.6 4.7 2.6 6.9 0 1.3-.5 2.5-1.1 3.4h-4.4c1.4-2.7 2.2-6 2.9-10.3z" fill="#f7a325"/><path d="M24.3 29.6c1.7 2.7.4 4.5 1 6.4.6-1 1.6-.8 1.8.3.4 1.8-1 3.1-1.4 4.2h-4.5c-.8-2.5 1-3.5 1.7-5.4.7 1.5 1.5 1 1.4-.6z" fill="#fde9a0"/><path d="M5.6 40.5c1.4-2.4 3.8-2.9 6.2-1.9 2.5-1.9 4.6-1.6 6.5.6 2.3-2.4 4.6-2.4 6.9-.2 2.2-2.3 4.4-2.4 6.6-.4 2.4-2 4.7-1.8 6.9.5 2.1-1.4 4.1-1 5.7 1.4z" fill="#e8622a"/><path d="M8 40.5c1.2-1.6 2.9-1.9 4.7-1.1 1.9-1.3 3.6-1 5 .8 1.8-1.6 3.6-1.6 5.3.1 1.7-1.5 3.4-1.5 5.1.1 1.9-1.4 3.7-1.1 5.4.7 1.6-.9 3.1-.5 4.4 1z" fill="#f7a325"/><path d="M13.6 40.5c1-1.1 2.3-1.2 3.7-.4 1.5-.9 2.8-.6 3.9.6 1.4-1 2.7-1 4 .1 1.4-.9 2.7-.7 3.9.5z" fill="#fde9a0"/>`,
  "first-friend": (c, l) => `<path d="M10 21.4Q15 17.9 20 21.4L23.4 30.4 24 31.9 21.5 32.6 20 29.6V40.6H10V29.6L8.5 32.6 6 31.9 6.6 30.4Z" fill="${c}"/><circle cx="15" cy="13.4" r="5.2" fill="${c}"/><path d="M28 21.4Q33 17.9 38 21.4L41.4 30.4 42 31.9 39.5 32.6 38 29.6V40.6H28V29.6L26.5 32.6 24 31.9 24.6 30.4Z" fill="${l}"/><circle cx="33" cy="13.4" r="5.2" fill="${l}"/><g stroke="#2D8F5C" stroke-width="1.5" stroke-linecap="round" fill="none"><path d="M15 8.2V5"/><path d="M33 8.2V5"/></g><g fill="#2D8F5C"><path d="M15 5.9c0-2.4-1.5-4-4.1-4.3 0 2.4 1.5 4 4.1 4.3z"/><path d="M33 5.9c0-2.4-1.5-4-4.1-4.3 0 2.4 1.5 4 4.1 4.3z"/></g><g fill="#8FD9A8"><path d="M15 5.9c0-2.1 1.3-3.5 3.4-3.7 0 2-1.3 3.5-3.4 3.7z"/><path d="M33 5.9c0-2.1 1.3-3.5 3.4-3.7 0 2-1.3 3.5-3.4 3.7z"/></g>`,
  "study-circle": (c, l) => `<circle cx="24" cy="24" r="12" fill="none" stroke="${l}" stroke-width="2.2" opacity=".55"/><circle cx="24" cy="11.5" r="4" fill="${l}"/><circle cx="36.5" cy="24" r="4" fill="${l}"/><circle cx="24" cy="36.5" r="4" fill="${l}"/><circle cx="11.5" cy="24" r="4" fill="${l}"/><circle cx="24" cy="24" r="6" fill="${c}"/>`,
  "helping-hand": (c, l) => `<path d="M12 39c-2.2-1-3.5-3.2-3.5-6.5V25c0-1.7 2.6-1.7 2.6 0v-2.2c0-1.7 2.6-1.7 2.6 0 0-1.7 2.6-1.7 2.6 0v1.7c0-1.7 2.6-1.7 2.6 0V32c0 4.8-3.2 7-8 7z" fill="${c}"/><path d="M33 9c-8 1-11 6-11 12 6.5 0 11-4.5 11-12Z" fill="${l}"/>`,
  "room-leader": (c, l) => `<path d="M13 34l-2.5-12.5 6.5 4.5L24 16l7 10 6.5-4.5L35 34z" fill="${c}"/><rect x="12.5" y="34" width="23" height="3.4" rx="1.5" fill="${l}"/><circle cx="24" cy="14.5" r="4.6" fill="${l}"/>`,
  "popular": (c, l) => `<path d="M12 16l11 6 9-8 6 13-14 4z" fill="none" stroke="${l}" stroke-width="1.8" opacity=".55" stroke-linejoin="round"/><circle cx="12" cy="16" r="3.6" fill="${c}"/><circle cx="24" cy="22" r="4.8" fill="${l}"/><circle cx="32" cy="13" r="3.6" fill="${c}"/><circle cx="38" cy="26" r="3.6" fill="${c}"/><circle cx="24" cy="30" r="3.6" fill="${c}"/>`,
  "mentor": (c, l) => `<g fill="${l}"><ellipse cx="13" cy="20" rx="3.4" ry="2" transform="rotate(-45 13 20)"/><ellipse cx="12.4" cy="26" rx="3.4" ry="2" transform="rotate(-22 12.4 26)"/><ellipse cx="14" cy="32" rx="3.4" ry="2" transform="rotate(8 14 32)"/><ellipse cx="35" cy="20" rx="3.4" ry="2" transform="rotate(45 35 20)"/><ellipse cx="35.6" cy="26" rx="3.4" ry="2" transform="rotate(22 35.6 26)"/><ellipse cx="34" cy="32" rx="3.4" ry="2" transform="rotate(-8 34 32)"/></g><path d="M24 14l2.6 5.3 5.8.8-4.2 4.1 1 5.8L24 33l-5.2 2.8 1-5.8-4.2-4.1 5.8-.8z" fill="${c}"/>`,
  "social-butterfly": (c, l) => `<ellipse cx="15.5" cy="18" rx="7.5" ry="5.2" fill="${l}"/><ellipse cx="32.5" cy="18" rx="7.5" ry="5.2" fill="${l}"/><ellipse cx="17" cy="28.5" rx="5.4" ry="4.2" fill="${c}"/><ellipse cx="31" cy="28.5" rx="5.4" ry="4.2" fill="${c}"/><rect x="22.6" y="14" width="2.8" height="20" rx="1.4" fill="${c}"/><path d="M24 14c-1.5-3-4-4-4-4M24 14c1.5-3 4-4 4-4" stroke="${c}" stroke-width="1.8" stroke-linecap="round"/>`,
  "sprout": (c, l) => `<rect x="22.4" y="22" width="3.2" height="18" rx="1.6" fill="${c}"/><path d="M24 29c-2-8-9-11-15-10 0 8 6 12 15 10Z" fill="${c}"/><path d="M24 25c2-8 9-11 15-10 0 8-6 12-15 10Z" fill="${l}"/><rect x="17" y="38" width="14" height="3.2" rx="1.6" fill="${l}"/>`,
  "rooted": (c, l) => `<rect x="22.6" y="9" width="2.8" height="9" rx="1.4" fill="${l}"/><path d="M24 12.5c-2.8-1-4.6-2.8-4.6-5.6 2.8 0 4.6 1.9 4.6 5.6zM24 12.5c2.8-1 4.6-2.8 4.6-5.6-2.8 0-4.6 1.9-4.6 5.6z" fill="${l}"/><rect x="11" y="17.5" width="26" height="3" rx="1.5" fill="${l}"/><g stroke="${c}" fill="none" stroke-linecap="round"><path d="M24 20.5v5.5" stroke-width="3"/><path d="M24 25c-1.8 2-3.8 2.6-4.9 5.8-.6 1.7-.8 3.2-.9 4.9" stroke-width="2.3"/><path d="M24 25c1.8 2 3.8 2.6 4.9 5.8.6 1.7.8 3.2.9 4.9" stroke-width="2.3"/><path d="M23.9 29c-.7 1.9-2 2.9-2.5 5.6" stroke-width="1.5"/><path d="M24.1 29c.7 1.9 2 2.9 2.5 5.6" stroke-width="1.5"/><path d="M24 31.5v6" stroke-width="1.8"/></g><g fill="${c}"><circle cx="18" cy="36.2" r="1.4"/><circle cx="30" cy="36.2" r="1.4"/><circle cx="24" cy="38.2" r="1.4"/><circle cx="21.2" cy="35" r="1.1"/><circle cx="26.8" cy="35" r="1.1"/></g>`,
  "grade-a": (c, l) => `<path d="M11 8h18l8 8v24a2 2 0 0 1-2 2H13a2 2 0 0 1-2-2z" fill="${l}"/><path d="M29 8l8 8h-8z" fill="${c}" opacity=".55"/><g stroke="${c}" stroke-width="1.6" stroke-linecap="round" opacity=".5"><path d="M16 22h9M16 27h13M16 32h11"/></g><g fill="none" stroke="#d33a2c" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M19.5 36.5l5.3-14.6 5.9 14.2"/><path d="M21.4 31.4c3.4-1.4 5.6-1.2 8 .3"/></g>`,
  "branching": (c, l) => `<rect x="22.2" y="18" width="3.6" height="22" rx="1.5" fill="${c}"/><rect x="24" y="23" width="10" height="3" rx="1.5" transform="rotate(-40 24 24.5)" fill="${c}"/><rect x="14" y="20" width="10" height="3" rx="1.5" transform="rotate(40 24 21.5)" fill="${c}"/><circle cx="15" cy="18" r="5.4" fill="${l}"/><circle cx="33" cy="15" r="5.4" fill="${l}"/><circle cx="24" cy="11" r="5.8" fill="${l}"/>`,
  "rings": (c, l) => `<circle cx="24" cy="24" r="15" fill="${c}"/><circle cx="24" cy="24" r="11.5" fill="${l}"/><circle cx="24" cy="24" r="8" fill="${c}"/><circle cx="24" cy="24" r="4.5" fill="${l}"/><circle cx="24" cy="24" r="1.8" fill="${c}"/>`,
  "web": (c, l) => `<path d="M14 14l10 8 11-6M14 14l4 18 6-10M24 22l11 12-17-2" fill="none" stroke="${l}" stroke-width="1.8" opacity=".55" stroke-linejoin="round"/><circle cx="14" cy="14" r="3.6" fill="${c}"/><circle cx="35" cy="16" r="3.6" fill="${c}"/><circle cx="24" cy="22" r="4.8" fill="${l}"/><circle cx="18" cy="32" r="3.6" fill="${c}"/><circle cx="35" cy="34" r="3.6" fill="${c}"/>`,
  "canopy": (c, l) => `<rect x="22.6" y="20" width="2.8" height="20" rx="1.4" fill="${c}"/><g stroke="${c}" stroke-width="1.8" stroke-linecap="round" fill="none"><path d="M24 26l-7-4.5M24 30l7-4.5"/></g><path d="M24 8.5c9.6 0 16.8 4.6 18.4 10.4-2 .3-3.4-.4-4.4-1.9-.6 2-1.9 3-4 3-1.9 0-3.2-.9-3.9-2.6-.9 2.2-2.9 3.3-6.1 3.3s-5.2-1.1-6.1-3.3c-.7 1.7-2 2.6-3.9 2.6-2.1 0-3.4-1-4-3-1 1.5-2.4 2.2-4.4 1.9C7.2 13.1 14.4 8.5 24 8.5z" fill="${l}"/><ellipse cx="17" cy="12.4" rx="4.6" ry="2.2" fill="${c}" opacity=".26"/><rect x="15" y="38.4" width="18" height="3" rx="1.5" fill="${c}"/>`,
  "old-growth": (c, l) => `<rect x="21" y="25" width="6" height="16" rx="1.5" fill="${c}"/><circle cx="24" cy="17" r="14" fill="${l}"/><circle cx="17" cy="14" r="6.5" fill="${l}"/><circle cx="31" cy="14" r="6.5" fill="${l}"/><ellipse cx="20" cy="12" rx="4.5" ry="3.2" fill="${c}" opacity=".28"/><path d="M17 41c0-3.5 3-5.5 7-5.5s7 2 7 5.5z" fill="${c}"/>`,
  "methuselah": (c, l) => `<g fill="${c}" stroke="${c}" stroke-width="2" stroke-linejoin="round"><path d="M16.2 42c1.6-4.8 3-8 3.8-11.1.9-3.2 1.1-6 .6-8.9l5.4-.4c-.2 3.6.4 7 1.7 10.4 1.3 3.5 2.1 6.8 2.5 10z"/><path d="M20.8 23.4c-.7-4.6-.2-9 1.5-13.2.7-1.7 1.6-3.2 2.8-4.4-.4 1.9-1.2 3.6-2 5.1 1.4-.8 2.7-.6 3.8.5-1.7.2-3 1-3.8 2.5-.9 3.3-.9 6.6-.3 9.9z"/><path d="M25.2 22.6c1.7-3.6 4-6.5 7-8.8 1.3-1 2.6-1.8 3.9-2.4-.9 1.7-2.1 3-3.6 4 1.5-.2 2.8.2 3.7 1.3-1.9 0-3.4.6-4.7 1.9-2.1 1.3-3.8 3-4.9 4.9z"/><path d="M20.4 26.2c-2.9-1.7-5.9-2.7-9-2.9-1.5-.1-2.8 0-3.9.4 1.3-1.3 2.8-2 4.5-2.2-1.5-.9-2.6-2-3.2-3.5 2.3.9 4.4 2.2 6.3 3.9 1.9 1.5 3.6 2.8 4.9 3.7z"/><path d="M27.4 31c2.3-.9 4.4-.4 6.3 1.1-1.5.2-2.8.7-3.8 1.5 1 .5 1.8 1.1 2.4 2-2.1-.7-3.8-2.2-5.1-3.9z"/><path d="M20 33.8c-1.7-.6-3.4-.4-5.1.5 1 .4 1.9.6 2.7.6-.9.6-1.5 1.3-1.9 2.2 1.7-.6 3.2-1.7 4.3-2.8z"/></g><g fill="${l}"><path d="M16.2 42c1.6-4.8 3-8 3.8-11.1.9-3.2 1.1-6 .6-8.9l5.4-.4c-.2 3.6.4 7 1.7 10.4 1.3 3.5 2.1 6.8 2.5 10z"/><path d="M20.8 23.4c-.7-4.6-.2-9 1.5-13.2.7-1.7 1.6-3.2 2.8-4.4-.4 1.9-1.2 3.6-2 5.1 1.4-.8 2.7-.6 3.8.5-1.7.2-3 1-3.8 2.5-.9 3.3-.9 6.6-.3 9.9z"/><path d="M25.2 22.6c1.7-3.6 4-6.5 7-8.8 1.3-1 2.6-1.8 3.9-2.4-.9 1.7-2.1 3-3.6 4 1.5-.2 2.8.2 3.7 1.3-1.9 0-3.4.6-4.7 1.9-2.1 1.3-3.8 3-4.9 4.9z"/><path d="M20.4 26.2c-2.9-1.7-5.9-2.7-9-2.9-1.5-.1-2.8 0-3.9.4 1.3-1.3 2.8-2 4.5-2.2-1.5-.9-2.6-2-3.2-3.5 2.3.9 4.4 2.2 6.3 3.9 1.9 1.5 3.6 2.8 4.9 3.7z"/><path d="M27.4 31c2.3-.9 4.4-.4 6.3 1.1-1.5.2-2.8.7-3.8 1.5 1 .5 1.8 1.1 2.4 2-2.1-.7-3.8-2.2-5.1-3.9z"/><path d="M20 33.8c-1.7-.6-3.4-.4-5.1.5 1 .4 1.9.6 2.7.6-.9.6-1.5 1.3-1.9 2.2 1.7-.6 3.2-1.7 4.3-2.8z"/></g><g stroke="${c}" stroke-width="1.1" stroke-linecap="round" fill="none" opacity=".8"><path d="M21.8 40.6c.7-3.6 1.5-6.4 2.1-8.4.6-2.2.8-4.3.6-6.4"/><path d="M19.4 31.4c2 .7 4 .9 6 .4M18.8 38.4c2.7.9 5.5 1 8.2.3"/><path d="M22.2 19.4c-.2-2.8.3-5.4 1.4-7.8M27.4 20c1.5-2.4 3.3-4.3 5.5-5.9"/></g><path d="M11 42c2.6-2.4 5.6-3.7 9-3.9l1.6-1.6h4.8l1.6 1.6c3.4.2 6.4 1.5 9 3.9z" fill="${c}"/><path d="M14.8 42c2-1.4 4.2-2.2 6.6-2.4l1.4-1.4h2.4l1.4 1.4c2.4.2 4.6 1 6.6 2.4z" fill="${l}"/>`,
  "perfect-week": () => `<rect x="8" y="11" width="32" height="30" rx="4" fill="#f4f1e8"/><rect x="8" y="11" width="32" height="9" rx="4" fill="#c8352a"/><rect x="8" y="17" width="32" height="3" fill="#c8352a"/><g fill="#a8281f"><rect x="14" y="7" width="3.4" height="8" rx="1.7"/><rect x="30.6" y="7" width="3.4" height="8" rx="1.7"/></g><path d="M18.5 24.5h11l-5.6 12h-4.5l4.6-7.9H18.5z" fill="#22201c"/>`,
  "comeback": (c, l) => `<path d="M16 40V30c0-1.4 1-2.4 2.4-2.4h11.2c1.4 0 2.4 1 2.4 2.4v10z" fill="${c}"/><ellipse cx="24" cy="28.5" rx="8.5" ry="2.6" fill="${l}"/><ellipse cx="24" cy="28.5" rx="4" ry="1.2" fill="${c}"/><rect x="22.4" y="15" width="3.2" height="14" rx="1.6" fill="${c}"/><path d="M24 20c5-1 8-4.5 8-9-5.5 0-8.5 3.5-8 9Z" fill="${l}"/>`,
  "polymath": (c, l) => `<g fill="${l}"><ellipse cx="24" cy="13" rx="4.2" ry="8.5"/><ellipse cx="24" cy="13" rx="4.2" ry="8.5" transform="rotate(72 24 24)"/><ellipse cx="24" cy="13" rx="4.2" ry="8.5" transform="rotate(144 24 24)"/><ellipse cx="24" cy="13" rx="4.2" ry="8.5" transform="rotate(216 24 24)"/><ellipse cx="24" cy="13" rx="4.2" ry="8.5" transform="rotate(288 24 24)"/></g><circle cx="24" cy="24" r="4.2" fill="${c}"/>`,
  "golden-hour": (c, l) => `<circle cx="24" cy="24" r="9" fill="${c}"/><g fill="${l}"><rect x="22.4" y="6" width="3.2" height="6.5" rx="1.6"/><rect x="22.4" y="35.5" width="3.2" height="6.5" rx="1.6"/><rect x="6" y="22.4" width="6.5" height="3.2" rx="1.6"/><rect x="35.5" y="22.4" width="6.5" height="3.2" rx="1.6"/><rect x="10.5" y="10.5" width="3.2" height="6.5" rx="1.6" transform="rotate(-45 12.1 13.7)"/><rect x="34.3" y="31" width="3.2" height="6.5" rx="1.6" transform="rotate(-45 35.9 34.2)"/><rect x="34.3" y="10.5" width="3.2" height="6.5" rx="1.6" transform="rotate(45 35.9 13.7)"/><rect x="10.5" y="31" width="3.2" height="6.5" rx="1.6" transform="rotate(45 12.1 34.2)"/></g>`,
  "secret": (c, l) => `<circle cx="24" cy="24" r="13.5" fill="${c}"/><path d="M19.5 20c0-3 2-5.2 4.8-5.2s4.8 2 4.8 4.8c0 2.6-2.6 3.6-3.8 5.2-.6.8-.8 1.7-.8 2.8h-3.2c0-1.7.3-3.1 1.6-4.2 1.1-1 2.6-1.7 2.6-3.4 0-1.3-1-2.2-2.6-2.2s-2.6 1-2.6 2.4z" fill="${l}"/><circle cx="24" cy="31.5" r="1.9" fill="${l}"/>`,
};

// Per-icon colours [main, shade], verbatim from the design's iconColor()
// (Achievements.dc.html, line ~928). Unlocked hex only — the locked look is
// carried by LOCKED_COLORS below plus the disc's grey palette + grayscale
// filter, matching the design's ac()/ac2() locked-grey behaviour.
const ICON_COLORS: Record<string, [string, string]> = {
  "first-steps": ["#c8dd97", "#e8f0b4"],
  "flash": ["#f4f0e8", "#ffe0a0"],
  "bookworm": ["#e6d3b3", "#d0b48a"],
  "on-fire": ["#ffb07f", "#ffdca0"],
  "early-bird": ["#ffd58a", "#ffeab8"],
  "night-owl": ["#eef3ff", "#ffeab0"],
  "deep-focus": ["#e6c48f", "#fff0d8"],
  "quiz-master": ["#eef6f0", "#a6e6c2"],
  "marathon": ["#9cc47f", "#d6b98a"],
  "wildfire": ["#ffb07f", "#ffdca0"],
  "first-friend": ["#cfe6a4", "#a6cf8a"],
  "study-circle": ["#e0eda8", "#c2dd8f"],
  "helping-hand": ["#efe2cc", "#b0dfa0"],
  "room-leader": ["#ffe08f", "#a6dde2"],
  "popular": ["#d9edb2", "#a6cf8a"],
  "mentor": ["#ffe08f", "#d8e6a4"],
  "social-butterfly": ["#ffb07f", "#ffd98f"],
  "sprout": ["#c8dd97", "#e8f0b4"],
  "rooted": ["#bcd678", "#e4ef9c"],
  "grade-a": ["#a6cf8a", "#ffeab0"],
  "branching": ["#d6a877", "#a6d68f"],
  "rings": ["#e6cc9c", "#c49a6a"],
  "web": ["#d9edb2", "#a6cf8a"],
  "canopy": ["#d6a877", "#a6d68f"],
  "old-growth": ["#d6a877", "#a6d68f"],
  "methuselah": ["#6b4a2d", "#e8dbc0"],
  "perfect-week": ["#dbe8a4", "#ffe08f"],
  "comeback": ["#d6b088", "#c8dd97"],
  "polymath": ["#ffe08f", "#e4c0f0"],
  "golden-hour": ["#ffd88f", "#ffc57a"],
  "secret": ["#eef0e6", "#c7bfad"],
};

const LOCKED_COLORS: [string, string] = ["#cbc8c0", "#e6e3db"];

export function BadgeArt({
  slug, rarity, locked, iconUrl, emoji, size = 80,
}: {
  slug: string;
  rarity: RarityTier;
  locked: boolean;
  iconUrl?: string | null;
  emoji?: string | null;
  size?: number;
}) {
  const d = discFor(rarity, locked);
  const id = React.useId().replace(/:/g, "");
  const builtIn = ICON_PATHS[slug];
  const [main, shade] = locked ? LOCKED_COLORS : (ICON_COLORS[slug] ?? ["#bcd678", "#e4ef9c"]);

  return (
    <svg viewBox="0 0 64 64" width={size} height={size} style={{ display: "block", overflow: "visible" }}>
      <defs>
        <radialGradient id={`bg-${id}`} cx="40%" cy="33%" r="72%">
          <stop offset="0%" stopColor={d.gl} />
          <stop offset="100%" stopColor={d.gd} />
        </radialGradient>
        <clipPath id={`clip-${id}`}><circle cx="32" cy="32" r="23.2" /></clipPath>
      </defs>
      <circle cx="32" cy="33.4" r="30" fill="rgba(19,38,16,0.16)" />
      <circle cx="32" cy="32" r="30" fill={d.band} stroke="rgba(0,0,0,0.06)" strokeWidth="1" />
      <circle cx="32" cy="32" r="23.2" fill={`url(#bg-${id})`} stroke={d.br} strokeWidth="2.6" />
      {iconUrl ? (
        <image
          href={iconUrl} x="17" y="17" width="30" height="30"
          clipPath={`url(#clip-${id})`} preserveAspectRatio="xMidYMid meet"
          style={locked ? { filter: "grayscale(1) opacity(0.55)" } : undefined}
        />
      ) : builtIn ? (
        <svg x="17" y="17" width="30" height="30" viewBox="0 0 48 48" fill="none"
             data-icon={slug}
             dangerouslySetInnerHTML={{ __html: builtIn(main, shade) }} />
      ) : (
        <text x="32" y="39" textAnchor="middle" fontSize="20"
              style={locked ? { filter: "grayscale(1) opacity(0.5)" } : undefined}>
          {emoji || "★"}
        </text>
      )}
    </svg>
  );
}
