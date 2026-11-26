"use client";

import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";

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
  ariaLabel?: string;
  disabled?: boolean;
  size?: "sm" | "md";
  align?: "left" | "right";
  className?: string;
  style?: React.CSSProperties;
  /** Merged over the trigger button's own style (e.g. a pill radius). */
  triggerStyle?: React.CSSProperties;
  /** `data-testid` on the trigger button. */
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
  const listboxId = useId();
  // Opens downward unless there isn't room there and there is more above.
  const [place, setPlace] = useState<{ up: boolean; max: number }>({ up: false, max: LIST_MAX });

  const selectedIndex = useMemo(() => options.findIndex(o => o.value === value), [options, value]);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null;

  useEffect(() => {
    if (!open) return;
    setHighlighted(selectedIndex >= 0 ? selectedIndex : 0);
    const onDown = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      // Handled: an Esc that closes the list shouldn't also close what it sits in.
      if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, selectedIndex]);

  // Measured as the list opens, so it lays out once in the right place.
  const toggle = () => {
    const el = wrapperRef.current;
    if (!open && el) {
      const r = el.getBoundingClientRect();
      const box = clipBox(el);
      const below = box.bottom - r.bottom - LIST_GAP * 2;
      const above = r.top - box.top - LIST_GAP * 2;
      const up = below < Math.min(LIST_MAX, 200) && above > below;
      setPlace({ up, max: Math.max(LIST_MIN, Math.min(LIST_MAX, up ? above : below)) });
    }
    setOpen(o => !o);
  };

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
      toggle();
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
      className={cn(className, "relative inline-block")}
      style={{ ...style }}
    >
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-label={ariaLabel}
        data-testid={testId}
        disabled={disabled}
        onClick={() => !disabled && toggle()}
        onKeyDown={onButtonKey}
        className={cn("inline-flex items-center justify-between gap-2 w-full rounded-sm border border-border bg-bg-input text-left [transition:border-color_var(--dur-fast)_var(--ease)]", selected ? "text-text" : "text-text-muted", disabled ? "cursor-not-allowed" : "cursor-pointer", disabled ? "opacity-60" : "opacity-100")} style={{ padding, fontSize, ...triggerStyle }}
      >
        <span className="overflow-hidden text-ellipsis whitespace-nowrap">
          {selected ? selected.label : placeholder}
        </span>
        <span aria-hidden className={cn("text-2xs text-text-muted [transition:transform_var(--dur-fast)_var(--ease)]", open ? "[transform:rotate(180deg)]" : "[transform:none]")}>▾</span>
      </button>
      {open && (
        <ul
          role="listbox"
          id={listboxId}
          tabIndex={-1}
          onKeyDown={onListKey}
          ref={el => el?.focus({ preventScroll: true })}
          className={cn("fade-in", "absolute z-100 min-w-full m-0 p-1 list-none [background:var(--bg-panel)] border border-border-strong rounded-md shadow-lg overflow-y-auto", align === "left" ? "left-0" : "left-auto", align === "right" ? "right-0" : "right-auto")}
          style={{ top: place.up ? "auto" : `calc(100% + ${LIST_GAP}px)`, bottom: place.up ? `calc(100% + ${LIST_GAP}px)` : "auto", maxHeight: place.max }}
        >
          {options.map((opt, idx) => {
            const active = idx === highlighted;
            const isSelected = opt.value === value;
            return (
              <li
                key={opt.value}
                role="option"
                data-testid={opt.testId}
                aria-selected={isSelected}
                aria-disabled={opt.disabled}
                onMouseEnter={() => setHighlighted(idx)}
                onClick={() => commit(idx)}
                className={cn("py-[7px] px-2.5 rounded-sm flex items-center gap-1.5", opt.disabled ? "cursor-not-allowed" : "cursor-pointer", opt.disabled ? "text-text-muted" : "text-text", active && !opt.disabled ? "bg-bg-subtle" : "bg-transparent")} style={{ fontSize }}
              >
                <span className="flex-1 min-w-0">
                  <span>{opt.label}</span>
                  {opt.description && (
                    <span className="block text-xs text-text-muted">{opt.description}</span>
                  )}
                </span>
                {isSelected && <span aria-hidden className="text-accent text-sm">✓</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
