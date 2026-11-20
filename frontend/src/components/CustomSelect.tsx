"use client";

import React, { useCallback, useId, useLayoutEffect, useMemo, useRef, useState } from "react";

export interface CustomSelectOption<T extends string = string> {
  value: T;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
  /** `data-testid` on this option's row in the open listbox. */
  testId?: string;
}

interface CustomSelectProps<T extends string = string> {
  value: T;
  options: CustomSelectOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  /** What the control chooses ("Course", "Layout"). Required: a screen reader
   *  announces it with the current choice, as "Course, CS 101" — the visible
   *  text alone is only the value (spec §13 A135). */
  ariaLabel: string;
  disabled?: boolean;
  size?: "sm" | "md";
  align?: "left" | "right";
  className?: string;
  style?: React.CSSProperties;
  /** Merged over the trigger button's own style (e.g. a pill radius). */
  triggerStyle?: React.CSSProperties;
  /** E2E surface (docs/frontend-testids.md): `data-testid` on the trigger
   *  button; each option gets `<testId>-option-<value>`. Omitted: no testids. */
  testId?: string;
}

const LIST_MAX = 280;
const LIST_MIN = 120;
const LIST_GAP = 4;

/** The box the open list must fit inside: the viewport, narrowed by every
 *  ancestor that clips or scrolls vertically (a list that runs past a
 *  scrolling panel's edge makes the panel scroll instead of showing it). */
function clipBox(el: HTMLElement): { top: number; bottom: number } {
  let top = 0;
  let bottom = window.innerHeight;
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (getComputedStyle(p).overflowY === "visible") continue;
    const r = p.getBoundingClientRect();
    top = Math.max(top, r.top);
    bottom = Math.min(bottom, r.bottom);
  }
  return { top, bottom };
}

/** Where the list opens: downward unless there isn't room there and there is
 *  more above. Measured as the list opens, so it lays out once in the right place. */
function placeList(el: HTMLElement): { up: boolean; max: number } {
  const r = el.getBoundingClientRect();
  const box = clipBox(el);
  const below = box.bottom - r.bottom - LIST_GAP * 2;
  const above = r.top - box.top - LIST_GAP * 2;
  const up = below < Math.min(LIST_MAX, 200) && above > below;
  return { up, max: Math.max(LIST_MIN, Math.min(LIST_MAX, up ? above : below)) };
}

/**
 * A button that opens a listbox of options (spec §13 A135 for its keyboard
 * and screen-reader behaviour). The button is named by `ariaLabel` and the
 * current choice. Enter, Space or an arrow key opens the list, which takes
 * focus with the chosen option (else the first enabled one) active; the
 * active option is the listbox's `aria-activedescendant`, so a screen reader
 * follows it. Up / Down move (skipping disabled options), Home / End jump to
 * the ends, Enter or Space chooses, Escape closes; both return focus to the
 * button. Tab closes and moves on; a click outside closes.
 */
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
  triggerStyle,
  testId,
}: CustomSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const baseId = useId();
  const listboxId = `${baseId}-listbox`;
  const labelId = `${baseId}-label`;
  const valueId = `${baseId}-value`;
  const optionId = (idx: number) => `${baseId}-option-${idx}`;
  // Opens downward unless there isn't room there and there is more above.
  const [place, setPlace] = useState<{ up: boolean; max: number }>({ up: false, max: LIST_MAX });

  const selectedIndex = useMemo(() => options.findIndex(o => o.value === value), [options, value]);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null;

  /** The enabled option `step` places from `from` (wrapping), or `from` when there is none. */
  const enabledFrom = useCallback((from: number, step: 1 | -1) => {
    for (let i = 1; i <= options.length; i++) {
      const next = (((from + step * i) % options.length) + options.length) % options.length;
      if (!options[next].disabled) return next;
    }
    return from;
  }, [options]);
  const firstEnabled = useCallback(() => options.findIndex(o => !o.disabled), [options]);
  const lastEnabled = useCallback(() => {
    for (let i = options.length - 1; i >= 0; i--) if (!options[i].disabled) return i;
    return -1;
  }, [options]);

  const openList = () => {
    if (disabled) return;
    if (wrapperRef.current) setPlace(placeList(wrapperRef.current));
    setHighlighted(selected && !selected.disabled ? selectedIndex : firstEnabled());
    setOpen(true);
  };
  /** Close; `refocus` returns focus to the button (the list it held is going away). */
  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  }, []);

  // While open: the list holds focus (once, on opening); a click outside closes
  // it, and so does Escape wherever focus is.
  useLayoutEffect(() => {
    if (!open) return;
    listRef.current?.focus({ preventScroll: true });
    const onDown = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Handled: an Esc that closes the list shouldn't also close what it sits in.
      e.preventDefault();
      close(!!wrapperRef.current?.contains(document.activeElement));
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  // Keep the active option in view as the keys move it.
  useLayoutEffect(() => {
    if (!open || highlighted < 0) return;
    document.getElementById(optionId(highlighted))?.scrollIntoView?.({ block: "nearest" });
    // optionId is derived from the stable useId value
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, highlighted]);

  const commit = useCallback((idx: number, refocus: boolean) => {
    const opt = options[idx];
    if (!opt || opt.disabled) return;
    onChange(opt.value);
    close(refocus);
  }, [options, onChange, close]);

  const onButtonKey = (e: React.KeyboardEvent) => {
    if (disabled) return;
    if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (open) close(false);
      else openList();
    }
  };

  const onListKey = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlighted(h => enabledFrom(h, 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlighted(h => enabledFrom(h < 0 ? 0 : h, -1));
        break;
      case "Home":
        e.preventDefault();
        setHighlighted(firstEnabled());
        break;
      case "End":
        e.preventDefault();
        setHighlighted(lastEnabled());
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        commit(highlighted, true);
        break;
      case "Escape":
        e.preventDefault();
        e.stopPropagation(); // a dialog around the select stays open
        close(true);
        break;
      case "Tab":
        close(false); // focus moves on to the next control
        break;
      default:
        break;
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
      <span id={labelId} hidden>{ariaLabel}</span>
      <button
        ref={buttonRef}
        type="button"
        data-testid={testId}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-labelledby={`${labelId} ${valueId}`}
        disabled={disabled}
        onClick={() => {
          if (disabled) return;
          if (open) close(false);
          else openList();
        }}
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
          ...triggerStyle,
        }}
      >
        <span id={valueId} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {selected ? selected.label : placeholder}
        </span>
        <span aria-hidden style={{ fontSize: 10, color: "var(--text-muted)", transform: open ? "rotate(180deg)" : "none", transition: "transform var(--dur-fast) var(--ease)" }}>▾</span>
      </button>
      {open && (
        <ul
          ref={listRef}
          role="listbox"
          id={listboxId}
          tabIndex={-1}
          aria-labelledby={labelId}
          aria-activedescendant={highlighted >= 0 ? optionId(highlighted) : undefined}
          onKeyDown={onListKey}
          className="fade-in"
          style={{
            position: "absolute",
            zIndex: 100,
            top: place.up ? "auto" : `calc(100% + ${LIST_GAP}px)`,
            bottom: place.up ? `calc(100% + ${LIST_GAP}px)` : "auto",
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
            maxHeight: place.max,
            overflowY: "auto",
          }}
        >
          {options.map((opt, idx) => {
            const active = idx === highlighted;
            const isSelected = opt.value === value;
            return (
              <li
                key={opt.value}
                id={optionId(idx)}
                // An option's own testId wins; otherwise `<testId>-option-<value>`.
                data-testid={opt.testId ?? (testId ? `${testId}-option-${opt.value}` : undefined)}
                role="option"
                aria-selected={isSelected}
                aria-disabled={opt.disabled}
                onMouseEnter={() => setHighlighted(idx)}
                onClick={() => commit(idx, true)}
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
