'use client';

import { useEffect, useRef, useState, useCallback, useId } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useScrollLock } from '@/lib/useScrollLock';
import { cn } from "@/lib/cn";

const SIZE_WIDTH: Record<string, string> = {
  sm: '420px',
  md: '520px',
  lg: '640px',
  xl: '760px',
};

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Everything a modal overlay has to get right that isn't its shape: portal
 * readiness, the enter-transition flag, scroll-lock, initial focus, focus
 * restore on close, Escape, and the Tab trap.
 *
 * Extracted from `Dialog` unchanged so `<Sheet>` (the side-anchored panel the
 * quiz's "Ask about this" needs, #537) inherits the exact same behaviour
 * rather than a second, subtly different implementation of it. `Dialog` and
 * `Sheet` differ only in where the panel sits and how it animates in.
 */
export function useOverlayBehaviour({
  open,
  onClose,
  dismissible = true,
  initialFocusRef,
}: {
  open: boolean;
  onClose: () => void;
  dismissible?: boolean;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
}) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<Element | null>(null);

  // Lock the scrolling container while open so background content doesn't
  // scroll-bleed behind the overlay (matches the other portal modals).
  useScrollLock(open);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!open) { setVisible(false); return; }
    previousFocusRef.current = document.activeElement;
    const raf = requestAnimationFrame(() => setVisible(true));

    const focusTimer = setTimeout(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const preferred = initialFocusRef?.current;
      if (preferred) { preferred.focus(); return; }
      const focusable = panel.querySelector<HTMLElement>(FOCUSABLE);
      (focusable ?? panel).focus();
    }, 20);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(focusTimer);
      const prev = previousFocusRef.current;
      if (prev instanceof HTMLElement) prev.focus();
    };
  }, [open, initialFocusRef]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!open) return;

    if (e.key === 'Escape' && dismissible) {
      e.stopPropagation();
      onClose();
      return;
    }

    if (e.key === 'Tab' && panelRef.current) {
      const panel = panelRef.current;
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(FOCUSABLE)
      ).filter(el => !el.hasAttribute('data-focus-skip'));
      if (focusable.length === 0) { e.preventDefault(); return; }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }, [open, dismissible, onClose]);

  return { mounted, visible, panelRef, onKeyDown };
}

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  labelledBy?: string;
  title?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  /**
   * Panel width as a CSS length (e.g. `min(980px, calc(100vw - 32px))`), for
   * a dialog wider than the `size` presets. Replaces the preset width only:
   * the panel's max-width still applies, so it never outgrows a small screen.
   */
  width?: string;
  dismissible?: boolean;
  showCloseButton?: boolean;
  padding?: string;
  zIndex?: number;
  /**
   * Element to focus on open. Without it focus lands on the first focusable
   * node in the panel — the close button, since it precedes {children} in
   * the DOM. Form dialogs pass their first field instead. `autoFocus` can't
   * do this job: React fires it at mount, before the focus pass below.
   */
  initialFocusRef?: React.RefObject<HTMLElement | null>;
}

export default function Dialog({
  open,
  onClose,
  children,
  labelledBy,
  title,
  size = 'md',
  width,
  dismissible = true,
  showCloseButton = true,
  padding = '28px',
  zIndex = 100,
  initialFocusRef,
}: DialogProps) {
  const autoTitleId = useId();
  const effectiveLabelledBy = labelledBy ?? (title ? autoTitleId : undefined);
  const { mounted, visible, panelRef, onKeyDown: handleKeyDown } = useOverlayBehaviour({
    open,
    onClose,
    dismissible,
    initialFocusRef,
  });

  if (!mounted || !open) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={effectiveLabelledBy}
      onKeyDown={handleKeyDown}
      className={cn("fixed inset-0 flex items-center justify-center p-5 [transition:background_220ms_var(--ease)]", visible ? "bg-[rgba(15,23,42,0.45)]" : "bg-[rgba(15,23,42,0)]")} style={{ zIndex }}
      onClick={e => { if (dismissible && e.target === e.currentTarget) onClose(); }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cn("bg-bg-panel rounded-lg max-w-[min(95vw,_calc(100vw_-_32px))] max-h-[calc(100vh_-_48px)] overflow-y-auto relative border border-border shadow-lg font-sans text-text [transition:opacity_220ms_var(--ease),_transform_220ms_var(--ease)] outline-none", visible ? "opacity-100" : "opacity-0", visible ? "[transform:scale(1)_translateY(0)]" : "[transform:scale(0.96)_translateY(8px)]")} style={{ padding, width: width ?? SIZE_WIDTH[size] }}
      >
        {title && (
          <h2
            id={effectiveLabelledBy}
            className={cn("text-xl font-bold text-text mt-0 mx-0 mb-4", showCloseButton && dismissible ? "pr-9" : "pr-0")}
          >
            {title}
          </h2>
        )}
        {showCloseButton && dismissible && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="absolute top-3.5 right-3.5 w-11 h-11 flex items-center justify-center [background:none] border-0 rounded-sm cursor-pointer text-text-muted p-0"
          >
            <X size={16} />
          </button>
        )}
        {children}
      </div>
    </div>,
    document.body
  );
}
