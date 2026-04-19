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
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: bg,
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: Math.max(10, size * 0.36),
          fontWeight: 600,
          fontFamily: "var(--font-sans)",
          border: "1px solid rgba(0,0,0,0.08)",
          overflow: "hidden",
        }}
      >
        {img ? (
          <img
            src={img}
            alt=""
            referrerPolicy="no-referrer"
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          initials
        )}
      </div>
      {frame && (
        <div
          style={{
            position: "absolute",
            inset: -3,
            borderRadius: "50%",
            border: `2px solid ${frame}`,
            boxShadow: `0 0 8px ${frame}66`,
          }}
        />
      )}
    </div>
  );
}
