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
  const options: {
    value: ModelPref;
    label: string;
    color: string;
    soft: string;
    border: string;
  }[] = [
    {
      value: "fast",
      label: "Fast",
      color: "#3B82F6",
      soft: "rgba(59, 130, 246, 0.12)",
      border: "rgba(59, 130, 246, 0.35)",
    },
    {
      value: "smart",
      label: "Smart",
      color: "#8A63D2",
      soft: "rgba(138, 99, 210, 0.14)",
      border: "rgba(138, 99, 210, 0.4)",
    },
  ];

  const activeIndex = pref === "smart" ? 1 : 0;
  const active = options[activeIndex];

  const segmentStyle = (isActive: boolean, color: string): React.CSSProperties => ({
    width: 56,
    padding: "4px 0",
    fontSize: 12,
    fontWeight: isActive ? 600 : 500,
    textAlign: "center",
    border: "none",
    background: "transparent",
    color: isActive ? color : "var(--text-dim)",
    cursor: "pointer",
    borderRadius: "var(--r-full)",
    position: "relative",
    zIndex: 1,
    transition: "color var(--dur-fast) var(--ease)",
  });

  return (
    <div
      style={{ position: "relative", display: "inline-block" }}
      onMouseEnter={() => setTooltip(true)}
      onMouseLeave={() => setTooltip(false)}
      onFocus={() => setTooltip(true)}
      onBlur={() => setTooltip(false)}
    >
      <div
        role="radiogroup"
        aria-label="Tutor model"
        style={{
          position: "relative",
          display: "inline-flex",
          height: 28,
          padding: 2,
          alignItems: "center",
          background: "var(--bg-subtle)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-full)",
          boxSizing: "border-box",
        }}
      >
        <span
          aria-hidden
          style={{
            position: "absolute",
            top: 2,
            left: 2,
            width: 56,
            height: "calc(100% - 4px)",
            borderRadius: "var(--r-full)",
            background: active.soft,
            border: `1px solid ${active.border}`,
            transform: `translateX(${activeIndex * 56}px)`,
            transition:
              "transform var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease)",
          }}
        />
        {options.map((opt) => {
          const isActive = pref === opt.value;
          return (
            <button
              key={opt.value}
              role="radio"
              aria-checked={isActive}
              onClick={() => onChange(opt.value)}
              style={segmentStyle(isActive, opt.color)}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
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
          Fast is the default — quicker replies. Switch to Smart for stronger reasoning when
          you want depth and don&apos;t mind waiting.
        </div>
      )}
    </div>
  );
}
