"use client";
/**
 * A segmented switcher whose selected pill slides between its options.
 *
 * The Library's List ⇄ Panel toggle used to paint the pill onto whichever tab
 * was selected, so a switch snapped it across. Here there is ONE pill — the
 * thumb — laid behind the tabs and moved under the selected one with a
 * transform (and width) transition, measured from the tab's
 * `offsetLeft`/`offsetWidth` and re-measured whenever the track or a tab
 * resizes (a window resize, a late web font). The labels' colour eases with
 * it.
 *
 * At rest it is the toggle exactly as designed: the same track, padding, gap,
 * radii, colours and shadow; only the pill's owner changed. On first paint the
 * thumb is inserted already in place, so it never slides in. Before it has
 * been measured (the server render, the first client render) the selected tab
 * wears the pill itself, so no frame shows a bare track.
 *
 * The motion is the Library's 220 ms entrance curve, set by the
 * `.sapSwitchThumb` / `.sapSwitchTab` classes in library-notes.css — classes
 * rather than inline styles so the reduced-motion rule there can switch the
 * transitions off and the thumb snaps.
 *
 * Keyboard: the tabs follow the WAI-ARIA tabs pattern — only the selected tab
 * is in the Tab order, and Left/Right (wrapping) move to the neighbour, focus
 * it and select it.
 */
import React from "react";

export interface ViewSwitcherOption<K extends string> {
  key: K;
  label: string;
  icon?: React.ReactNode;
}

export interface ViewSwitcherProps<K extends string> {
  options: ViewSwitcherOption<K>[];
  value: K;
  onChange: (key: K) => void;
  /** The tablist's accessible name, e.g. "Layout". */
  label: string;
  /** Each tab is `${testIdPrefix}-${key}`; the thumb is `${testIdPrefix}-thumb`. */
  testIdPrefix?: string;
  style?: React.CSSProperties;
}

/** The selected pill: the design's tab-on colours, now on the thumb. */
const PILL: React.CSSProperties = {
  background: "#FDFCF9",
  boxShadow: "0 1px 2px rgba(25,37,11,0.10)",
};

interface Thumb { x: number; w: number }

export function ViewSwitcher<K extends string>({
  options, value, onChange, label, testIdPrefix, style,
}: ViewSwitcherProps<K>) {
  const trackRef = React.useRef<HTMLDivElement>(null);
  const tabRefs = React.useRef(new Map<K, HTMLButtonElement>());
  const [thumb, setThumb] = React.useState<Thumb | null>(null);

  const measure = React.useCallback(() => {
    const tab = tabRefs.current.get(value);
    if (!tab) return;
    const next = { x: tab.offsetLeft, w: tab.offsetWidth };
    setThumb(t => (t && t.x === next.x && t.w === next.w ? t : next));
  }, [value]);

  // Before paint, so a change of value moves the thumb in the same frame the
  // labels recolour, and the first paint already has it in place.
  React.useLayoutEffect(measure, [measure]);

  React.useEffect(() => {
    window.addEventListener("resize", measure);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    if (observer && trackRef.current) {
      observer.observe(trackRef.current);
      tabRefs.current.forEach(tab => observer.observe(tab));
    }
    return () => {
      window.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [measure]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const at = options.findIndex(o => o.key === value);
    const step = e.key === "ArrowRight" ? 1 : -1;
    const next = options[(at + step + options.length) % options.length];
    tabRefs.current.get(next.key)?.focus();
    onChange(next.key);
  };

  const measured = thumb !== null;
  return (
    <div
      ref={trackRef}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      style={{
        position: "relative", display: "flex", gap: 2, padding: 4, height: 40,
        flexShrink: 0, boxSizing: "border-box", background: "#F4F1EA", borderRadius: 12,
        ...style,
      }}
    >
      {thumb && (
        <span
          aria-hidden="true"
          className="sapSwitchThumb"
          data-testid={testIdPrefix ? `${testIdPrefix}-thumb` : undefined}
          style={{
            position: "absolute", top: 4, bottom: 4, left: 0, width: thumb.w,
            transform: `translateX(${thumb.x}px)`, borderRadius: 9,
            pointerEvents: "none", ...PILL,
          }}
        />
      )}
      {options.map(o => {
        const on = o.key === value;
        return (
          <button
            key={o.key}
            ref={el => {
              if (el) tabRefs.current.set(o.key, el);
              else tabRefs.current.delete(o.key);
            }}
            role="tab"
            className="sapSwitchTab"
            data-testid={testIdPrefix ? `${testIdPrefix}-${o.key}` : undefined}
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.key)}
            style={{
              // Positioned, so it paints over the thumb laid before it.
              position: "relative",
              display: "inline-flex", alignItems: "center", gap: 7, border: 0,
              padding: "0 14px", borderRadius: 9, font: "inherit", fontSize: 14,
              fontWeight: 600, cursor: "pointer",
              background: "transparent", boxShadow: "none",
              ...(on && !measured ? PILL : null),
              color: on ? "#1A1814" : "#6F6857",
            }}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
