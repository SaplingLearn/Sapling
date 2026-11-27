"use client";
import React from "react";

const palette = ["#4e873c", "#3e6f8a", "#a8456b", "#b4862c", "#7b4b99", "#b4562c"];

export function Avatar({
  name,
  size = 28,
  color,
  img,
  frame,
}: {
  name: string;
  size?: number;
  color?: string;
  img?: string;
  frame?: string | null;
}) {
  const initials = name
    .split(" ")
    .map((s) => s[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const bg = color || palette[name.charCodeAt(0) % palette.length];
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <div
        className="rounded-[50%] text-accent-fg flex items-center justify-center font-semibold font-sans border border-[rgba(0,0,0,0.08)] overflow-hidden" style={{ width: size, height: size, background: bg, fontSize: Math.max(10, size * 0.36) }}
      >
        {img ? (
          <img
            src={img}
            alt=""
            width={size}
            height={size}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            className="w-full h-full object-cover"
          />
        ) : (
          initials
        )}
      </div>
      {frame && (
        <div
          className="absolute inset-[-3px] rounded-[50%]" style={{ border: `2px solid ${frame}`, boxShadow: `0 0 8px ${frame}66` }}
        />
      )}
    </div>
  );
}
