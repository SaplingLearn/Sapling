"use client";
/**
 * The Notes page's own toast: the dark centred pill the design draws, not the
 * app's tinted corner toast.
 *
 * The page sits on paper with no chrome of its own, and every message it has
 * is about the document under the cursor ("Link copied", "Replaced the
 * selected text") — so the design puts them where the eye already is. The
 * Library's undo toast is the same pill, for the same reason.
 */
import React from "react";

/** The design's `flash()` holds a message for this long. */
export const TOAST_MS = 2400;

export function NotesToast({ message }: { message: string }) {
  return (
    <div role="status" data-testid="notes-toast" style={{
      position: "absolute", left: "50%", bottom: 32, transform: "translateX(-50%)",
      zIndex: 30, padding: "12px 18px", borderRadius: 12, background: "#1A1814",
      color: "#FFFFFF", fontSize: 15, fontWeight: 600,
      boxShadow: "0 10px 28px rgba(25,37,11,0.25)",
    }}>{message}</div>
  );
}

/** One message at a time, cleared on its own. */
export function useNotesToast(): {
  message: string | null;
  flash: (message: string) => void;
} {
  const [message, setMessage] = React.useState<string | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const flash = React.useCallback((next: string) => {
    if (timer.current) clearTimeout(timer.current);
    setMessage(next);
    timer.current = setTimeout(() => setMessage(null), TOAST_MS);
  }, []);

  return { message, flash };
}
