"use client";
import React from "react";
import { createPortal } from "react-dom";

/**
 * Tooltip — a short hint shown on hover AND keyboard focus.
 *
 * The app's existing tooltips (SharedContextToggle, AIDisclaimerChip) are
 * absolutely positioned inside their trigger, which clips inside any
 * `overflow` container — a Sheet body, a scrolling table. This one portals to
 * `document.body` and positions itself `fixed` from the trigger's rect, so it
 * works anywhere, and flips below the trigger when there's no room above.
 *
 * The trigger is the single child element; it gets `aria-describedby` while
 * the tip is open, so screen readers read the hint with the control.
 */
export function Tooltip({
  content,
  children,
  placement = "top",
  delayMs = 250,
}: {
  content: React.ReactNode;
  children: React.ReactElement<React.HTMLAttributes<HTMLElement>>;
  placement?: "top" | "bottom";
  delayMs?: number;
}) {
  const id = `tt-${React.useId()}`;
  const anchorRef = React.useRef<HTMLSpanElement | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pos, setPos] = React.useState<{ top: number; left: number; side: "top" | "bottom" } | null>(null);

  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  const show = (immediate = false) => {
    clear();
    const open = () => {
      const el = anchorRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const roomAbove = r.top > 72;
      const side = placement === "top" && roomAbove ? "top" : "bottom";
      setPos({ top: side === "top" ? r.top - 8 : r.bottom + 8, left: r.left + r.width / 2, side });
    };
    if (immediate) open();
    else timer.current = setTimeout(open, delayMs);
  };
  const hide = () => {
    clear();
    setPos(null);
  };
  React.useEffect(() => clear, []);

  if (content == null || content === "") return children;

  return (
    <span
      ref={anchorRef}
      className="tt-anchor"
      onMouseEnter={() => show()}
      onMouseLeave={hide}
      onFocus={() => show(true)}
      onBlur={hide}
      onKeyDown={(e) => { if (e.key === "Escape" && pos) { e.stopPropagation(); hide(); } }}
    >
      {React.cloneElement(children, { "aria-describedby": pos ? id : undefined })}
      {pos && typeof document !== "undefined" && createPortal(
        <div
          id={id}
          role="tooltip"
          className="tooltip"
          data-side={pos.side}
          style={{ top: pos.top, left: pos.left }}
        >
          {content}
        </div>,
        document.body,
      )}
    </span>
  );
}

/** A small "?" button that only exists to carry a Tooltip — for labels that
 *  need a sentence of explanation without spending layout on it. */
export function InfoTip({ content, label = "More info" }: { content: React.ReactNode; label?: string }) {
  return (
    <Tooltip content={content}>
      <button type="button" className="info-tip" aria-label={label}>?</button>
    </Tooltip>
  );
}
