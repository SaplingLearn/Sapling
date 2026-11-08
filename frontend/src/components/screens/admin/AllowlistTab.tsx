"use client";
import React from "react";

import Dialog from "@/components/Dialog";
import { Icon } from "@/components/Icon";
import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import {
  adminApproveAllowlist,
  adminApproveAllowlistBulk,
  adminEmailStatus,
  adminListAllowlist,
  adminRevokeAllowlist,
} from "@/lib/api";
import type { AllowlistEmail, EmailStatus, InviteStatus } from "@/lib/types";

import { fieldStyle, tdStyle, thStyle } from "./adminStyles";
import { EmailNotConfiguredBanner } from "./EmailNotConfiguredBanner";

/**
 * Admin "Allowlist" tab: the waitlist, filterable by status, with per-row and
 * bulk approval. Approving sends the "you're in" email server-side; the
 * Invite column shows that email's delivery state.
 */

type RowStatus = "signup" | "approved" | "joined";
type Filter = "all" | RowStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "signup", label: "Signups" },
  { key: "approved", label: "Approved" },
  { key: "joined", label: "Joined" },
];

/** The backend's bulk endpoint takes 1..500 addresses per call. */
const BULK_LIMIT = 500;

export function rowStatus(row: AllowlistEmail): RowStatus {
  if (row.joined_at) return "joined";
  if (row.approved_at) return "approved";
  return "signup";
}

const INVITE_CHIP: Record<InviteStatus, { cls: string; title: string }> = {
  sent: { cls: "chip chip--accent", title: "The “you’re in” email was sent." },
  failed: { cls: "chip chip--warn", title: "Sending the “you’re in” email failed." },
  queued: { cls: "chip", title: "Queued to send." },
  skipped: { cls: "chip", title: "Not sent: Resend not configured." },
  suppressed: { cls: "chip", title: "Not sent: this address unsubscribed." },
};

function InviteChip({ status, email }: { status: InviteStatus | null | undefined; email: string }) {
  if (!status) return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const meta = INVITE_CHIP[status] ?? { cls: "chip", title: status };
  return (
    <span className={meta.cls} title={meta.title} data-testid={`allowlist-invite-${email}`}>
      {status}
    </span>
  );
}

/** Toast for a single approval, driven by the invite status the server returned. */
function approvalToast(
  toast: ReturnType<typeof useToast>,
  row: AllowlistEmail | undefined,
  email: string,
  status: EmailStatus | null,
) {
  const s = row?.invite_status ?? (status && !status.configured ? "skipped" : null);
  switch (s) {
    case "sent":
      toast.success(`Approved ${email}. "You're in" email sent.`);
      return;
    case "queued":
      toast.success(`Approved ${email}. "You're in" email queued.`);
      return;
    case "skipped":
      toast.success(`Approved ${email}. No email sent: Resend isn't configured.`);
      return;
    case "suppressed":
      toast.success(`Approved ${email}. No email sent: they unsubscribed.`);
      return;
    case "failed":
      toast.warn(`Approved ${email}, but the "you're in" email failed to send.`);
      return;
    default:
      toast.success(`Approved ${email}.`);
  }
}

function fmtDate(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleDateString() : "—";
}

export function AllowlistTab() {
  const toast = useToast();
  const [emails, setEmails] = React.useState<AllowlistEmail[]>([]);
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<Filter>("all");
  const [selected, setSelected] = React.useState<Set<string>>(() => new Set());
  const [newEmail, setNewEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [emailStatus, setEmailStatus] = React.useState<EmailStatus | null>(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [bulkBusy, setBulkBusy] = React.useState(false);
  const headerBoxRef = React.useRef<HTMLInputElement | null>(null);

  const load = React.useCallback(async () => {
    try {
      const r = await adminListAllowlist();
      setEmails(r.emails || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { void load(); }, [load]);

  React.useEffect(() => {
    // A failed status read leaves the banner hidden rather than crying wolf.
    adminEmailStatus().then(setEmailStatus, () => setEmailStatus(null));
  }, []);

  const counts = React.useMemo(() => {
    const c: Record<Filter, number> = { all: emails.length, signup: 0, approved: 0, joined: 0 };
    for (const e of emails) c[rowStatus(e)] += 1;
    return c;
  }, [emails]);

  const q = query.trim().toLowerCase();
  const filtered = emails.filter(
    (e) => (filter === "all" || rowStatus(e) === filter) && (!q || e.email.toLowerCase().includes(q)),
  );

  // Selection only ever holds unapproved rows; derive it from the live list so
  // a row approved elsewhere (or by a reload) silently drops out.
  const selectedRows = emails.filter((e) => rowStatus(e) === "signup" && selected.has(e.email));
  const selectableVisible = filtered.filter((e) => rowStatus(e) === "signup");
  const visibleSelectedCount = selectableVisible.filter((e) => selected.has(e.email)).length;
  const allVisibleSelected = selectableVisible.length > 0 && visibleSelectedCount === selectableVisible.length;
  const someVisibleSelected = visibleSelectedCount > 0 && !allVisibleSelected;

  React.useEffect(() => {
    if (headerBoxRef.current) headerBoxRef.current.indeterminate = someVisibleSelected;
  }, [someVisibleSelected]);

  const toggleRow = (email: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  const toggleAllVisible = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) selectableVisible.forEach((e) => next.delete(e.email));
      else selectableVisible.forEach((e) => next.add(e.email));
      return next;
    });
  };

  const add = async () => {
    const e = newEmail.trim().toLowerCase();
    if (!e) return;
    setBusy(true);
    try {
      const r = await adminApproveAllowlist(e);
      setNewEmail("");
      approvalToast(toast, r?.email, e, emailStatus);
      await load();
    } catch (err) {
      toast.error(`Add failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (row: AllowlistEmail) => {
    try {
      if (row.approved_at) {
        await adminRevokeAllowlist(row.email);
        toast.success("Allowlist revoked");
      } else {
        const r = await adminApproveAllowlist(row.email);
        approvalToast(toast, r?.email, row.email, emailStatus);
      }
      await load();
    } catch (err) {
      toast.error(`Update failed: ${String(err)}`);
    }
  };

  const approveSelected = async () => {
    const targets = selectedRows.map((e) => e.email);
    if (targets.length === 0) return;
    setBulkBusy(true);
    let approved = 0;
    let done = 0;
    try {
      for (let i = 0; i < targets.length; i += BULK_LIMIT) {
        const batch = targets.slice(i, i + BULK_LIMIT);
        const r = await adminApproveAllowlistBulk(batch);
        approved += r?.approved ?? 0;
        done += batch.length;
      }
      const tail = emailStatus && !emailStatus.configured
        ? " No emails sent: Resend isn't configured."
        : ` "You're in" email${approved === 1 ? "" : "s"} on the way.`;
      toast.success(`Approved ${approved} of ${targets.length}.${tail}`);
      setSelected(new Set());
      setConfirmOpen(false);
    } catch (err) {
      const partial = done > 0 ? ` (${approved} approved before the failure)` : "";
      toast.error(`Bulk approve failed${partial}: ${String(err)}`);
    } finally {
      setBulkBusy(false);
      await load();
    }
  };

  if (loading) return <AdminTableSkeleton />;

  const notConfigured = emailStatus !== null && !emailStatus.configured;
  const n = selectedRows.length;

  return (
    <>
      {notConfigured && <EmailNotConfiguredBanner />}
      <div className="body-serif" style={{ fontSize: 15, marginBottom: 22, color: "var(--text-dim)", maxWidth: 680 }}>
        <span style={{ color: "var(--text)" }}>{emails.length}</span> address{emails.length === 1 ? "" : "es"} · {" "}
        <span style={{ color: "var(--accent)" }}>{emails.filter((e) => e.approved_at).length} approved</span> · {counts.joined} joined
        {counts.signup > 0 && <> · <span style={{ color: "var(--warn)" }}>{counts.signup} unapproved signups</span></>}
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ display: "flex", flexWrap: "wrap", padding: "12px 16px", borderBottom: "1px solid var(--border)", alignItems: "center", gap: 12 }}>
          <div style={{ position: "relative", flex: 1, minWidth: 180, maxWidth: 300 }}>
            <div style={{ position: "absolute", left: 10, top: 8, color: "var(--text-muted)" }}>
              <Icon name="search" size={14} />
            </div>
            <input
              data-testid="allowlist-search"
              placeholder="Search emails…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{
                width: "100%", padding: "7px 12px 7px 32px",
                border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
                fontSize: 13, background: "var(--bg-input)",
              }}
            />
          </div>
          <input
            data-testid="allowlist-add-input"
            placeholder="someone@bu.edu"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void add(); }}
            style={{ ...fieldStyle, maxWidth: 240 }}
          />
          <button
            type="button"
            data-testid="allowlist-add"
            className="btn btn--primary btn--sm"
            onClick={() => void add()}
            disabled={busy || !newEmail.trim()}
          >
            {busy ? "Adding…" : "Allowlist"}
          </button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", padding: "10px 16px", borderBottom: "1px solid var(--border)", alignItems: "center", gap: 6 }}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              data-testid={`allowlist-filter-${f.key}`}
              aria-pressed={filter === f.key}
              className={`chip ${filter === f.key ? "chip--accent" : ""}`}
              onClick={() => setFilter(f.key)}
              style={{ cursor: "pointer", border: filter === f.key ? undefined : "1px dashed var(--border)" }}
            >
              {f.label} ({counts[f.key]})
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <button
            type="button"
            data-testid="allowlist-bulk-approve"
            className="btn btn--primary btn--sm"
            disabled={n === 0 || bulkBusy}
            onClick={() => setConfirmOpen(true)}
          >
            Approve selected ({n})
          </button>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)" }}>
              <th style={{ ...thStyle, width: 36, paddingRight: 0 }}>
                <input
                  ref={headerBoxRef}
                  type="checkbox"
                  data-testid="allowlist-select-all"
                  aria-label="Select all unapproved signups shown"
                  checked={allVisibleSelected}
                  disabled={selectableVisible.length === 0}
                  onChange={toggleAllVisible}
                />
              </th>
              {["Email", "Status", "Invite", "Submitted", "Approved", "Joined", ""].map((h) => (
                <th key={h} style={thStyle}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={8} style={{ padding: 28, textAlign: "center", color: "var(--text-muted)" }}>
                  No addresses match.
                </td>
              </tr>
            )}
            {filtered.map((row) => {
              const st = rowStatus(row);
              return (
                <tr key={row.id} data-testid={`allowlist-row-${row.email}`} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ ...tdStyle, paddingRight: 0 }}>
                    {st === "signup" && (
                      <input
                        type="checkbox"
                        data-testid={`allowlist-select-${row.email}`}
                        aria-label={`Select ${row.email}`}
                        checked={selected.has(row.email)}
                        onChange={() => toggleRow(row.email)}
                      />
                    )}
                  </td>
                  <td style={{ ...tdStyle, fontWeight: 500 }}>{row.email}</td>
                  <td style={tdStyle}>
                    <span className={`chip ${st === "signup" ? "chip--warn" : "chip--accent"}`}>{st}</span>
                  </td>
                  <td style={tdStyle}>
                    <InviteChip status={row.invite_status} email={row.email} />
                  </td>
                  <td style={{ ...tdStyle, color: "var(--text-muted)" }}>{fmtDate(row.created_at)}</td>
                  <td style={{ ...tdStyle, color: "var(--text-muted)" }}>{fmtDate(row.approved_at)}</td>
                  <td style={{ ...tdStyle, color: "var(--text-muted)" }}>{fmtDate(row.joined_at)}</td>
                  <td style={{ ...tdStyle, textAlign: "right" }}>
                    <button
                      type="button"
                      data-testid={`allowlist-toggle-${row.email}`}
                      className={`btn btn--sm ${row.approved_at ? "btn--ghost" : "btn--primary"}`}
                      onClick={() => void toggle(row)}
                    >
                      {row.approved_at ? "Revoke" : "Approve"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog
        open={confirmOpen}
        onClose={() => { if (!bulkBusy) setConfirmOpen(false); }}
        size="sm"
        title={`Approve ${n} ${n === 1 ? "person" : "people"}?`}
      >
        <p className="flags__confirm-text" style={{ marginBottom: 12 }} data-testid="allowlist-bulk-confirm-text">
          {notConfigured
            ? "The approvals will be saved, but no emails go out until Resend is configured."
            : `Each gets a “you’re in” email.`}
        </p>
        <ul
          style={{
            margin: "0 0 20px", padding: "8px 12px", listStyle: "none", maxHeight: 160, overflowY: "auto",
            border: "1px solid var(--border)", borderRadius: "var(--r-sm)", fontSize: 12, color: "var(--text-dim)",
          }}
        >
          {selectedRows.map((e) => <li key={e.id}>{e.email}</li>)}
        </ul>
        <div className="flags__confirm-actions">
          <button
            type="button"
            className="btn"
            data-testid="allowlist-bulk-cancel"
            disabled={bulkBusy}
            onClick={() => setConfirmOpen(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--primary"
            data-testid="allowlist-bulk-confirm"
            disabled={bulkBusy || n === 0}
            onClick={() => void approveSelected()}
          >
            {bulkBusy ? "Approving…" : `Approve ${n}`}
          </button>
        </div>
      </Dialog>
    </>
  );
}
