"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type ToastVariant = "default" | "success" | "error" | "info" | "warn";

export interface ToastOptions {
  variant?: ToastVariant;
  duration?: number | null;
}

interface Toast {
  id: number;
  content: React.ReactNode;
  variant: ToastVariant;
  duration: number | null;
  createdAt: number;
}

interface ToastContextValue {
  show: (content: React.ReactNode, options?: ToastOptions) => number;
  dismiss: (id: number) => void;
  success: (content: React.ReactNode, options?: ToastOptions) => number;
  error: (content: React.ReactNode, options?: ToastOptions) => number;
  info: (content: React.ReactNode, options?: ToastOptions) => number;
  warn: (content: React.ReactNode, options?: ToastOptions) => number;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let toastCounter = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [mounted, setMounted] = useState(false);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => { setMounted(true); }, []);

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const show = useCallback((content: React.ReactNode, options?: ToastOptions) => {
    const id = ++toastCounter;
    const duration = options?.duration === undefined ? 5000 : options.duration;
    const variant = options?.variant ?? "default";
    setToasts(prev => [...prev, { id, content, variant, duration, createdAt: Date.now() }]);
    if (duration !== null && duration > 0) {
      const timer = setTimeout(() => dismiss(id), duration);
      timers.current.set(id, timer);
    }
    return id;
  }, [dismiss]);

  const value = useMemo<ToastContextValue>(() => ({
    show,
    dismiss,
    success: (c, o) => show(c, { ...o, variant: "success" }),
    error: (c, o) => show(c, { ...o, variant: "error" }),
    info: (c, o) => show(c, { ...o, variant: "info" }),
    warn: (c, o) => show(c, { ...o, variant: "warn" }),
  }), [show, dismiss]);

  useEffect(() => () => {
    timers.current.forEach(t => clearTimeout(t));
    timers.current.clear();
  }, []);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {mounted && createPortal(<ToastStack toasts={toasts} onDismiss={dismiss} />, document.body)}
    </ToastContext.Provider>
  );
}

function variantStyles(variant: ToastVariant): React.CSSProperties {
  switch (variant) {
    case "success":
      return { background: "var(--accent-soft)", color: "var(--accent)", borderColor: "var(--accent-border)" };
    case "error":
      return { background: "var(--err-soft)", color: "var(--err)", borderColor: "transparent" };
    case "warn":
      return { background: "var(--warn-soft)", color: "var(--warn)", borderColor: "transparent" };
    case "info":
      return { background: "var(--info-soft)", color: "var(--info)", borderColor: "transparent" };
    default:
      return { background: "var(--bg-panel)", color: "var(--text)", borderColor: "var(--border-strong)" };
  }
}

function ToastStack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      style={{
        position: "fixed",
        top: 16,
        right: 16,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        zIndex: 1000,
        pointerEvents: "none",
        maxWidth: "calc(100vw - 32px)",
      }}
    >
      {toasts.map(t => (
        <div
          key={t.id}
          className="fade-in"
          role="status"
          style={{
            pointerEvents: "auto",
            padding: "10px 12px",
            borderRadius: "var(--r-md)",
            border: "1px solid",
            boxShadow: "var(--shadow-md)",
            fontSize: 13,
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            minWidth: 220,
            maxWidth: 360,
            ...variantStyles(t.variant),
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>{t.content}</div>
          <button
            onClick={() => onDismiss(t.id)}
            aria-label="Dismiss notification"
            style={{
              color: "inherit",
              opacity: 0.6,
              fontSize: 16,
              lineHeight: 1,
              padding: 2,
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
