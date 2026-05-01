"use client";
import React from "react";

// Each entry is either a bare path string (uses the default stroke
// config below) or a full spec so individual icons — e.g. Streamline
// Guidance — can bring their own stroke weight, cap style, and
// multiple subpaths rendered as separate <path> elements.
type IconSpec = {
  d: string | string[];
  strokeWidth?: number;
  linecap?: "round" | "butt" | "square";
  linejoin?: "round" | "miter" | "bevel";
};

const paths: Record<string, string | IconSpec> = {
  home: {
    d: "M22.5 21V10.25l-0.247 -0.113a20 20 0 0 1 -8.942 -8.104L13 1.5h-2l-0.311 0.533a20 20 0 0 1 -8.942 8.104l-0.247 0.113V21M23 22.5H1M15 21v-4a3 3 0 1 0 -6 0v4",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  brain: {
    d: "M10 22.5h13M3.5 16 18 1.5A4.5 4.5 0 0 1 22.5 6L8 20.5H7c-1.974 0 -3.377 0.584 -5.02 1.68l-0.48 0.32 0.32 -0.48C2.917 20.376 3.5 18.973 3.5 17v-1Z",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  tree: {
    d: "M12 19.56v4.38M4.5 12.56h3.724A33.264 33.264 0 0 1 1.5 19.31v0.25h21v-0.25a33.263 33.263 0 0 1 -6.724 -6.75H19.5v-0.25l-1.386 -1.04A15.383 15.383 0 0 1 12 0.06a15.384 15.384 0 0 1 -6.114 11.21L4.5 12.31v0.25Z",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  book: {
    d: "M12 7.5V17m0 -9.5a3 3 0 0 0 -3 -3H2v1.085A62.99 62.99 0 0 1 0.5 19.25v0.25H9a3 3 0 0 1 3 3m0 -15a3 3 0 0 1 3 -3h7v1.085c0 4.596 0.503 9.178 1.5 13.665v0.25H15a3 3 0 0 0 -3 3m0 0v0.5",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  // Streamline Guidance (Free) — drawn at 1px stroke, sharp caps/joins.
  cal: {
    d: "M7.5 6V1m10 5V1m4 16v4.5h-18v-3m17.863 -10H3.352M0.5 18.25v0.25h17.9l0.15 -0.25 0.234 -0.491A28 28 0 0 0 21.5 5.729V3.5h-18v2.128A28 28 0 0 1 0.743 17.744L0.5 18.25Z",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  users: {
    d: "M6 8.5h12M6 13h6M23.5 2H23c-3 0.5 -8 0.75 -11 0.75S4 2.5 1 2H0.5v21.5h0.25l0.154 -0.154A15.692 15.692 0 0 1 12 18.75c3 0 8 0.25 11 0.75h0.5V2Z",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  sparkle: "M12 2l2.5 7L22 11.5l-7.5 2.5L12 22l-2.5-8L2 11.5 9.5 9z",
  cog: {
    d: [
      "m10.5 1.5 -0.181 0.543a7 7 0 0 1 -0.716 1.514 4.632 4.632 0 0 1 -3.717 2.146 6.998 6.998 0 0 1 -1.668 -0.137l-0.561 -0.115 -1.5 2.598 0.38 0.429c0.374 0.422 0.693 0.884 0.953 1.376a4.632 4.632 0 0 1 0 4.292 7 7 0 0 1 -0.953 1.376l-0.38 0.429 1.5 2.598 0.56 -0.115a6.997 6.997 0 0 1 1.67 -0.137 4.632 4.632 0 0 1 3.716 2.146c0.296 0.47 0.537 0.979 0.716 1.514l0.181 0.543h3l0.181 -0.543c0.179 -0.536 0.42 -1.043 0.716 -1.514a4.632 4.632 0 0 1 3.717 -2.146 6.996 6.996 0 0 1 1.668 0.137l0.561 0.115 1.5 -2.598 -0.38 -0.429a7.007 7.007 0 0 1 -0.953 -1.376 4.632 4.632 0 0 1 0 -4.292c0.26 -0.492 0.579 -0.954 0.953 -1.376l0.38 -0.429 -1.5 -2.598 -0.56 0.115a6.999 6.999 0 0 1 -1.67 0.137 4.632 4.632 0 0 1 -3.716 -2.146 6.997 6.997 0 0 1 -0.716 -1.514L13.5 1.5h-3Z",
      "M15.502 12a3.502 3.502 0 1 1 -7.004 0 3.502 3.502 0 0 1 7.004 0Z",
    ],
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  trophy: {
    d: "M12 6.5v15m0 -15V4m0 2.5H9.5A2.5 2.5 0 1 1 12 4m0 2.5h2.5A2.5 2.5 0 1 0 12 4M3.25 14h17.5m-17.5 0c0 -2.328 -0.23 -4.65 -0.686 -6.932L2.5 6.75V6.5h19v0.25l-0.064 0.318A35.346 35.346 0 0 0 20.75 14m-17.5 0c0 2.328 -0.23 4.65 -0.686 6.932l-0.064 0.318v0.25h19v-0.25l-0.064 -0.318A35.345 35.345 0 0 1 20.75 14",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  shield: {
    d: [
      "M11.75 23.5C4 19 2.5 16 2.5 5.5c3.15 0 6.356 -1.238 8.276 -3.357 0.422 -0.465 0.687 -1.044 0.874 -1.643h0.7c0.187 0.599 0.452 1.178 0.874 1.643C15.144 4.262 18.35 5.5 21.5 5.5c0 10.5 -1.5 13.5 -9.25 18h-0.5Z",
      "M11.898 7.5h0.204l0.15 0.542a4 4 0 0 0 3.856 2.935h0.392v0.166l-0.365 0.252a4 4 0 0 0 -1.55 4.473l0.196 0.632h-0.21a4.066 4.066 0 0 0 -5.142 0h-0.21l0.195 -0.632a4 4 0 0 0 -1.55 -4.473l-0.364 -0.252v-0.166h0.392a4 4 0 0 0 3.856 -2.935l0.15 -0.542Z",
    ],
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  flask: "M9 3h6M10 3v6l-5 10a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-10V3",
  plus: "M12 5v14M5 12h14",
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zM21 21l-4.3-4.3",
  menu: "M4 6h16M4 12h16M4 18h16",
  x: "M6 6l12 12M18 6L6 18",
  chev: "M9 18l6-6-6-6",
  send: "M22 2L11 13M22 2l-7 20-4-9-9-4z",
  max: "M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7",
  bolt: {
    d: "m12.165 7.835 1.3 -1.3a3.536 3.536 0 0 0 -5 -5l-1.3 1.3c-0.437 0.437 -0.97 0.767 -1.558 0.963L3.5 4.5v0.25l6.75 6.75h0.25l0.703 -2.107c0.195 -0.587 0.525 -1.12 0.962 -1.558Zm0 0L12.27 8a9.724 9.724 0 0 0 5.365 4.38M6.5 10.5a1.414 1.414 0 1 1 -2 -2m8.964 -6.964L14.6 0.4M12 20.5c0 -0.66 0.113 -1.322 0.415 -1.91a10.533 10.533 0 0 1 5.264 -4.88M12 20.5c5.5 0 8.5 2 8.5 2v1h-17v-1s3 -2 8.5 -2Zm5.678 -6.79a1.5 1.5 0 1 0 -0.044 -1.33m0.044 1.33a1.493 1.493 0 0 1 -0.044 -1.33",
    strokeWidth: 1,
    linecap: "butt",
    linejoin: "miter",
  },
  check: "M5 12l5 5L20 7",
  star: "M12 2l3 7h7l-5.5 4.5L18 21l-6-4-6 4 1.5-7.5L2 9h7z",
  fire: "M12 2s5 4 5 9a5 5 0 0 1-10 0c0-3 2-4 2-7 2 2 3 3 3 5 1-2 0-5 0-7z",
  doc: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
  up: "M12 19V5M5 12l7-7 7 7",
  bell: "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M14 21a2 2 0 0 1-4 0",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  pencil: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  palette: "M12 22a10 10 0 1 1 10-10c0 2-1 3-3 3h-2a2 2 0 0 0-1 4 2 2 0 0 1-1 3 7 7 0 0 1-3 0",
  heart: "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.6z",
};

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  const entry = paths[name];
  if (!entry) return null;
  const spec: IconSpec =
    typeof entry === "string" ? { d: entry } : entry;
  const ds = Array.isArray(spec.d) ? spec.d : [spec.d];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={spec.strokeWidth ?? 1.8}
      strokeLinecap={spec.linecap ?? "round"}
      strokeLinejoin={spec.linejoin ?? "round"}
      style={{ flexShrink: 0 }}
    >
      {ds.map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}
