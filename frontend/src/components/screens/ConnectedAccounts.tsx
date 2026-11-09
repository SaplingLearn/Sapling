"use client";
import React from "react";
import Link from "next/link";
import { TopBar } from "@/components/TopBar";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/components/ToastProvider";
import { GradescopeSyncModal } from "@/components/Gradebook/GradescopeSyncModal";
import {
  getGradescopeStatus,
  deleteGradescopeCredentials,
  type GradescopeStatus,
} from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import { gradescopeConnectionState } from "@/components/Gradebook/gradescopeState";

/**
 * Connected Accounts — settings surface for managing third-party
 * integrations Sapling syncs with. Currently lists Gradescope; future
 * providers (Canvas, Blackboard, Google Classroom) drop in as more
 * <ProviderCard /> entries.
 */
export function ConnectedAccounts() {
  const { userId, userReady } = useUser();
  const toast = useToast();

  const [status, setStatus] = React.useState<GradescopeStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [connectOpen, setConnectOpen] = React.useState(false);
  const [reconnect, setReconnect] = React.useState(false);

  // Latest-wins: the mount load and the post-dialog / post-disconnect
  // reloads can overlap, and an older answer must not repaint the card.
  const refreshSeq = React.useRef(0);
  const refresh = React.useCallback(async () => {
    if (!userId) return;
    const seq = ++refreshSeq.current;
    try {
      const s = await getGradescopeStatus(userId);
      if (seq !== refreshSeq.current) return;
      setStatus(s);
    } catch (e: unknown) {
      if (seq !== refreshSeq.current) return;
      toast.error(`Couldn't load Gradescope status: ${humanizeError(e, "Try again.")}`);
      // Unknown, not "disconnected": a failed read says nothing about the
      // connection, and Connect over saved credentials would be misleading.
      setStatus(null);
    } finally {
      if (seq === refreshSeq.current) setLoading(false);
    }
  }, [userId, toast]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  async function onDisconnect() {
    if (!userId) return;
    if (!window.confirm("Disconnect Gradescope from Sapling? Your course links are kept, so reconnecting resumes syncing.")) return;
    try {
      await deleteGradescopeCredentials(userId);
      toast.info("Gradescope disconnected.");
      await refresh();
    } catch (e: unknown) {
      toast.error(`Couldn't disconnect: ${humanizeError(e, "Try again.")}`);
    }
  }

  if (!userReady || !userId) return null;

  return (
    <>
      <TopBar
        breadcrumb={
          <Link href="/settings" style={{ color: "var(--text-dim)", textDecoration: "none" }}>
            ← Settings
          </Link>
        }
        title="Connected accounts"
      />
      <main
        style={{
          padding: "var(--pad-xl)",
          maxWidth: 900,
          margin: "0 auto",
        }}
      >
        <header style={{ marginBottom: 32 }}>
          <h1
            style={{
              fontFamily: "var(--font-display), 'Aleo', Georgia, serif",
              fontWeight: 500,
              fontSize: "clamp(28px, 3.6vw, 40px)",
              lineHeight: 1.05,
              letterSpacing: "-0.02em",
              color: "var(--text)",
              margin: "0 0 10px",
            }}
          >
            Connected accounts
          </h1>
          <p
            style={{
              fontFamily: "var(--font-serif), var(--font-aleo), 'Aleo', Georgia, serif",
              fontSize: 15,
              lineHeight: 1.6,
              color: "var(--text-dim)",
              margin: 0,
              maxWidth: 640,
            }}
          >
            Link the platforms you already use so Sapling can pull grades,
            assignments, and deadlines into one place. Credentials are
            encrypted at rest; you can disconnect anytime.
          </p>
        </header>

        <ProviderCard
          name="Gradescope"
          domain="gradescope.com"
          loading={loading}
          status={status}
          onConnect={() => { setReconnect(false); setConnectOpen(true); }}
          onReconnect={() => { setReconnect(true); setConnectOpen(true); }}
          onDisconnect={onDisconnect}
        />
      </main>

      <GradescopeSyncModal
        open={connectOpen}
        reconnect={reconnect}
        userId={userId}
        onClose={() => {
          setConnectOpen(false);
          refresh();
        }}
      />
    </>
  );
}

// Copy for the last sync attempt's failure code (routes/gradescope.py). An
// auth failure isn't listed: it surfaces as the needs-reauth state instead.
const SYNC_ERROR_COPY: Record<NonNullable<GradescopeStatus["last_sync_error"]>, string | null> = {
  auth_failed: null,
  fetch_failed: "Gradescope was unavailable",
  write_failed: "grades couldn't be saved",
  partial_write: "some grades couldn't be saved",
};

// ───────────────────────────────────────────────────────────────────────────
// ProviderCard — one row per integration. Same shape regardless of
// connection state; the trailing button(s) and status badge change.
// ───────────────────────────────────────────────────────────────────────────
function ProviderCard({
  name,
  domain,
  loading,
  status,
  onConnect,
  onReconnect,
  onDisconnect,
}: {
  name: string;
  domain: string;
  loading: boolean;
  status: GradescopeStatus | null;
  onConnect: () => void;
  onReconnect: () => void;
  onDisconnect: () => void;
}) {
  // #770: "has a credentials row" is not "connected". Rejected credentials are
  // their own state (reconnect), and a failed status read is unknown.
  const state = status ? gradescopeConnectionState(status) : null;
  const connected = state === "connected" || state === "needs_reauth"; // credentials saved
  const needsReauth = state === "needs_reauth";
  const modeLabel =
    status?.auth_mode === "cookies" ? "session cookies (SSO)" : "password";
  const syncProblem = state === "connected" && status?.last_sync_error
    ? SYNC_ERROR_COPY[status.last_sync_error]
    : null;
  return (
    <section
      style={{
        padding: "20px 24px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-md)",
        display: "flex",
        gap: 24,
        alignItems: "center",
        flexWrap: "wrap",
      }}
    >
      <div style={{ flex: "1 1 280px", minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 10,
            marginBottom: 4,
          }}
        >
          <h2
            style={{
              fontFamily:
                "var(--font-display), 'Aleo', Georgia, serif",
              fontWeight: 500,
              fontSize: 22,
              letterSpacing: "-0.01em",
              color: "var(--text)",
              margin: 0,
            }}
          >
            {name}
          </h2>
          <span
            className="mono"
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              letterSpacing: "-0.01em",
            }}
          >
            {domain}
          </span>
        </div>
        <div
          className="mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: loading
              ? "var(--text-muted)"
              : needsReauth
                ? "var(--err)"
                : connected
                  ? "var(--sap-600)"
                  : "var(--text-muted)",
            marginBottom: 6,
          }}
        >
          {loading
            ? "Checking…"
            : state === null
              ? "Couldn't check status"
              : needsReauth
                ? "Sign-in expired · reconnect needed"
                : connected
                  ? `Credentials saved · ${modeLabel}`
                  : "Not connected"}
        </div>
        <p
          style={{
            fontFamily: "var(--font-serif), var(--font-aleo), 'Aleo', Georgia, serif",
            fontSize: 13,
            lineHeight: 1.55,
            color: "var(--text-dim)",
            margin: 0,
            maxWidth: 520,
          }}
        >
          Pulls assignments and grades from your enrolled courses. For SSO
          use BU SSO + Duo or paste session cookies. Credentials are verified
          when you open the sync setup or pull grades.
        </p>
        {connected && status?.last_synced_at && (
          <div
            className="mono"
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              marginTop: 8,
              letterSpacing: "-0.01em",
            }}
          >
            Last sync · {new Date(status.last_synced_at).toLocaleString()}
          </div>
        )}
        {syncProblem && (
          <div
            className="mono"
            style={{ fontSize: 11, color: "var(--err)", marginTop: 4, letterSpacing: "-0.01em" }}
          >
            Last attempt · {syncProblem}
            {status?.last_attempt_at ? ` · ${new Date(status.last_attempt_at).toLocaleString()}` : ""}
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {connected ? (
          <>
            <button
              type="button"
              className={needsReauth ? "btn btn--primary" : "btn"}
              onClick={onReconnect}
              style={{ padding: "8px 14px", fontSize: 13 }}
            >
              Reconnect
            </button>
            <button
              type="button"
              className="btn btn--danger"
              onClick={onDisconnect}
              style={{ padding: "8px 14px", fontSize: 13 }}
            >
              Disconnect
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            onClick={onConnect}
            disabled={loading}
            style={{ padding: "10px 16px", fontSize: 13 }}
          >
            Connect
          </button>
        )}
      </div>
    </section>
  );
}
