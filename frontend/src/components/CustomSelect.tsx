"use client";

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

export interface CustomSelectOption<T extends string = string> {
  value: T;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
}

interface CustomSelectProps<T extends string = string> {
  value: T;
  options: CustomSelectOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
  size?: "sm" | "md";
  align?: "left" | "right";
  className?: string;
  style?: React.CSSProperties;
}

export function CustomSelect<T extends string = string>({
  value,
  options,
  onChange,
  placeholder = "Select…",
  ariaLabel,
  disabled,
  size = "md",
  align = "left",
  className,
  style,
}: CustomSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const listboxId = useId();

  const selectedIndex = useMemo(() => options.findIndex(o => o.value === value), [options, value]);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null;

  useEffect(() => {
    if (!open) return;
    setHighlighted(selectedIndex >= 0 ? selectedIndex : 0);
    const onDown = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, selectedIndex]);

  const commit = useCallback((idx: number) => {
    const opt = options[idx];
    if (!opt || opt.disabled) return;
    onChange(opt.value);
    setOpen(false);
  }, [options, onChange]);

  const onButtonKey = (e: React.KeyboardEvent) => {
    if (disabled) return;
    if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(o => !o);
      return;
    }
  };

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted(h => {
        for (let i = 1; i <= options.length; i++) {
          const next = (h + i) % options.length;
          if (!options[next].disabled) return next;
        }
        return h;
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted(h => {
        for (let i = 1; i <= options.length; i++) {
          const next = (h - i + options.length) % options.length;
          if (!options[next].disabled) return next;
        }
        return h;
      });
    } else if (e.key === "Enter") {
      e.preventDefault();
      commit(highlighted);
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  const padding = size === "sm" ? "5px 10px" : "8px 12px";
  const fontSize = size === "sm" ? 12 : 13;

  return (
    <div
      ref={wrapperRef}
      className={className}
      style={{ position: "relative", display: "inline-block", ...style }}
    >
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => !disabled && setOpen(o => !o)}
        onKeyDown={onButtonKey}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          width: "100%",
          padding,
          fontSize,
          borderRadius: "var(--r-sm)",
          border: "1px solid var(--border)",
          background: "var(--bg-input)",
          color: selected ? "var(--text)" : "var(--text-muted)",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.6 : 1,
          textAlign: "left",
          transition: "border-color var(--dur-fast) var(--ease)",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {selected ? selected.label : placeholder}
        </span>
        <span aria-hidden style={{ fontSize: 10, color: "var(--text-muted)", transform: open ? "rotate(180deg)" : "none", transition: "transform var(--dur-fast) var(--ease)" }}>▾</span>
      </button>
      {open && (
        <ul
          role="listbox"
          id={listboxId}
          tabIndex={-1}
          onKeyDown={onListKey}
          ref={el => el?.focus()}
          className="fade-in"
          style={{
            position: "absolute",
            zIndex: 100,
            top: "calc(100% + 4px)",
            left: align === "left" ? 0 : "auto",
            right: align === "right" ? 0 : "auto",
            minWidth: "100%",
            margin: 0,
            padding: 4,
            listStyle: "none",
            background: "var(--bg-panel)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--r-md)",
            boxShadow: "var(--shadow-lg)",
            maxHeight: 280,
            overflowY: "auto",
          }}
        >
          {options.map((opt, idx) => {
            const active = idx === highlighted;
            const isSelected = opt.value === value;
            return (
              <li
                key={opt.value}
                role="option"
                aria-selected={isSelected}
                aria-disabled={opt.disabled}
                onMouseEnter={() => setHighlighted(idx)}
                onClick={() => commit(idx)}
                style={{
                  padding: "7px 10px",
                  fontSize,
                  borderRadius: "var(--r-sm)",
                  cursor: opt.disabled ? "not-allowed" : "pointer",
                  color: opt.disabled ? "var(--text-muted)" : "var(--text)",
                  background: active && !opt.disabled ? "var(--bg-subtle)" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span>{opt.label}</span>
                  {opt.description && (
                    <span style={{ display: "block", fontSize: 11, color: "var(--text-muted)" }}>{opt.description}</span>
                  )}
                </span>
                {isSelected && <span aria-hidden style={{ color: "var(--accent)", fontSize: 12 }}>✓</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
