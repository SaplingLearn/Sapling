"use client";
import React from "react";

import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import {
  adminListFlags, adminUpdateFlag, adminUpsertFlagTarget, adminDeleteFlagTarget,
  adminExplainFlag, adminListRoles, adminFetchUsers, type AdminFlag,
} from "@/lib/api";
import type { AdminUserListItem } from "@/lib/types";

/**
 * Admin "Feature flags" tab (#620, ADR 0029). Lists every flag from the
 * static registry (`GET /api/admin/flags`), and expands a row into an
 * editor for the default variant, a percent rollout, and per-user/per-role
 * override rules, plus a one-off "what would student X see" lookup.
 */
export function FeatureFlagsTab() {
  const toast = useToast();
  const [flags, setFlags] = React.useState<AdminFlag[] | null>(null);
  const [open, setOpen] = React.useState<string | null>(null);
  const [roles, setRoles] = React.useState<{ id: string; name: string }[]>([]);

  React.useEffect(() => {
    adminListFlags().then(
      (r) => setFlags(r.flags),
      (err) => { setFlags([]); toast.error(`Couldn't load flags: ${String(err)}`); },
    );
    adminListRoles().then((r) => setRoles(r.roles), () => setRoles([]));
  }, [toast]);

  if (!flags) return <AdminTableSkeleton />;

  const replace = (f: AdminFlag) => setFlags((all) => (all ?? []).map((x) => (x.key === f.key ? f : x)));

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr style={{ background: "var(--bg-subtle)" }}>
          {["Flag", "Default", "Rollout", "Rules", "Last change"].map((h) => (
            <th key={h} style={{ textAlign: "left", padding: "10px 16px", fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-muted)" }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {flags.map((f) => (
          <React.Fragment key={f.key}>
            <tr
              data-testid={`flag-row-${f.key}`}
              onClick={() => setOpen(open === f.key ? null : f.key)}
              style={{ cursor: "pointer", borderTop: "1px solid var(--border)" }}
            >
              <td style={{ padding: "10px 16px" }}>
                <strong>{f.key}</strong>
                <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 2 }}>{f.description}</div>
              </td>
              <td style={{ padding: "10px 16px" }}>{f.default_variant}</td>
              <td style={{ padding: "10px 16px" }}>
                {f.rollout_percent > 0 ? `${f.rollout_percent}% → ${f.rollout_variant}` : "—"}
              </td>
              <td style={{ padding: "10px 16px" }}>{f.targets.length}</td>
              <td style={{ padding: "10px 16px", color: "var(--text-muted)" }}>
                {f.updated_at ? `${f.updated_by_name ?? f.updated_by ?? ""} · ${new Date(f.updated_at).toLocaleString()}` : "—"}
              </td>
            </tr>
            {open === f.key && (
              <tr>
                <td colSpan={5} style={{ padding: 0, borderTop: "1px dashed var(--border)", background: "var(--bg-subtle)" }}>
                  <FlagEditor flag={f} roles={roles} onSaved={replace} />
                </td>
              </tr>
            )}
          </React.Fragment>
        ))}
        {flags.length === 0 && (
          <tr><td colSpan={5} style={{ padding: 28, textAlign: "center", color: "var(--text-muted)" }}>No flags defined.</td></tr>
        )}
      </tbody>
    </table>
  );
}

function FlagEditor({ flag, roles, onSaved }: {
  flag: AdminFlag; roles: { id: string; name: string }[]; onSaved: (f: AdminFlag) => void;
}) {
  const toast = useToast();
  const [def, setDef] = React.useState(flag.default_variant);
  const [pct, setPct] = React.useState(flag.rollout_percent);
  const [rv, setRv] = React.useState<string | null>(flag.rollout_variant);
  const [ruleType, setRuleType] = React.useState<"user" | "role">("role");
  const [ruleId, setRuleId] = React.useState("");
  const [ruleVariant, setRuleVariant] = React.useState(flag.variants[flag.variants.length - 1] ?? flag.variants[0]);
  const [userQuery, setUserQuery] = React.useState("");
  const [userHits, setUserHits] = React.useState<AdminUserListItem[]>([]);
  const [explainId, setExplainId] = React.useState("");
  const [explained, setExplained] = React.useState<string | null>(null);

  // A chosen rollout variant that stops being valid (e.g. the default just
  // changed to match it) is cleared rather than silently saved anyway.
  React.useEffect(() => {
    if (rv !== null && rv === def) setRv(null);
  }, [def, rv]);

  const actuallySave = React.useCallback(() => {
    void (async () => {
      try {
        const r = await adminUpdateFlag(flag.key, {
          default_variant: def,
          rollout_percent: pct,
          rollout_variant: pct > 0 ? rv : null,
        });
        onSaved(r.flag);
        toast.success("Flag saved");
      } catch (err) {
        toast.error(`Couldn't save: ${String(err)}`);
      }
    })();
  }, [flag.key, def, pct, rv, onSaved, toast]);
  const saveConfirm = useConfirm(actuallySave);

  const addRule = async () => {
    if (!ruleId) return;
    try {
      const r = await adminUpsertFlagTarget(flag.key, { target_type: ruleType, target_id: ruleId, variant: ruleVariant });
      onSaved(r.flag);
      setRuleId("");
      setUserQuery("");
      setUserHits([]);
      toast.success("Rule added");
    } catch (err) {
      toast.error(`Couldn't add rule: ${String(err)}`);
    }
  };

  const removeRule = async (type: "user" | "role", id: string) => {
    try {
      const r = await adminDeleteFlagTarget(flag.key, type, id);
      onSaved(r.flag);
    } catch (err) {
      toast.error(`Couldn't remove rule: ${String(err)}`);
    }
  };

  const searchUsers = async (q: string) => {
    setUserQuery(q);
    setRuleId("");
    if (q.trim().length < 2) {
      setUserHits([]);
      return;
    }
    try {
      const r = await adminFetchUsers({ q, page_size: 8 });
      setUserHits(r.users);
    } catch {
      setUserHits([]);
    }
  };

  const explain = async () => {
    if (!explainId.trim()) return;
    try {
      const r = await adminExplainFlag(flag.key, explainId.trim());
      setExplained(`${r.variant} (${r.step}${r.detail ? `: ${r.detail}` : ""})`);
    } catch (err) {
      toast.error(`Couldn't check that student: ${String(err)}`);
    }
  };

  return (
    <div style={{ display: "grid", gap: 14, padding: "14px 16px" }}>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 12, color: "var(--text-dim)", display: "flex", alignItems: "center", gap: 6 }}>
          Default
          <select data-testid={`flag-default-${flag.key}`} value={def} onChange={(e) => setDef(e.target.value)}>
            {flag.variants.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 12, color: "var(--text-dim)", display: "flex", alignItems: "center", gap: 6 }}>
          Rollout
          <input
            data-testid={`flag-rollout-${flag.key}`}
            type="range" min={0} max={100} value={pct}
            onChange={(e) => setPct(Number(e.target.value))}
          />
          <span style={{ minWidth: 32 }}>{pct}%</span>
        </label>
        <select
          data-testid={`flag-rollout-variant-${flag.key}`}
          value={rv ?? ""}
          disabled={pct === 0}
          onChange={(e) => setRv(e.target.value || null)}
        >
          <option value="">variant…</option>
          {flag.variants.filter((v) => v !== def).map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <button data-testid={`flag-save-${flag.key}`} onClick={saveConfirm.trigger}>
          {saveConfirm.armed ? "Click again to save" : "Save"}
        </button>
      </div>

      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-dim)", marginBottom: 6 }}>Rules</div>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <tbody>
            {flag.targets.map((t) => (
              <tr key={`${t.target_type}-${t.target_id}`} data-testid={`flag-target-row-${flag.key}-${t.target_type}-${t.target_id}`}>
                <td style={{ padding: "4px 8px 4px 0" }}>{t.target_type}</td>
                <td style={{ padding: "4px 8px" }}>{t.label}</td>
                <td style={{ padding: "4px 8px" }}>{t.variant}</td>
                <td style={{ padding: "4px 0" }}>
                  <button
                    data-testid={`flag-target-remove-${flag.key}-${t.target_type}-${t.target_id}`}
                    onClick={() => removeRule(t.target_type, t.target_id)}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {flag.targets.length === 0 && (
              <tr><td colSpan={4} style={{ color: "var(--text-muted)", padding: "4px 0" }}>No rules yet.</td></tr>
            )}
          </tbody>
        </table>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
          <select
            data-testid={`flag-target-type-${flag.key}`}
            value={ruleType}
            onChange={(e) => {
              setRuleType(e.target.value as "user" | "role");
              setRuleId("");
              setUserQuery("");
              setUserHits([]);
            }}
          >
            <option value="role">role</option>
            <option value="user">user</option>
          </select>
          {ruleType === "role" ? (
            <select data-testid={`flag-target-role-${flag.key}`} value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
              <option value="">pick a role…</option>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          ) : (
            <span style={{ position: "relative" }}>
              <input
                data-testid={`flag-target-user-search-${flag.key}`}
                placeholder="search students…"
                value={userQuery}
                onChange={(e) => searchUsers(e.target.value)}
              />
              {userHits.length > 0 && (
                <ul style={{ position: "absolute", background: "var(--bg)", zIndex: 10, listStyle: "none", padding: 4, margin: 0, border: "1px solid var(--border)" }}>
                  {userHits.map((u) => (
                    <li key={u.id}>
                      <button
                        data-testid={`flag-target-user-result-${flag.key}-${u.id}`}
                        onClick={() => { setRuleId(u.id); setUserQuery(u.name || u.email || u.id); setUserHits([]); }}
                      >
                        {u.name || u.email || u.id}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </span>
          )}
          <select data-testid={`flag-target-variant-${flag.key}`} value={ruleVariant} onChange={(e) => setRuleVariant(e.target.value)}>
            {flag.variants.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
          <button data-testid={`flag-target-add-${flag.key}`} onClick={addRule} disabled={!ruleId}>Add rule</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          data-testid={`flag-explain-input-${flag.key}`}
          placeholder="check a student (user id)…"
          value={explainId}
          onChange={(e) => setExplainId(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void explain(); }}
        />
        <button data-testid={`flag-explain-check-${flag.key}`} onClick={() => void explain()}>Check</button>
        {explained && <span data-testid={`flag-explain-result-${flag.key}`}>{explained}</span>}
      </div>
    </div>
  );
}
