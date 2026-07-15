"use client";
import React from "react";

/**
 * Ambient drifting-orb field per .impeccable.md. PlayStation/Wii-U menu
 * vibe: barely-there colored orbs in soft warm palette, very low opacity,
 * slow drift on independent timings so the field never resolves into a
 * recognizable loop. UI components remain solid and fully unblurred.
 *
 * Mount once per page that wants the brand atmosphere. Renders inside a
 * fixed container at z-index 0 with pointer-events: none; the page's
 * existing background color and content paint over and under it.
 */

interface Orb {
  color: string;
  x: string;
  y: string;
  size: number;
  opacity: number;
  anim: string;
  duration: string;
  delay: string;
}

const ORBS: Orb[] = [
  { color: "#a4c4e8", x: "10%", y: "20%", size: 420, opacity: 0.22, anim: "orb-drift-1", duration: "42s", delay:   "0s" },
  { color: "#c6b3e3", x: "72%", y: "15%", size: 380, opacity: 0.20, anim: "orb-drift-2", duration: "56s", delay: "-12s" },
  { color: "#e8c894", x: "86%", y: "62%", size: 320, opacity: 0.24, anim: "orb-drift-3", duration: "38s", delay:  "-8s" },
  { color: "#a8d5c9", x: "22%", y: "78%", size: 460, opacity: 0.20, anim: "orb-drift-4", duration: "64s", delay: "-20s" },
  { color: "#b6cce8", x: "52%", y: "48%", size: 300, opacity: 0.16, anim: "orb-drift-5", duration: "48s", delay: "-30s" },
  { color: "#d6c2a4", x:  "6%", y: "52%", size: 240, opacity: 0.22, anim: "orb-drift-6", duration: "52s", delay: "-15s" },
];

export function AmbientOrbs() {
  return (
    <div
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {ORBS.map((o, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: o.x,
            top: o.y,
            width: o.size,
            height: o.size,
            borderRadius: "50%",
            background: `radial-gradient(circle, ${o.color} 0%, transparent 70%)`,
            filter: "blur(60px)",
            opacity: o.opacity,
            transform: "translate(-50%, -50%)",
            willChange: "transform",
            animation: `${o.anim} ${o.duration} ease-in-out ${o.delay} infinite`,
          }}
        />
      ))}
    </div>
  );
}
