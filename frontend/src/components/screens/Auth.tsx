"use client";
import React, { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { IS_LOCAL_MODE } from "@/lib/api";

// Empty fallback lets the browser use a same-origin /api/... path, which
// Next.js rewrites to BACKEND_URL server-side. Hardcoding localhost here
// would break production deploys that forgot to set NEXT_PUBLIC_API_URL.
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

function AuthInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setActiveUser, confirmApproved } = useUser();
  const error = searchParams.get("error");
  const errorMessage = error ? ERROR_COPY[error] ?? `Something went wrong (${error}).` : null;

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
      style={{
        width: "100vw",
        height: "100vh",
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        background: "var(--bg)",
      }}
    >
      <div
        style={{
          background: "var(--sap-700)",
          color: "#fff",
          padding: "60px 48px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <button
          type="button"
          onClick={() => router.push("/")}
          aria-label="Back to home"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "transparent",
            border: 0,
            padding: 0,
            color: "inherit",
            cursor: "pointer",
          }}
        >
          <svg width="28" height="28" viewBox="0 0 24 24">
            <path d="M12 22 Q 5 15 5 9 Q 5 3 12 3 Q 19 3 19 9 Q 19 15 12 22 Z" fill="#fff" opacity={0.15} />
            <path
              d="M12 22 V 10 M12 13 Q 8 10 7 7 M12 14 Q 16 11 17 8"
              stroke="#fff"
              strokeWidth={1.5}
              fill="none"
              strokeLinecap="round"
            />
          </svg>
          <span className="h-serif" style={{ fontSize: 22, fontWeight: 500 }}>Sapling</span>
        </button>
        <div>
          <div className="h-serif" style={{ fontSize: 48, fontWeight: 500, lineHeight: 1.1, maxWidth: 440 }}>
            Your mind,
            <br />
            quietly mapped.
          </div>
          <div style={{ fontSize: 15, color: "rgba(255,255,255,0.7)", marginTop: 20, maxWidth: 380, lineHeight: 1.55 }}>
            An AI tutor that doesn&apos;t just answer — it asks the right questions, remembers what you know, and grows
            your knowledge graph session by session.
          </div>
        </div>
        <div aria-hidden style={{ height: 1 }} />
        <svg
          style={{ position: "absolute", right: -80, bottom: -60, opacity: 0.08 }}
          width="360"
          height="360"
          viewBox="0 0 100 100"
        >
          <path d="M50 100 Q 20 60 20 35 Q 20 5 50 5 Q 80 5 80 35 Q 80 60 50 100 Z" fill="#fff" />
        </svg>
      </div>

      <div style={{ padding: 60, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: "100%", maxWidth: 380 }}>
          <div className="h-serif" style={{ fontSize: 32, fontWeight: 500, marginBottom: 8 }}>Welcome back</div>
          <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 28 }}>
            Sign in with your school Google account to continue.
          </div>

          {errorMessage && (
            <div
              style={{
                background: "var(--err-soft)",
                color: "var(--err)",
                padding: "10px 12px",
                borderRadius: "var(--r-sm)",
                fontSize: 13,
                marginBottom: 14,
              }}
            >
              {errorMessage}
            </div>
          )}

          <button
            className="btn"
            style={{ width: "100%", justifyContent: "center", padding: 12, fontSize: 14 }}
            onClick={signInWithGoogle}
          >
            <svg width="16" height="16" viewBox="0 0 48 48">
              <path
                fill="#4285f4"
                d="M45 24c0-1.5-.1-2.9-.4-4.3H24v8.1h11.8c-.5 2.8-2 5.1-4.3 6.7v5.6h7c4.1-3.8 6.5-9.3 6.5-16.1z"
              />
              <path
                fill="#34a853"
                d="M24 46c5.8 0 10.7-1.9 14.2-5.2l-7-5.6c-1.9 1.3-4.4 2.1-7.2 2.1-5.5 0-10.2-3.7-11.9-8.7H5v5.7C8.5 41.7 15.7 46 24 46z"
              />
              <path
                fill="#fbbc04"
                d="M12.1 28.5c-.4-1.3-.7-2.6-.7-4s.3-2.7.7-4v-5.7H5C3.5 18 3 20.9 3 24s.5 6 2 8.5l7.1-4z"
              />
              <path
                fill="#ea4335"
                d="M24 10.5c3.1 0 5.9 1.1 8.1 3.2l6.1-6.1C34.6 4.1 29.7 2 24 2 15.7 2 8.5 6.3 5 12.8L12.1 18c1.7-4.9 6.4-7.5 11.9-7.5z"
              />
            </svg>
            Continue with Google
          </button>

          <div style={{ textAlign: "center", marginTop: 18, fontSize: 12, color: "var(--text-muted)" }}>
            By signing in, you agree to the terms and privacy policy.
          </div>
        </div>
      </div>
    </div>
  );
}

export function Auth() {
  return (
    <Suspense fallback={<div style={{ minHeight: "100vh", background: "var(--bg)" }} />}>
      <AuthInner />
    </Suspense>
  );
}
