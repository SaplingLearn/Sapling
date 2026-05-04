"use client";

import React, { useEffect, useState } from "react";

export type ModelPref = "smart" | "fast";

const STORAGE_KEY = "sapling_model_pref";

export function useModelPref(): [ModelPref, (v: ModelPref) => void] {
  const [pref, setPref] = useState<ModelPref>("fast");
  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "fast" || raw === "smart") setPref(raw);
  }, []);
  const update = (v: ModelPref) => {
    setPref(v);
    localStorage.setItem(STORAGE_KEY, v);
  };
  return [pref, update];
}

export function ModelToggle({
  pref,
  onChange,
}: {
  pref: ModelPref;
  onChange: (v: ModelPref) => void;
}) {
  const [tooltip, setTooltip] = useState(false);
  // Fast is the default; Smart is the opt-in upgrade, so it gets the highlight.
  const isSmart = pref === "smart";

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
        aria-checked={isSmart}
        onClick={() => onChange(isSmart ? "fast" : "smart")}
        className="btn btn--sm"
        style={{
          padding: "5px 10px",
          background: isSmart ? "var(--accent-soft)" : "var(--bg-subtle)",
          color: isSmart ? "var(--accent)" : "var(--text-dim)",
          borderColor: isSmart ? "var(--accent-border)" : "var(--border)",
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
            background: isSmart ? "var(--accent)" : "var(--border-strong)",
            position: "relative",
            transition: "background var(--dur-fast) var(--ease)",
          }}
        >
          <span
            style={{
              position: "absolute",
              top: 1,
              left: isSmart ? 13 : 1,
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#fff",
              transition: "left var(--dur-fast) var(--ease)",
            }}
          />
        </span>
        {isSmart ? "Smart" : "Fast"}
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
            Tutor model
          </strong>
          Fast is the default — quicker replies. Flip on Smart for stronger reasoning when you
          want depth and don&apos;t mind waiting.
        </div>
      )}
    </div>
  );
}
