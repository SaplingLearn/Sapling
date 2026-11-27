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
import {
  gradescopeConnectionState,
  gradescopeModeLabel,
  gradescopeReauthShort,
} from "@/components/Gradebook/gradescopeState";
import { cn } from "@/lib/cn";

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
          <Link href="/settings" className="text-text-dim no-underline">
            ← Settings
          </Link>
        }
        title="Connected accounts"
      />
      <main
        className="p-(--pad-xl) max-w-225 my-0 mx-auto"
      >
        <header className="mb-8">
          <h1
            className="font-display font-medium text-[length:clamp(28px,_3.6vw,_40px)] leading-[1.05] tracking-[-0.02em] text-text mt-0 mx-0 mb-2.5"
          >
            Connected accounts
          </h1>
          <p
            className="font-serif text-[15px] leading-[1.6] text-text-dim m-0 max-w-160"
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
  const modeLabel = status ? gradescopeModeLabel(status) : "";
  const syncProblem = state === "connected" && status?.last_sync_error
    ? SYNC_ERROR_COPY[status.last_sync_error]
    : null;
  return (
    <section
      className="py-5 px-6 bg-bg-panel border border-border rounded-md flex gap-6 items-center flex-wrap"
    >
      <div className="flex-[1_1_280px] min-w-0">
        <div
          className="flex items-baseline gap-2.5 mb-1"
        >
          <h2
            className="font-display font-medium text-2xl tracking-[-0.01em] text-text m-0"
          >
            {name}
          </h2>
          <span
            className="mono text-xs text-text-muted tracking-[-0.01em]"
          >
            {domain}
          </span>
        </div>
        <div
          className="mono text-md mb-1.5"
          style={{ color: loading
              ? "var(--text-muted)"
              : needsReauth
                ? "var(--err)"
                : connected
                  ? "var(--sap-600)"
                  : "var(--text-muted)" }}
        >
          {loading
            ? "Checking…"
            : state === null
              ? "Couldn't check status"
              : needsReauth
                ? (status ? gradescopeReauthShort(status) : "")
                : connected
                  ? `Session saved · ${modeLabel}`
                  : "Not connected"}
        </div>
        <p
          className="font-serif text-md leading-[1.55] text-text-dim m-0 max-w-130"
        >
          Pulls assignments and grades from your enrolled courses. For SSO
          use BU SSO + Duo or paste session cookies. Credentials are verified
          when you open the sync setup or pull grades.
        </p>
        {connected && status?.last_synced_at && (
          <div
            className="mono text-xs text-text-muted mt-2 tracking-[-0.01em]"
          >
            Last sync · {new Date(status.last_synced_at).toLocaleString()}
          </div>
        )}
        {syncProblem && (
          <div
            className="mono text-xs text-err mt-1 tracking-[-0.01em]"
          >
            Last attempt · {syncProblem}
            {status?.last_attempt_at ? ` · ${new Date(status.last_attempt_at).toLocaleString()}` : ""}
          </div>
        )}
      </div>

      <div className="flex gap-2.5 flex-wrap">
        {connected ? (
          <>
            <button
              type="button"
              className={cn(needsReauth ? "btn btn--primary" : "btn", "py-2 px-3.5 text-md")}
              onClick={onReconnect}
            >
              Reconnect
            </button>
            <button
              type="button"
              className="btn btn--danger py-2 px-3.5 text-md"
              onClick={onDisconnect}
            >
              Disconnect
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn btn--primary py-2.5 px-4 text-md"
            onClick={onConnect}
            disabled={loading}
          >
            Connect
          </button>
        )}
      </div>
    </section>
  );
}
