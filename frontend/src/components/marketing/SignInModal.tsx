"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useScrollLock } from "@/lib/useScrollLock";
import { HeroCard } from "@/components/marketing/HeroCard";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const POPUP_TIMEOUT_MS = 3 * 60 * 1000;

const ERROR_COPY: Record<string, string> = {
  not_approved: "Your account is pending approval. We'll email you once an admin lets you in.",
  invalid_domain: "Sign-in is limited to approved school accounts (@bu.edu).",
  google_not_configured: "Google sign-in is not configured on the server. Please contact support.",
  signin_failed: "Sign-in failed. Please try again.",
  session_expired: "Your session has expired. Please sign in again.",
  env_misconfig: "This environment is misconfigured and can't sign you in. Please contact support.",
  revoked: "Your access has been revoked.",
  oauth_denied: "Sign-in was cancelled.",
  unknown: "Something went wrong. Please try again.",
};

interface SignInModalProps {
  open: boolean;
  onClose: () => void;
  errorCode?: string | null;
}

export default function SignInModal({ open, onClose, errorCode }: SignInModalProps) {
  const router = useRouter();
  const { setActiveUser, confirmApproved } = useUser();
  const [closing, setClosing] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const popupRef = useRef<Window | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const watchdogRef = useRef<number | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<Element | null>(null);

  const cleanupPopupListeners = useCallback(() => {
    if (channelRef.current) {
      try { channelRef.current.close(); } catch {}
      channelRef.current = null;
    }
    if (watchdogRef.current !== null) {
      window.clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
    // Best effort — COOP may have severed the handle, but harmless to try.
    if (popupRef.current) {
      try { popupRef.current.close(); } catch {}
      popupRef.current = null;
    }
  }, []);

  const close = useCallback(() => {
    cleanupPopupListeners();
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 200);
  }, [onClose, cleanupPopupListeners]);

  useScrollLock(open);

  useEffect(() => {
    if (!open) {
      setWaiting(false);
      cleanupPopupListeners();
      return;
    }
    setLocalError(null);
  }, [open, cleanupPopupListeners]);

  useEffect(() => () => cleanupPopupListeners(), [cleanupPopupListeners]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { close(); return; }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = Array.from(
          panelRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        );
        if (focusable.length === 0) { e.preventDefault(); return; }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  // Move focus into the modal on open; restore it to the trigger on close.
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement;
    const focusTimer = setTimeout(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelector<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      (focusable ?? panel).focus();
    }, 20);
    return () => {
      clearTimeout(focusTimer);
      const prev = previousFocusRef.current;
      if (prev instanceof HTMLElement) prev.focus();
    };
  }, [open]);

  if (!open) return null;

  const visibleError = localError ?? errorCode ?? null;
  const errorMessage = visibleError
    ? ERROR_COPY[visibleError] ?? `Something went wrong (${visibleError}).`
    : null;

  const signInWithGoogle = () => {
    setLocalError(null);

    // An empty API_URL is the valid same-origin config (a cross-origin value
    // drops the session cookie), so we don't guard against it here. The
    // redirect below resolves to the same-origin path `/api/auth/google`,
    // which Next.js proxies to the backend.

    // BroadcastChannel-based popup flow. We don't depend on window.opener:
    // COOP severs the opener handle the moment the popup hops to a
    // cross-origin URL (Railway, then Google). Instead the callback page
    // broadcasts the result on a per-attempt channel keyed by popup_id.
    const supportsPopup =
      typeof BroadcastChannel !== "undefined" &&
      typeof crypto !== "undefined" &&
      typeof crypto.randomUUID === "function";

    const sameTabUrl = `${API_URL}/api/auth/google`;

    if (!supportsPopup) {
      setWaiting(true);
      window.location.href = sameTabUrl;
      return;
    }

    const popupId = crypto.randomUUID();
    const popupUrl = `${API_URL}/api/auth/google?popup_id=${encodeURIComponent(popupId)}`;

    cleanupPopupListeners();
    const channel = new BroadcastChannel(`sapling_signin:${popupId}`);
    channelRef.current = channel;
    channel.onmessage = (event: MessageEvent) => {
      const data = event.data as {
        type?: string; success?: boolean; error?: string;
        userId?: string; name?: string; avatar?: string;
        onboardingCompleted?: boolean; profileConfirmed?: boolean;
      } | null;
      if (!data || data.type !== "sapling_signin") return;
      cleanupPopupListeners();
      setWaiting(false);
      if (data.success && data.userId) {
        // Upstream (feat/landing-v5-port) passes a 4th `{ persist }` option
        // here (#191: the callback reports whether /me confirmed the identity).
        // That option only exists on that branch's UserContext, whose wider
        // change also adds app-wide session recovery and shell-route redirects.
        // This branch ports the public landing ONLY, so it keeps staging's
        // 3-arg setActiveUser rather than changing auth for every screen.
        // Re-add the option in the same commit that brings that UserContext over.
        setActiveUser(data.userId, data.name || "", data.avatar || "");
        confirmApproved();
        if (data.onboardingCompleted) {
          router.replace("/dashboard");
        } else {
          router.replace("/onboarding");
        }
        onClose();
      } else {
        setLocalError(data.error || "signin_failed");
      }
    };

    const w = 520;
    const h = 640;
    const left = Math.max(0, window.screenX + (window.outerWidth - w) / 2);
    const top = Math.max(0, window.screenY + (window.outerHeight - h) / 2);
    const features = `width=${w},height=${h},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes`;
    const popup = window.open(popupUrl, "sapling_signin", features);
    if (!popup || popup.closed) {
      // Pop-up blocker / user setting. Fall back to same-tab redirect.
      cleanupPopupListeners();
      setWaiting(true);
      window.location.href = sameTabUrl;
      return;
    }
    popupRef.current = popup;
    try { popup.focus(); } catch {}
    setWaiting(true);

    // We can't reliably observe popup.closed under COOP, so set a watchdog
    // that resets the modal if the user abandons the flow.
    watchdogRef.current = window.setTimeout(() => {
      cleanupPopupListeners();
      setWaiting(false);
    }, POPUP_TIMEOUT_MS);
  };

  const cancelSignIn = () => {
    cleanupPopupListeners();
    setWaiting(false);
  };

  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center p-4 ${closing ? "modal-backdrop-out" : "modal-backdrop-in"}`}
      style={{ background: "rgba(12,18,26,0.55)" }}
      onClick={close}
    >
      <HeroCard
        ref={panelRef}
        tabIndex={-1}
        className={`relative w-full ${closing ? "modal-card-out" : "modal-card-in"}`}
        style={{
          maxWidth: 440,
          padding: "44px 44px 36px",
        }}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Sign in to Sapling"
        data-testid="signin-modal"
      >
        <button
          data-testid="signin-close"
          onClick={close}
          aria-label="Close dialog"
          style={{
            position: "absolute", top: 14, right: 14,
            width: 32, height: 32, borderRadius: 16,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#4b5563", fontSize: 20, lineHeight: 1,
            background: "none", border: "none", cursor: "pointer",
            transition: "background 0.15s",
          }}
          onMouseEnter={e => (e.currentTarget.style.background = "rgba(107,114,128,0.1)")}
          onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
        >×</button>

        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 24 }}>
          <img src="/sapling-icon.svg" alt="Sapling" style={{ width: 22, height: 22 }} />
          <span style={{ fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif", fontWeight: 700, fontSize: 17, color: "var(--brand-forest)", letterSpacing: "-0.02em" }}>Sapling</span>
        </div>

        <h2 style={{
          margin: 0,
          fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
          fontSize: 34, lineHeight: 1.05, fontWeight: 600,
          letterSpacing: "-0.02em", color: "#1a1a1a",
        }}>
          Welcome <span style={{ fontStyle: "italic", color: "var(--brand-forest)" }}>back.</span>
        </h2>
        <p style={{ margin: "12px 0 0", fontSize: 14, color: "#4b5563", lineHeight: 1.55 }}>
          Sign in with your school Google account to continue.
        </p>

        {errorMessage && (
          <div data-testid="signin-error" style={{
            marginTop: 20,
            background: "rgba(220,38,38,0.08)",
            color: "#b91c1c",
            padding: "10px 12px",
            borderRadius: 10,
            fontSize: 13,
            border: "1px solid rgba(220,38,38,0.2)",
          }}>
            {errorMessage}
          </div>
        )}

        <button
          type="button"
          data-testid="signin-google-button"
          onClick={signInWithGoogle}
          disabled={waiting}
          style={{
            marginTop: 28,
            width: "100%", padding: "14px 16px", borderRadius: 12,
            background: "#fff", color: "#1a1a1a",
            fontSize: 14, fontWeight: 600, letterSpacing: "0.01em",
            border: "1.5px solid rgba(107,114,128,0.25)",
            cursor: waiting ? "wait" : "pointer",
            opacity: waiting ? 0.7 : 1,
            display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            transition: "all 0.18s",
            boxShadow: "0 4px 14px rgba(15,23,42,0.06)",
          }}
          onMouseEnter={e => {
            if (waiting) return;
            e.currentTarget.style.borderColor = "var(--brand-forest)";
            e.currentTarget.style.boxShadow = "0 6px 18px rgba(27,108,66,0.15)";
          }}
          onMouseLeave={e => {
            e.currentTarget.style.borderColor = "rgba(107,114,128,0.25)";
            e.currentTarget.style.boxShadow = "0 4px 14px rgba(15,23,42,0.06)";
          }}
        >
          <svg width="18" height="18" viewBox="0 0 48 48">
            <path fill="#4285f4" d="M45 24c0-1.5-.1-2.9-.4-4.3H24v8.1h11.8c-.5 2.8-2 5.1-4.3 6.7v5.6h7c4.1-3.8 6.5-9.3 6.5-16.1z" />
            <path fill="#34a853" d="M24 46c5.8 0 10.7-1.9 14.2-5.2l-7-5.6c-1.9 1.3-4.4 2.1-7.2 2.1-5.5 0-10.2-3.7-11.9-8.7H5v5.7C8.5 41.7 15.7 46 24 46z" />
            <path fill="#fbbc04" d="M12.1 28.5c-.4-1.3-.7-2.6-.7-4s.3-2.7.7-4v-5.7H5C3.5 18 3 20.9 3 24s.5 6 2 8.5l7.1-4z" />
            <path fill="#ea4335" d="M24 10.5c3.1 0 5.9 1.1 8.1 3.2l6.1-6.1C34.6 4.1 29.7 2 24 2 15.7 2 8.5 6.3 5 12.8L12.1 18c1.7-4.9 6.4-7.5 11.9-7.5z" />
          </svg>
          {waiting ? "Waiting for Google…" : "Continue with Google"}
        </button>

        {waiting && (
          <button
            type="button"
            data-testid="signin-cancel"
            onClick={cancelSignIn}
            style={{
              marginTop: 10,
              width: "100%",
              padding: "6px 0",
              background: "none",
              border: "none",
              color: "#6b7280",
              fontSize: 12.5,
              cursor: "pointer",
              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            }}
          >
            Cancel
          </button>
        )}

        <p style={{ margin: "16px 0 0", fontSize: 11.5, color: "#6b7280", textAlign: "center", lineHeight: 1.5 }}>
          By signing in, you agree to the{" "}
          <a href="/terms" style={{ color: "var(--brand-forest)", textDecoration: "underline" }}>terms</a>
          {" "}and{" "}
          <a href="/privacy" style={{ color: "var(--brand-forest)", textDecoration: "underline" }}>privacy policy</a>.
        </p>
      </HeroCard>
    </div>
  );
}
