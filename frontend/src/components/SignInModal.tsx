"use client";
import { useCallback, useEffect, useState } from "react";
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

  const close = useCallback(() => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 200);
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  const errorMessage = errorCode
    ? ERROR_COPY[errorCode] ?? `Something went wrong (${errorCode}).`
    : null;

  const signInWithGoogle = () => {
    if (IS_LOCAL_MODE) {
      setActiveUser("local-user-001", "Local Dev", "");
      confirmApproved();
      router.replace("/dashboard");
      return;
    }
    window.location.href = `${API_URL}/api/auth/google`;
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
          style={{
            marginTop: 28,
            width: "100%", padding: "14px 16px", borderRadius: 12,
            background: "#fff", color: "#1a1a1a",
            fontSize: 14, fontWeight: 600, letterSpacing: "0.01em",
            border: "1.5px solid rgba(107,114,128,0.25)",
            cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            transition: "all 0.18s",
            boxShadow: "0 4px 14px rgba(15,23,42,0.06)",
          }}
          onMouseEnter={e => {
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
          Continue with Google
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
