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
      color: "#1D4ED8",
      soft: "rgba(59, 130, 246, 0.12)",
      border: "rgba(59, 130, 246, 0.35)",
    },
    {
      value: "smart",
      label: "Smart",
      color: "#6D28D9",
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
      className="relative inline-block"
      onMouseEnter={() => setTooltip(true)}
      onMouseLeave={() => setTooltip(false)}
      onFocus={() => setTooltip(true)}
      onBlur={() => setTooltip(false)}
    >
      <div
        role="radiogroup"
        aria-label="Tutor model"
        className="relative inline-flex h-7 p-0.5 items-center bg-bg-subtle border border-border rounded-[var(--r-full)] box-border"
      >
        <span
          aria-hidden
          className="absolute top-0.5 left-0.5 w-14 h-[calc(100%_-_4px)] rounded-[var(--r-full)] [transition:transform_var(--dur-fast)_var(--ease),_background_var(--dur-fast)_var(--ease),_border-color_var(--dur-fast)_var(--ease)]" style={{ background: active.soft, border: `1px solid ${active.border}`, transform: `translateX(${activeIndex * 56}px)` }}
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
          className="absolute top-[calc(100%_+_6px)] right-0 z-60 w-60 p-2.5 bg-bg-panel border border-border-strong rounded-md shadow-md text-xs text-text-dim leading-[1.5]"
        >
          <strong className="text-text block mb-1">
            Tutor model
          </strong>
          Fast is the default — lighter and snappier. Switch to Smart for stronger reasoning
          when you want depth.
        </div>
      )}
    </div>
  );
}
