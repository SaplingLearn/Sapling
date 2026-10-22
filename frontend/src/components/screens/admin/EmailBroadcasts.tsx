"use client";
import React from "react";

import Dialog from "@/components/Dialog";
import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import {
  adminEmailAudiences,
  adminEmailStatus,
  adminListBroadcasts,
  adminSendBroadcast,
  adminSendTestBroadcast,
} from "@/lib/api";
import type { EmailAudience, EmailAudienceKey, EmailBroadcast, EmailStatus } from "@/lib/types";

import { fieldStyle, tdStyle, thStyle } from "./adminStyles";
import { EmailBodyPreview } from "./emailPreview";
import { EmailNotConfiguredBanner } from "./EmailNotConfiguredBanner";

/**
 * Admin "Email" tab: compose a plain-text broadcast, preview it, send a test
 * to yourself, then send it to an audience behind a typed confirmation. The
 * send is accepted (202) and delivered in the background, so the history
 * table polls while any broadcast is still `sending`.
 */

export const SUBJECT_MAX = 200;
export const BODY_MAX = 20000;
export const POLL_MS = 5000;

const BROADCAST_CHIP: Record<EmailBroadcast["status"], string> = {
  sending: "chip chip--info",
  sent: "chip chip--accent",
  failed: "chip chip--warn",
};

function people(n: number) {
  return `${n} ${n === 1 ? "person" : "people"}`;
}

export function EmailBroadcastsTab() {
  const toast = useToast();
  const [loading, setLoading] = React.useState(true);
  const [status, setStatus] = React.useState<EmailStatus | null>(null);
  const [audiences, setAudiences] = React.useState<EmailAudience[]>([]);
  const [broadcasts, setBroadcasts] = React.useState<EmailBroadcast[]>([]);

  const [subject, setSubject] = React.useState("");
  const [body, setBody] = React.useState("");
  const [audience, setAudience] = React.useState<EmailAudienceKey | null>(null);
  const [testing, setTesting] = React.useState(false);
  const [sending, setSending] = React.useState(false);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState("");
  const confirmInputRef = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    let alive = true;
    Promise.allSettled([adminEmailStatus(), adminEmailAudiences(), adminListBroadcasts()]).then(
      ([s, a, b]) => {
        if (!alive) return;
        if (s.status === "fulfilled") setStatus(s.value);
        if (a.status === "fulfilled") setAudiences(a.value.audiences || []);
        else toast.error(`Couldn't load audiences: ${String(a.reason)}`);
        if (b.status === "fulfilled") setBroadcasts(b.value.broadcasts || []);
        else toast.error(`Couldn't load broadcast history: ${String(b.reason)}`);
        setLoading(false);
      },
    );
    return () => { alive = false; };
  }, [toast]);

  // Poll the history only while something is still going out.
  const anySending = broadcasts.some((b) => b.status === "sending");
  React.useEffect(() => {
    if (!anySending) return;
    const id = window.setInterval(() => {
      adminListBroadcasts().then(
        (r) => setBroadcasts(r.broadcasts || []),
        () => { /* transient; the next tick retries */ },
      );
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [anySending]);

  const selectedAudience = audiences.find((a) => a.key === audience) ?? null;
  const n = selectedAudience?.count ?? 0;
  const hasDraft = subject.trim().length > 0 && body.trim().length > 0;
  const canSend = hasDraft && selectedAudience !== null && n > 0 && !sending;
  const notConfigured = status !== null && !status.configured;
  const confirmOk = confirmText.trim() === String(n) || confirmText.trim() === "SEND";

  const labelFor = (key: string) => audiences.find((a) => a.key === key)?.label ?? key;

  const sendTest = async () => {
    setTesting(true);
    try {
      const r = await adminSendTestBroadcast({ subject: subject.trim(), body: body.trim() });
      const msg = `Test email to ${r.to}: ${r.status}`;
      if (r.status === "sent" || r.status === "queued") toast.success(msg);
      else toast.warn(msg);
    } catch (err) {
      toast.error(`Test send failed: ${String(err)}`);
    } finally {
      setTesting(false);
    }
  };

  const openConfirm = () => {
    setConfirmText("");
    setConfirmOpen(true);
  };

  const send = async () => {
    if (!audience || !canSend || !confirmOk) return;
    setSending(true);
    try {
      const r = await adminSendBroadcast({ subject: subject.trim(), body: body.trim(), audience });
      setBroadcasts((prev) => [r.broadcast, ...prev.filter((b) => b.id !== r.broadcast.id)]);
      toast.success(`Sending to ${people(n)}. Progress shows in History below.`);
      setSubject("");
      setBody("");
      setConfirmOpen(false);
    } catch (err) {
      toast.error(`Send failed: ${String(err)}`);
    } finally {
      setSending(false);
    }
  };

  if (loading) return <AdminTableSkeleton />;

  return (
    <>
      {notConfigured && <EmailNotConfiguredBanner />}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: 16, marginBottom: 16 }}>
        <div className="card" style={{ padding: "var(--pad-lg)" }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Compose</div>

          <label style={{ display: "block", marginBottom: 12 }}>
            <span style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span className="label-micro">Subject</span>
              <span className="label-micro" data-testid="email-subject-count">{subject.length}/{SUBJECT_MAX}</span>
            </span>
            <input
              data-testid="email-subject"
              value={subject}
              maxLength={SUBJECT_MAX}
              onChange={(e) => setSubject(e.target.value)}
              style={fieldStyle}
            />
          </label>

          <label style={{ display: "block", marginBottom: 12 }}>
            <span style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span className="label-micro">Body</span>
              <span className="label-micro" data-testid="email-body-count">{body.length}/{BODY_MAX}</span>
            </span>
            <textarea
              data-testid="email-body"
              value={body}
              maxLength={BODY_MAX}
              rows={10}
              onChange={(e) => setBody(e.target.value)}
              style={{ ...fieldStyle, resize: "vertical", minHeight: 160 }}
            />
            <span style={{ display: "block", fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
              Plain text. Blank lines make paragraphs; links are clickable.
            </span>
          </label>

          <fieldset style={{ border: 0, padding: 0, margin: "0 0 16px" }}>
            <legend className="label-micro" style={{ marginBottom: 6 }}>Audience</legend>
            {audiences.length === 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No audiences available.</div>
            )}
            {audiences.map((a) => (
              <label
                key={a.key}
                style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "6px 0", fontSize: 13, cursor: "pointer",
                }}
              >
                <input
                  type="radio"
                  name="email-audience"
                  data-testid={`email-audience-${a.key}`}
                  value={a.key}
                  checked={audience === a.key}
                  onChange={() => setAudience(a.key)}
                />
                <span style={{ flex: 1 }}>{a.label}</span>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>{a.count}</span>
              </label>
            ))}
          </fieldset>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              data-testid="email-send-test"
              disabled={!hasDraft || testing}
              onClick={() => void sendTest()}
            >
              {testing ? "Sending test…" : "Send test to me"}
            </button>
            <button
              type="button"
              className="btn btn--primary btn--sm"
              data-testid="email-send"
              disabled={!canSend}
              onClick={openConfirm}
            >
              {sending ? "Sending…" : `Send to ${people(n)}`}
            </button>
          </div>
          {status?.from_address && (
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 10 }}>
              From {status.from_address}
            </div>
          )}
        </div>

        <div className="card" style={{ padding: "var(--pad-lg)" }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Preview</div>
          <div
            data-testid="email-preview"
            style={{
              border: "1px solid var(--border)", borderRadius: "var(--r-md)", padding: 16,
              background: "var(--bg-subtle)", fontSize: 14,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 12, overflowWrap: "anywhere" }} data-testid="email-preview-subject">
              {subject.trim() || <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(no subject)</span>}
            </div>
            <EmailBodyPreview body={body} />
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }} data-testid="email-history">
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
          <div className="label-micro">History · {broadcasts.length}</div>
        </div>
        {broadcasts.length === 0 ? (
          <div style={{ padding: 28, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            No broadcasts yet.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--bg-subtle)" }}>
                  {["Subject", "Audience", "Status", "Delivered", "Date"].map((h) => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {broadcasts.map((b) => (
                  <tr key={b.id} data-testid={`email-history-row-${b.id}`} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ ...tdStyle, fontWeight: 500, overflowWrap: "anywhere" }}>{b.subject}</td>
                    <td style={{ ...tdStyle, color: "var(--text-dim)" }}>{labelFor(b.audience)}</td>
                    <td style={tdStyle}>
                      <span className={BROADCAST_CHIP[b.status] ?? "chip"} data-testid={`email-history-status-${b.id}`}>
                        {b.status}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>
                      <span style={{ fontFamily: "var(--font-mono)" }}>{b.sent_count}/{b.recipient_count}</span>
                      {(b.failed_count > 0 || b.skipped_count > 0) && (
                        <span style={{ display: "block", fontSize: 11, color: "var(--text-muted)" }}>
                          {b.failed_count > 0 && <span style={{ color: "var(--warn)" }}>{b.failed_count} failed</span>}
                          {b.failed_count > 0 && b.skipped_count > 0 && " · "}
                          {b.skipped_count > 0 && <span>{b.skipped_count} skipped</span>}
                        </span>
                      )}
                    </td>
                    <td style={{ ...tdStyle, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                      {new Date(b.sent_at ?? b.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Dialog
        open={confirmOpen}
        onClose={() => { if (!sending) setConfirmOpen(false); }}
        size="sm"
        title={`Email ${people(n)}?`}
        initialFocusRef={confirmInputRef}
      >
        <p className="flags__confirm-text" style={{ marginBottom: 12 }}>
          This sends &ldquo;{subject.trim()}&rdquo; to {people(n)} in <strong>{selectedAudience?.label}</strong>.
          These are real inboxes and it can&apos;t be undone.
          {notConfigured && " Email isn't configured, so the broadcast will be recorded but nothing is delivered."}
        </p>
        <label style={{ display: "block", marginBottom: 20 }}>
          <span className="label-micro" style={{ display: "block", marginBottom: 4 }}>
            Type {n} or SEND to confirm
          </span>
          <input
            ref={confirmInputRef}
            data-testid="email-send-confirm-input"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && confirmOk) void send(); }}
            autoComplete="off"
            style={fieldStyle}
          />
        </label>
        <div className="flags__confirm-actions">
          <button
            type="button"
            className="btn"
            data-testid="email-send-cancel"
            disabled={sending}
            onClick={() => setConfirmOpen(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--primary"
            data-testid="email-send-confirm"
            disabled={!confirmOk || !canSend}
            onClick={() => void send()}
          >
            {sending ? "Sending…" : `Send to ${people(n)}`}
          </button>
        </div>
      </Dialog>
    </>
  );
}
