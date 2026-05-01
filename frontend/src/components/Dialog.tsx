'use client';

import { useEffect, useRef, useState, useCallback, useId } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const SIZE_WIDTH: Record<string, string> = {
  sm: '420px',
  md: '520px',
  lg: '640px',
  xl: '760px',
};

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  labelledBy?: string;
  title?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  dismissible?: boolean;
  showCloseButton?: boolean;
  padding?: string;
  zIndex?: number;
}

export default function Dialog({
  open,
  onClose,
  children,
  labelledBy,
  title,
  size = 'md',
  dismissible = true,
  showCloseButton = true,
  padding = '28px',
  zIndex = 100,
}: DialogProps) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<Element | null>(null);
  const autoTitleId = useId();
  const effectiveLabelledBy = labelledBy ?? (title ? autoTitleId : undefined);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!open) { setVisible(false); return; }
    previousFocusRef.current = document.activeElement;
    const raf = requestAnimationFrame(() => setVisible(true));

    const focusTimer = setTimeout(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelector<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      (focusable ?? panel).focus();
    }, 20);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(focusTimer);
      const prev = previousFocusRef.current;
      if (prev instanceof HTMLElement) prev.focus();
    };
  }, [open]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!open) return;

    if (e.key === 'Escape' && dismissible) {
      e.stopPropagation();
      onClose();
      return;
    }

    if (e.key === 'Tab' && panelRef.current) {
      const panel = panelRef.current;
      const focusable = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
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

  if (!mounted || !open) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={effectiveLabelledBy}
      onKeyDown={handleKeyDown}
      style={{
        position: 'fixed',
        inset: 0,
        background: visible ? 'rgba(15,23,42,0.45)' : 'rgba(15,23,42,0)',
        zIndex,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
        transition: 'background 220ms var(--ease-out)',
      }}
      onClick={e => { if (dismissible && e.target === e.currentTarget) onClose(); }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        style={{
          background: 'var(--bg-panel)',
          borderRadius: 'var(--radius-lg)',
          padding,
          width: SIZE_WIDTH[size],
          maxWidth: 'min(95vw, calc(100vw - 32px))',
          maxHeight: 'calc(100vh - 48px)',
          overflowY: 'auto',
          position: 'relative',
          border: '1px solid var(--border)',
          boxShadow: 'var(--shadow-lg)',
          fontFamily: UI_FONT,
          color: 'var(--text)',
          opacity: visible ? 1 : 0,
          transform: visible ? 'scale(1) translateY(0)' : 'scale(0.96) translateY(8px)',
          transition: 'opacity 220ms var(--ease-out), transform 220ms var(--ease-out)',
          outline: 'none',
        }}
      >
        {title && (
          <h2
            id={effectiveLabelledBy}
            style={{
              fontSize: '18px',
              fontWeight: 700,
              color: 'var(--text)',
              margin: '0 0 16px',
              paddingRight: showCloseButton && dismissible ? '36px' : 0,
            }}
          >
            {title}
          </h2>
        )}
        {showCloseButton && dismissible && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            style={{
              position: 'absolute',
              top: '14px',
              right: '14px',
              width: '44px',
              height: '44px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'none',
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              color: 'var(--text-muted)',
              padding: 0,
            }}
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
