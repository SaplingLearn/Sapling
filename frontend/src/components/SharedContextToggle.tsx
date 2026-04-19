"use client";

import React, { useEffect, useState } from "react";

const STORAGE_KEY = "sapling_shared_ctx";

export function useSharedContext(): [boolean, (v: boolean) => void] {
  const [enabled, setEnabled] = useState(true);
  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "false") setEnabled(false);
  }, []);
  const update = (v: boolean) => {
    setEnabled(v);
    localStorage.setItem(STORAGE_KEY, String(v));
  };
  return [enabled, update];
}

export function SharedContextToggle({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (v: boolean) => void;
}) {
  const [tooltip, setTooltip] = useState(false);

  return (
    <div
      style={{ position: "relative", display: "inline-block" }}
      onMouseEnter={() => setTooltip(true)}
      onMouseLeave={() => setTooltip(false)}
      onFocus={() => setTooltip(true)}
      onBlur={() => setTooltip(false)}
    >
      <button
        role="switch"
        aria-checked={enabled}
        onClick={() => onChange(!enabled)}
        className="btn btn--sm"
        style={{
          padding: "5px 10px",
          background: enabled ? "var(--accent-soft)" : "var(--bg-subtle)",
          color: enabled ? "var(--accent)" : "var(--text-dim)",
          borderColor: enabled ? "var(--accent-border)" : "var(--border)",
          fontSize: 12,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 24,
            height: 12,
            borderRadius: "var(--r-full)",
            background: enabled ? "var(--accent)" : "var(--border-strong)",
            position: "relative",
            transition: "background var(--dur-fast) var(--ease)",
          }}
        >
          <span
            style={{
              position: "absolute",
              top: 1,
              left: enabled ? 13 : 1,
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#fff",
              transition: "left var(--dur-fast) var(--ease)",
            }}
          />
        </span>
        Class intel
      </button>
      {tooltip && (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 60,
            width: 240,
            padding: 10,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--r-md)",
            boxShadow: "var(--shadow-md)",
            fontSize: 11,
            color: "var(--text-dim)",
            lineHeight: 1.5,
          }}
        >
          <strong style={{ color: "var(--text)", display: "block", marginBottom: 4 }}>
            Shared course context
          </strong>
          Includes anonymized class-level patterns (common gaps, frequent questions). Disabling keeps the
          tutor focused on only your individual state.
        </div>
      )}
    </div>
  );
}
