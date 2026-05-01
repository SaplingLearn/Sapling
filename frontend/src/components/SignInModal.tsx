"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { IS_LOCAL_MODE } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

const ERROR_COPY: Record<string, string> = {
  not_approved: "Your account is pending approval. We'll email you once an admin lets you in.",
  invalid_domain: "Sign-in is limited to approved school accounts (@bu.edu).",
  google_not_configured: "Google sign-in is not configured on the server. Please contact support.",
  signin_failed: "Sign-in failed. Please try again.",
  session_expired: "Your session has expired. Please sign in again.",
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
  const popupPollRef = useRef<number | null>(null);

  const stopPopupPoll = useCallback(() => {
    if (popupPollRef.current !== null) {
      window.clearInterval(popupPollRef.current);
      popupPollRef.current = null;
    }
  }, []);

  const close = useCallback(() => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 200);
  }, [onClose]);

  useEffect(() => {
    if (!open) {
      setWaiting(false);
      stopPopupPoll();
      return;
    }
    setLocalError(null);
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, [open, stopPopupPoll]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  useEffect(() => {
    if (!open) return;
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return;
      const data = e.data as { type?: string; success?: boolean; error?: string;
        userId?: string; name?: string; avatar?: string; onboardingCompleted?: boolean } | null;
      if (!data || data.type !== "sapling_signin") return;
      stopPopupPoll();
      setWaiting(false);
      if (data.success && data.userId && data.name) {
        setActiveUser(data.userId, data.name, data.avatar || "");
        confirmApproved();
        if (data.onboardingCompleted) {
          router.replace("/dashboard");
        } else {
          sessionStorage.setItem("sapling_onboarding_pending", "1");
        }
        onClose();
      } else {
        setLocalError(data.error || "signin_failed");
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [open, setActiveUser, confirmApproved, router, onClose, stopPopupPoll]);

  useEffect(() => () => stopPopupPoll(), [stopPopupPoll]);

  if (!open) return null;

  const visibleError = localError ?? errorCode ?? null;
  const errorMessage = visibleError
    ? ERROR_COPY[visibleError] ?? `Something went wrong (${visibleError}).`
    : null;

  const signInWithGoogle = () => {
    setLocalError(null);
    if (IS_LOCAL_MODE) {
      setActiveUser("local-user-001", "Local Dev", "");
      confirmApproved();
      router.replace("/dashboard");
      return;
    }
    if (!API_URL) {
      setLocalError("google_not_configured");
      return;
    }
    const url = `${API_URL}/api/auth/google`;
    const w = 520;
    const h = 640;
    const left = Math.max(0, window.screenX + (window.outerWidth - w) / 2);
    const top = Math.max(0, window.screenY + (window.outerHeight - h) / 2);
    const features = `width=${w},height=${h},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes`;
    const popup = window.open(url, "sapling_signin", features);
    if (!popup || popup.closed) {
      window.location.href = url;
      return;
    }
    popup.focus?.();
    popupRef.current = popup;
    setWaiting(true);
    stopPopupPoll();
    popupPollRef.current = window.setInterval(() => {
      if (!popupRef.current || popupRef.current.closed) {
        stopPopupPoll();
        popupRef.current = null;
        setWaiting(false);
      }
    }, 500);
  };

  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center p-4 ${closing ? "modal-backdrop-out" : "modal-backdrop-in"}`}
      style={{ background: "rgba(12,18,26,0.55)" }}
      onClick={close}
    >
      <div
        className={`relative w-full ${closing ? "modal-card-out" : "modal-card-in"}`}
        style={{
          maxWidth: 440,
          background: "linear-gradient(145deg, #d5e8d8 0%, #e8f0e3 45%, #f0ebe0 100%)",
          borderRadius: 24,
          padding: "44px 44px 36px",
          border: "1px solid rgba(255,255,255,0.7)",
          boxShadow: "0 20px 60px rgba(15,23,42,0.18), inset 0 0 0 1px rgba(255,255,255,0.5)",
        }}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Sign in to Sapling"
      >
        <button
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
          <span style={{ fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif", fontWeight: 700, fontSize: 17, color: "#1a5c2a", letterSpacing: "-0.02em" }}>Sapling</span>
        </div>

        <h2 style={{
          margin: 0,
          fontFamily: "var(--font-playfair), 'Playfair Display', Georgia, serif",
          fontSize: 34, lineHeight: 1.05, fontWeight: 600,
          letterSpacing: "-0.02em", color: "#1a1a1a",
        }}>
          Welcome <span style={{ fontStyle: "italic", color: "#1B6C42" }}>back.</span>
        </h2>
        <p style={{ margin: "12px 0 0", fontSize: 14, color: "#4b5563", lineHeight: 1.55 }}>
          Sign in with your school Google account to continue.
        </p>

        {errorMessage && (
          <div style={{
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
            e.currentTarget.style.borderColor = "#1B6C42";
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

        <p style={{ margin: "16px 0 0", fontSize: 11.5, color: "#6b7280", textAlign: "center", lineHeight: 1.5 }}>
          By signing in, you agree to the{" "}
          <a href="/terms" style={{ color: "#1B6C42", textDecoration: "underline" }}>terms</a>
          {" "}and{" "}
          <a href="/privacy" style={{ color: "#1B6C42", textDecoration: "underline" }}>privacy policy</a>.
        </p>
      </div>
    </div>
  );
}
