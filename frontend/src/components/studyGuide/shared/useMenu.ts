"use client";
/**
 * A button that opens a short menu (`role="menu"`): the guide's three-dot
 * menu and the home's sort menu.
 *
 * Opening puts the focus on the first item, and Up and Down move it between
 * the items. Escape, or choosing an item, closes the menu and gives the focus
 * back to the button. A press outside, or the focus leaving with Tab, closes
 * it and leaves the focus where it went.
 */
import React from "react";

const BUTTON = '[aria-haspopup="menu"]';
const ITEMS = '[role^="menuitem"]:not(:disabled)';

export function useMenu() {
  const [open, setOpen] = React.useState(false);
  /** Goes on the element that holds the button and the menu. */
  const owner = React.useRef<HTMLDivElement>(null);
  const toggle = React.useCallback(() => setOpen(now => !now), []);
  const close = React.useCallback(() => {
    setOpen(false);
    owner.current?.querySelector<HTMLElement>(BUTTON)?.focus();
  }, []);

  React.useEffect(() => {
    if (!open) return;
    owner.current?.querySelector<HTMLElement>(ITEMS)?.focus();
    const onPress = (event: PointerEvent) => {
      if (!owner.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", onPress);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPress);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  /** Up and Down move through the items, round the ends. */
  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    const items = Array.from(owner.current?.querySelectorAll<HTMLElement>(ITEMS) ?? []);
    if (!open || step === 0 || items.length === 0) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLElement);
    const from = at < 0 && step < 0 ? 0 : at;
    items[(from + step + items.length) % items.length].focus();
  };

  /** The focus went to something else on the page. An item that is removed
   *  while it has the focus blurs to nothing, and that keeps the menu open. */
  const onBlur = (event: React.FocusEvent) => {
    if (event.relatedTarget instanceof Node && !owner.current?.contains(event.relatedTarget)) setOpen(false);
  };

  return { open, toggle, close, owner, onKeyDown, onBlur };
}
