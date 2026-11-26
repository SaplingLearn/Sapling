"use client";
import React from "react";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Avatar } from "../Avatar";
import { RoleBadge } from "../RoleBadge";
import { CustomSelect } from "../CustomSelect";
import { AdminTableSkeleton } from "../Skeleton";
import Dialog from "../Dialog";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useUser } from "@/context/UserContext";
import { humanizeError } from "@/lib/errorMessage";
import {
  adminFetchUsers, adminRemoveUserAccess,
  adminListRoles, adminCreateRole, adminDeleteRole, adminAssignRole, adminRevokeRole,
  adminListCosmetics, adminCreateCosmetic, adminDeleteCosmetic,
  adminListRoleCosmetics, adminLinkRoleCosmetic, adminUnlinkRoleCosmetic,
  adminAuditLog, adminAnalyticsOverview,
  adminListFeedback, adminListIssueReports,
  adminUploadCosmeticAsset, COSMETIC_ASSET_TYPES,
  type AdminFeedbackEntry, type AdminIssueReport,
} from "@/lib/api";
import type { Role, Cosmetic, CosmeticType, RarityTier, AdminAuditEntry, AnalyticsOverview, AdminUserListItem as AdminUser } from "@/lib/types";
import { AchievementWiki } from "./admin/AchievementWiki";
import { FeatureFlagsTab } from "./admin/FeatureFlags";
import { AllowlistTab } from "./admin/AllowlistTab";
import { EmailBroadcastsTab } from "./admin/EmailBroadcasts";
import { AccountToolsDialog } from "./admin/AccountToolsDialog";
import { AdminReauthBanner } from "./admin/AdminReauthBanner";
import { sentenceCase } from "@/lib/sentenceCase";
import { cn } from "@/lib/cn";
import { fieldClass } from "@/components/ui/field";

type Tab = "users" | "allowlist" | "email" | "roles" | "flags" | "achievements" | "cosmetics" | "analytics" | "audit" | "feedback";

const RARITIES: RarityTier[] = ["common", "uncommon", "rare", "epic", "legendary"];
const COSMETIC_TYPES: CosmeticType[] = ["avatar_frame", "banner", "name_color", "title"];

export function Admin() {
  const { isAdmin } = useUser();
  const [tab, setTab] = React.useState<Tab>("users");

  if (!isAdmin) {
    return (
      <div>
        <TopBar breadcrumb="Admin" title="Admin Console" subtitle="Staff only" />
        <div className="p-15 text-center text-text-muted">
          You don&apos;t have admin access.
        </div>
      </div>
    );
  }

  const tabs: Tab[] = ["users", "allowlist", "email", "roles", "flags", "achievements", "cosmetics", "analytics", "audit", "feedback"];

  return (
    <div>
      <TopBar
        breadcrumb="Admin"
        title="Admin Console"
        subtitle="School-wide moderation and catalog management"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <AdminReauthBanner />
      <div className="py-3 px-8 border-b border-b-border flex gap-1 overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t}
            data-testid={`admin-tab-${t}`}
            onClick={() => setTab(t)}
            className={cn("py-2 px-4 text-md capitalize whitespace-nowrap", tab === t ? "font-semibold" : "font-normal", tab === t ? "text-text" : "text-text-dim", tab === t ? "border-b-2 border-b-accent" : "border-b-2 border-b-transparent")}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="py-6 px-8">
        {tab === "users" && <UsersTab />}
        {tab === "allowlist" && <AllowlistTab />}
        {tab === "email" && <EmailBroadcastsTab />}
        {tab === "roles" && <RolesTab />}
        {tab === "flags" && <FeatureFlagsTab />}
        {tab === "achievements" && <AchievementWiki />}
        {tab === "cosmetics" && <CosmeticsTab />}
        {tab === "analytics" && <AnalyticsTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "feedback" && <FeedbackTab />}
      </div>
    </div>
  );
}

// ── Users ────────────────────────────────────────────────────────────────────

function UsersTab() {
  const toast = useToast();
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  const [roles, setRoles] = React.useState<Role[]>([]);
  const [query, setQuery] = React.useState("");
  const [committedQuery, setCommittedQuery] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [pageSize] = React.useState(50);
  const [total, setTotal] = React.useState(0);
  const [assignFor, setAssignFor] = React.useState<string | null>(null);
  const [assignRoleId, setAssignRoleId] = React.useState<string>("");
  const [loading, setLoading] = React.useState(true);
  const [removeFor, setRemoveFor] = React.useState<AdminUser | null>(null);
  const [toolsFor, setToolsFor] = React.useState<AdminUser | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [u, r] = await Promise.all([
        adminFetchUsers({ q: committedQuery || undefined, page, page_size: pageSize }),
        adminListRoles(),
      ]);
      setUsers(u.users || []);
      setTotal(u.total || 0);
      setRoles(r.roles || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [committedQuery, page, pageSize, toast]);

  React.useEffect(() => { load(); }, [load]);

  React.useEffect(() => {
    const id = window.setTimeout(() => {
      setCommittedQuery(query);
      setPage(1);
    }, 350);
    return () => window.clearTimeout(id);
  }, [query]);

  const assign = async (uid: string) => {
    if (!assignRoleId) return;
    try {
      await adminAssignRole(uid, assignRoleId);
      toast.success("Role assigned");
      setAssignFor(null);
      setAssignRoleId("");
      await load();
    } catch (err) {
      toast.error(`Assign failed: ${String(err)}`);
    }
  };

  const revoke = async (uid: string, rid: string) => {
    try {
      await adminRevokeRole(uid, rid);
      toast.success("Role revoked");
      await load();
    } catch (err) {
      toast.error(`Revoke failed: ${String(err)}`);
    }
  };

  // Removing access sends the account back to the waitlist (backend: PATCH
  // /users/{id}/unapprove), so the row leaves this list and shows up under
  // Allowlist as a signup.
  const removeAccess = async (u: AdminUser) => {
    try {
      await adminRemoveUserAccess(u.id);
      setRemoveFor(null);
      toast.success(`Access removed. ${u.email || u.name} is back on the Allowlist.`);
      await load();
    } catch (err) {
      setRemoveFor(null);
      toast.error(humanizeError(err, "Couldn't remove access. Try again."));
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (loading && users.length === 0) {
    return <AdminTableSkeleton />;
  }

  return (
    <>
      <div className="body-serif text-[15px] mb-5.5 text-text-dim max-w-170" data-testid="admin-users-summary">
        <span className="text-text">{total}</span> user{total === 1 ? "" : "s"}
        {committedQuery && <> · <span className="text-text-muted">filter "{committedQuery}"</span></>}
      </div>
      <div className="card p-0">
        <div className="flex py-3 px-4 border-b border-b-border items-center gap-3">
          <div className="relative flex-1 max-w-75">
            <div className="absolute left-2.5 top-2 text-text-muted">
              <Icon name="search" size={14} />
            </div>
            <input
              placeholder="Search users…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-full pt-[7px] pr-3 pb-[7px] pl-8 border border-border rounded-sm text-md bg-bg-input"
            />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-md">
            <thead>
              <tr className="bg-bg-subtle">
                {["User", "Email", "Roles", "Last seen", "Joined", ""].map(h => (
                  <th key={h} className="text-left py-2.5 px-4 font-medium text-md text-text-muted">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-t border-t-border">
                  <td className="py-2.5 px-4">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={u.name || u.email || "?"} size={28} />
                      {u.undecryptable ? (
                        <span
                          data-testid="admin-user-undecryptable"
                          title={`Encrypted with a different key than this server's; can't be read. User id: ${u.id}`}
                          className="italic text-text-muted">
                          Unreadable record
                        </span>
                      ) : u.name ? (
                        <span title={u.name} className="block min-w-0 max-w-60 overflow-hidden text-ellipsis whitespace-nowrap font-medium">{u.name}</span>
                      ) : (
                        <span className="italic text-text-muted">No profile name</span>
                      )}
                      {!u.is_approved && u.open_access_at && (
                        <span
                          className="chip chip--info"
                          data-testid="admin-user-open-access"
                          title="In through open access, not approved: goes back to the waitlist when you require it again. Approve them under Allowlist to keep them in."
                        >
                          open access
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 px-4 text-text-dim">
                    <span title={u.email ?? undefined} className="block min-w-0 max-w-60 overflow-hidden text-ellipsis whitespace-nowrap">{u.email ?? "—"}</span>
                  </td>
                  <td className="py-2.5 px-4">
                    <div className="flex gap-1 flex-wrap items-center">
                      {(u.roles || []).map(r => (
                        <span key={r.id} className="inline-flex items-center gap-[3px]">
                          <RoleBadge role={r} />
                          <button
                            title="Revoke"
                            onClick={() => revoke(u.id, r.id)}
                            className="text-text-muted py-px px-1"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                      {assignFor === u.id ? (
                        <span className="inline-flex gap-1 items-center">
                          <CustomSelect
                            size="sm"
                            value={assignRoleId}
                            onChange={v => setAssignRoleId(v)}
                            options={roles.filter(r => !(u.roles || []).some(ur => ur.id === r.id)).map(r => ({ value: r.id, label: r.name }))}
                            placeholder="Role…"
                          />
                          <button className="btn btn--sm btn--primary" onClick={() => assign(u.id)} disabled={!assignRoleId}>
                            Add
                          </button>
                          <button className="btn btn--sm btn--ghost" onClick={() => { setAssignFor(null); setAssignRoleId(""); }}>×</button>
                        </span>
                      ) : (
                        <button
                          className="btn btn--sm btn--ghost text-xs"
                          onClick={() => { setAssignFor(u.id); setAssignRoleId(""); }}
                        >
                          + role
                        </button>
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 px-4 text-text-muted">
                    {u.last_sign_in_at ? new Date(u.last_sign_in_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="py-2.5 px-4 text-text-muted">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="py-2.5 px-4 text-right whitespace-nowrap">
                    <button
                      className="btn btn--sm btn--ghost"
                      data-testid={`admin-user-account-tools-${u.id}`}
                      onClick={() => setToolsFor(u)}
                    >
                      Account tools
                    </button>
                    <button
                      className="btn btn--sm btn--ghost"
                      data-testid={`admin-user-remove-access-${u.id}`}
                      onClick={() => setRemoveFor(u)}
                    >
                      Remove access
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex justify-between items-center py-2.5 px-4 border-t border-t-border text-sm text-text-muted">
          <div>Page {page} of {totalPages} · {total} total</div>
          <div className="flex gap-1.5">
            <button className="btn btn--sm btn--ghost" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>Prev</button>
            <button className="btn btn--sm btn--ghost" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>Next</button>
          </div>
        </div>
      </div>
      <RemoveAccessDialog
        user={removeFor}
        onCancel={() => setRemoveFor(null)}
        onConfirm={removeAccess}
      />
      <AccountToolsDialog user={toolsFor} onClose={() => setToolsFor(null)} />
    </>
  );
}

/** In-page confirm for "Remove access" (never window.confirm). The middleware
 *  re-checks approval via /api/auth/me on every app page request, so the copy
 *  says they lose access on their next page load: the session itself isn't
 *  revoked, so "signed out" would overstate it. */
function RemoveAccessDialog({ user, onCancel, onConfirm }: {
  user: AdminUser | null;
  onCancel: () => void;
  onConfirm: (u: AdminUser) => Promise<void>;
}) {
  const [saving, setSaving] = React.useState(false);
  if (!user) return null;
  const who = user.name || user.email;

  const confirm = async () => {
    setSaving(true);
    try { await onConfirm(user); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open onClose={onCancel} size="sm" title={`Remove ${who}'s access?`}>
      <p
        data-testid="admin-user-remove-body"
        className="mt-0 mx-0 mb-6 text-text-dim text-base leading-[1.55]"
      >
        They&apos;ll lose access to Sapling the next time they load a page, and move to the Allowlist as a
        signup. Their account and data are kept, and approving them on the Allowlist lets them back in when
        they next sign in.
      </p>
      <div className="flex justify-end gap-2.5">
        <button type="button" className="btn" data-testid="admin-user-remove-cancel" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn--primary"
          data-testid="admin-user-remove-confirm"
          disabled={saving}
          onClick={() => void confirm()}
        >
          {saving ? "Removing…" : "Remove access"}
        </button>
      </div>
    </Dialog>
  );
}

// ── Roles ────────────────────────────────────────────────────────────────────

function RolesTab() {
  const toast = useToast();
  const { userName, avatarUrl, username } = useUser();
  const [roles, setRoles] = React.useState<Role[]>([]);
  const [form, setForm] = React.useState({
    name: "", slug: "", color: "#8a7bc4", icon: "", description: "",
    is_staff_assigned: true, is_earnable: false, display_priority: 0,
  });
  const [slugEdited, setSlugEdited] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  const previewRole: Role = {
    id: "preview",
    name: form.name.trim() || "Role name",
    slug: form.slug || "role-slug",
    color: form.color,
    icon: form.icon.trim() || null,
    description: form.description.trim() || null,
    is_staff_assigned: form.is_staff_assigned,
    is_earnable: form.is_earnable,
    display_priority: form.display_priority,
  };

  const load = async () => {
    try {
      const r = await adminListRoles();
      setRoles(r.roles || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    }
  };
  React.useEffect(() => { load(); }, []);

  const create = async () => {
    if (!form.name.trim() || !form.slug.trim()) {
      toast.warn("Name and slug are required.");
      return;
    }
    setSaving(true);
    try {
      await adminCreateRole({
        name: form.name.trim(),
        slug: form.slug.trim(),
        color: form.color,
        icon: form.icon.trim() || null,
        description: form.description.trim() || null,
        is_staff_assigned: form.is_staff_assigned,
        is_earnable: form.is_earnable,
        display_priority: form.display_priority,
      });
      setForm({ name: "", slug: "", color: "#8a7bc4", icon: "", description: "", is_staff_assigned: true, is_earnable: false, display_priority: 0 });
      setSlugEdited(false);
      await load();
      toast.success("Role created");
    } catch (err) {
      toast.error(`Create failed: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const del = async (id: string) => {
    try {
      await adminDeleteRole(id);
      await load();
      toast.success("Role deleted");
    } catch (err) {
      toast.error(`Delete failed: ${String(err)}`);
    }
  };

  return (
    <div className="pane-split">
      <div className="card p-(--pad-lg)">
        <div className="label-micro mb-2.5">Preview</div>
        <RoleProfilePreview
          draftRole={previewRole}
          draftActive={Boolean(form.name.trim())}
          existingRoles={roles}
          userName={userName}
          username={username}
          avatarUrl={avatarUrl}
        />
        <div className="label-micro mt-4.5 mb-2.5">Create role</div>
        <LabeledField label="Name">
          <input
            value={form.name}
            onChange={e => {
              const name = e.target.value;
              setForm(f => ({
                ...f,
                name,
                slug: slugEdited ? f.slug : name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''),
              }));
            }}
            className={fieldClass}
          />
        </LabeledField>
        <LabeledField label="Slug">
          <input
            value={form.slug}
            onChange={e => {
              setSlugEdited(true);
              setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }));
            }}
            className={fieldClass}
          />
          <div className="text-xs text-text-muted mt-1">
            URL-friendly ID. Auto-filled from name; edit to override.
          </div>
        </LabeledField>
        <LabeledField label="Color">
          <input type="color" value={form.color} onChange={e => setForm(f => ({ ...f, color: e.target.value }))} className="w-full border border-border rounded-sm text-md bg-bg-input [font-family:inherit] h-9 p-0.5" />
        </LabeledField>
        <LabeledField label="Icon (emoji, optional)">
          <input value={form.icon} onChange={e => setForm(f => ({ ...f, icon: e.target.value }))} placeholder="🛡️ (leave blank to skip)" className={fieldClass} />
        </LabeledField>
        <LabeledField label="Description">
          <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} className={fieldClass} />
        </LabeledField>
        <div className="flex gap-3 mt-1.5">
          <label className="inline-flex items-center gap-1.5 text-sm text-text-dim">
            <input type="checkbox" checked={form.is_staff_assigned} onChange={e => setForm(f => ({ ...f, is_staff_assigned: e.target.checked }))} /> Staff-assigned
          </label>
          <label className="inline-flex items-center gap-1.5 text-sm text-text-dim">
            <input type="checkbox" checked={form.is_earnable} onChange={e => setForm(f => ({ ...f, is_earnable: e.target.checked }))} /> Earnable
          </label>
        </div>
        <button className="btn btn--primary mt-3.5 w-full" onClick={create} disabled={saving}>
          {saving ? "Creating…" : "Create role"}
        </button>
      </div>
      <div className="card p-0">
        <div className="py-3 px-4 border-b border-b-border">
          <div className="label-micro">Roles · {roles.length}</div>
        </div>
        {roles.length === 0 && (
          <div className="p-7 text-center text-text-muted text-md">No roles yet.</div>
        )}
        {roles.map(r => <CatalogRow key={r.id} left={<RoleBadge role={r} />} middle={r.description || r.slug} onDelete={() => del(r.id)} />)}
      </div>
    </div>
  );
}

// ── Cosmetics ────────────────────────────────────────────────────────────────

function CosmeticsTab() {
  const toast = useToast();
  const [items, setItems] = React.useState<Cosmetic[]>([]);
  const [form, setForm] = React.useState<{
    type: CosmeticType; name: string; slug: string;
    asset_url: string; css_value: string;
    rarity: RarityTier; unlock_source: string;
  }>({ type: "avatar_frame", name: "", slug: "", asset_url: "", css_value: "", rarity: "common", unlock_source: "" });
  const [saving, setSaving] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const [openId, setOpenId] = React.useState<string | null>(null);
  const [allRoles, setAllRoles] = React.useState<Role[]>([]);
  const [linkedRoleIdsByCosmetic, setLinkedRoleIdsByCosmetic] = React.useState<Record<string, string[]>>({});

  const ensureRoles = React.useCallback(async () => {
    if (allRoles.length) return;
    try { setAllRoles((await adminListRoles()).roles || []); }
    catch (err) { toast.error(`Roles load failed: ${String(err)}`); }
  }, [allRoles.length, toast]);

  const loadLinks = async (cosmeticId: string) => {
    await ensureRoles();
    try {
      // Build linked roles list by checking each role's cosmetic links.
      const roles = allRoles.length ? allRoles : (await adminListRoles()).roles || [];
      if (!allRoles.length) setAllRoles(roles);
      const all = await Promise.all(roles.map(r => adminListRoleCosmetics(r.id).then(x => ({ r, x }))));
      const linked = all
        .filter(({ x }) => x.links.some(l => l.cosmetic_id === cosmeticId))
        .map(({ r }) => r.id);
      setLinkedRoleIdsByCosmetic(prev => ({ ...prev, [cosmeticId]: linked }));
    } catch (err) {
      toast.error(`Link load failed: ${String(err)}`);
    }
  };

  const toggleRoleLink = async (roleId: string, cosmeticId: string) => {
    const linked = linkedRoleIdsByCosmetic[cosmeticId] || [];
    try {
      if (linked.includes(roleId)) await adminUnlinkRoleCosmetic(roleId, cosmeticId);
      else                          await adminLinkRoleCosmetic(roleId, cosmeticId);
      await loadLinks(cosmeticId);
    } catch (err) { toast.error(`Toggle failed: ${String(err)}`); }
  };

  const toggleOpen = async (id: string) => {
    if (openId === id) { setOpenId(null); return; }
    setOpenId(id);
    await loadLinks(id);
  };

  const load = async () => {
    try {
      const r = await adminListCosmetics();
      setItems(r.cosmetics || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    }
  };
  React.useEffect(() => { load(); }, []);

  const onFilePicked = async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    try {
      // Through the backend (admin-only, service-role storage): the browser
      // never writes to storage with the anon key.
      const { asset_url } = await adminUploadCosmeticAsset(file);
      setForm(f => ({ ...f, asset_url }));
      toast.success("Asset uploaded");
    } catch (err) {
      toast.error(`Upload failed: ${String(err)}`);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const needsAsset = form.type === "avatar_frame" || form.type === "banner";
  const needsCss = form.type === "name_color" || form.type === "title";

  const create = async () => {
    if (!form.name.trim() || !form.slug.trim()) {
      toast.warn("Name and slug are required.");
      return;
    }
    if (needsAsset && !form.asset_url.trim()) {
      toast.warn("Upload an asset for frames/banners.");
      return;
    }
    if (needsCss && !form.css_value.trim()) {
      toast.warn("CSS value is required for name colors and titles.");
      return;
    }
    setSaving(true);
    try {
      await adminCreateCosmetic({
        type: form.type,
        name: form.name.trim(),
        slug: form.slug.trim(),
        asset_url: needsAsset ? form.asset_url.trim() : null,
        css_value: needsCss ? form.css_value.trim() : null,
        rarity: form.rarity,
        unlock_source: form.unlock_source.trim() || null,
      });
      setForm({ type: form.type, name: "", slug: "", asset_url: "", css_value: "", rarity: "common", unlock_source: "" });
      await load();
      toast.success("Cosmetic created");
    } catch (err) {
      toast.error(`Create failed: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const del = async (id: string) => {
    try {
      await adminDeleteCosmetic(id);
      await load();
      toast.success("Cosmetic deleted");
    } catch (err) {
      toast.error(`Delete failed: ${String(err)}`);
    }
  };

  const grouped: Record<CosmeticType, Cosmetic[]> = { avatar_frame: [], banner: [], name_color: [], title: [] };
  for (const c of items) grouped[c.type]?.push(c);

  return (
    <div className="pane-split pane-split--wide">
      <div className="card p-(--pad-lg)">
        <div className="label-micro mb-2.5">Create cosmetic</div>
        <LabeledField label="Type">
          <CustomSelect<CosmeticType>
            value={form.type}
            onChange={v => setForm(f => ({ ...f, type: v, asset_url: "", css_value: "" }))}
            options={COSMETIC_TYPES.map(t => ({ value: t, label: t.replace("_", " ") }))}
          />
        </LabeledField>
        <LabeledField label="Name"><input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} className={fieldClass} /></LabeledField>
        <LabeledField label="Slug"><input value={form.slug} onChange={e => setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }))} className={fieldClass} /></LabeledField>
        {needsAsset && (
          <LabeledField label="Asset (PNG/SVG)">
            <div className="flex gap-1.5">
              <input
                value={form.asset_url}
                onChange={e => setForm(f => ({ ...f, asset_url: e.target.value }))}
                placeholder="Upload or paste URL"
                className="w-full py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] flex-1"
              />
              <button
                className="btn btn--sm"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
              >
                <Icon name="upload" size={12} /> {uploading ? "…" : "Upload"}
              </button>
              <input
                ref={fileRef}
                type="file"
                accept={COSMETIC_ASSET_TYPES.join(",")}
                className="hidden"
                onChange={e => onFilePicked(e.target.files?.[0] ?? null)}
              />
            </div>
            {form.asset_url && (
              <img src={form.asset_url} alt="" loading="lazy" decoding="async" className="max-h-14 mt-1.5 rounded-sm border border-border" />
            )}
          </LabeledField>
        )}
        {needsCss && (
          <LabeledField label={form.type === "name_color" ? "CSS (color or gradient)" : "CSS (label)"}>
            <input
              value={form.css_value}
              onChange={e => setForm(f => ({ ...f, css_value: e.target.value }))}
              placeholder={form.type === "name_color" ? "linear-gradient(90deg, #ff7e5f, #feb47b)" : "Grandmaster"}
              className={fieldClass}
            />
          </LabeledField>
        )}
        <LabeledField label="Rarity">
          <CustomSelect<RarityTier>
            value={form.rarity}
            onChange={v => setForm(f => ({ ...f, rarity: v }))}
            options={RARITIES.map(r => ({ value: r, label: r }))}
          />
        </LabeledField>
        <LabeledField label="Unlock source">
          <input
            value={form.unlock_source}
            onChange={e => setForm(f => ({ ...f, unlock_source: e.target.value }))}
            placeholder="achievement:slug or shop"
            className={fieldClass}
          />
        </LabeledField>
        <button className="btn btn--primary mt-3.5 w-full" onClick={create} disabled={saving || uploading}>
          {saving ? "Creating…" : "Create cosmetic"}
        </button>
      </div>
      <div className="flex flex-col gap-3.5">
        {COSMETIC_TYPES.map(t => (
          <div key={t} className="card p-0">
            <div className="py-2.5 px-4 border-b border-b-border flex justify-between">
              <div className="label-micro" style={{ }}>{sentenceCase(t.replace("_", " "))}</div>
              <span className="text-xs text-text-muted">{grouped[t].length}</span>
            </div>
            {grouped[t].length === 0 && (
              <div className="p-4 text-sm text-text-muted text-center">None.</div>
            )}
            {grouped[t].map(c => (
              <CatalogRow
                key={c.id}
                left={c.asset_url ? (
                  <img src={c.asset_url} alt="" width={28} height={28} loading="lazy" decoding="async" className="w-7 h-7 rounded-sm object-cover border border-border" />
                ) : c.css_value ? (
                  <span className="py-0.5 px-1.5 text-2xs rounded-sm text-accent-fg border border-border" style={{ background: c.css_value }}>
                    sample
                  </span>
                ) : (
                  <span className="text-lg">◇</span>
                )}
                middle={
                  <span className="flex gap-2 items-center">
                    <span className="font-semibold">{c.name}</span>
                    <span className="chip text-sm">{sentenceCase(c.rarity)}</span>
                  </span>
                }
                sub={c.slug}
                onDelete={() => del(c.id)}
                onExpand={() => toggleOpen(c.id)}
                expanded={openId === c.id}
                expandedContent={
                  <div>
                    <div className="label-micro mb-1.5">Roles that grant this</div>
                    <div className="flex gap-1.5 flex-wrap">
                      {allRoles.map(r => {
                        const on = (linkedRoleIdsByCosmetic[c.id] || []).includes(r.id);
                        return (
                          <button
                            key={r.id}
                            className={cn(`chip ${on ? "chip--accent" : ""}`, "cursor-pointer", on ? "" : "border border-dashed border-border")}
                            onClick={() => toggleRoleLink(r.id, c.id)}
                          >
                            {r.name}
                          </button>
                        );
                      })}
                      {allRoles.length === 0 && <span className="text-sm text-text-muted">No roles defined yet.</span>}
                    </div>
                  </div>
                }
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Analytics ────────────────────────────────────────────────────────────────

function AnalyticsTab() {
  const toast = useToast();
  const [data, setData] = React.useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let alive = true;
    adminAnalyticsOverview()
      .then(r => { if (alive) setData(r); })
      .catch(err => toast.error(`Analytics load failed: ${String(err)}`))
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [toast]);

  if (loading) return <AdminTableSkeleton />;
  if (!data) return null;

  const { totals, signups_by_day, approvals_by_day, role_counts } = data;

  return (
    <div className="grid gap-3.5">
      <div className="metric-grid">
        <MetricCard label="Users" value={totals.users} />
        <MetricCard label="Approved" value={totals.approved} accent />
        <MetricCard label="Awaiting approval" value={totals.pending} warn={totals.pending > 0} />
        <MetricCard label="Admins" value={totals.admins} />
      </div>
      <div className="card p-(--pad-lg)">
        <div className="label-micro mb-2.5">Signups · last 30 days</div>
        <Sparkline points={signups_by_day} accent />
      </div>
      <div className="card p-(--pad-lg)">
        <div className="label-micro mb-2.5">Approvals · last 30 days</div>
        <Sparkline points={approvals_by_day} />
      </div>
      <div className="card p-0">
        <div className="py-3 px-4 border-b border-b-border">
          <div className="label-micro">Role membership · {role_counts.length}</div>
        </div>
        {role_counts.length === 0 && (
          <div className="p-7 text-center text-text-muted text-md">
            Nobody has any roles yet.
          </div>
        )}
        {role_counts.map(rc => (
          <div key={rc.slug} className="flex items-center gap-3 py-2.5 px-4 border-t border-t-border text-md">
            <span className="inline-block w-2.5 h-2.5 rounded-[3px] border border-border" style={{ background: rc.color }} />
            <span className="flex-1 font-medium">{rc.name}</span>
            <span className="font-sans text-text-dim">{rc.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricCard({ label, value, accent, warn }: { label: string; value: number; accent?: boolean; warn?: boolean }) {
  const color = accent ? "var(--accent)" : warn ? "var(--warn)" : "var(--text)";
  return (
    <div className="card p-(--pad-lg)">
      <div className="label-micro">{label}</div>
      <div className="h-serif text-5xl mt-1" style={{ color }}>{value}</div>
    </div>
  );
}

function Sparkline({ points, accent }: { points: { date: string; count: number }[]; accent?: boolean }) {
  if (points.length === 0) return <div className="text-sm text-text-muted">No data.</div>;
  const w = 600, h = 80, pad = 4;
  const max = Math.max(1, ...points.map(p => p.count));
  const stepX = (w - pad * 2) / Math.max(1, points.length - 1);
  const path = points.map((p, i) => {
    const x = pad + i * stepX;
    const y = h - pad - (p.count / max) * (h - pad * 2);
    return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  const stroke = accent ? "var(--accent)" : "var(--text-dim)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full h-20">
      <path d={path} fill="none" stroke={stroke} strokeWidth={2} />
      {points.map((p, i) => (
        <circle key={p.date} cx={pad + i * stepX} cy={h - pad - (p.count / max) * (h - pad * 2)} r={2} fill={stroke}>
          <title>{`${p.date}: ${p.count}`}</title>
        </circle>
      ))}
    </svg>
  );
}

// ── Shared row + input helpers ───────────────────────────────────────────────

function CatalogRow({
  left, middle, sub, onDelete, onExpand, expanded, expandedContent,
}: {
  left: React.ReactNode;
  middle: React.ReactNode;
  sub?: string;
  onDelete: () => void;
  onExpand?: () => void;
  expanded?: boolean;
  expandedContent?: React.ReactNode;
}) {
  const del = useConfirm(onDelete);
  return (
    <div>
      <div className="flex items-center gap-3 py-2.5 px-4 border-t border-t-border">
        <div className="shrink-0">{left}</div>
        <div className="flex-1 min-w-0">
          <div className="text-md">{middle}</div>
          {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
        </div>
        {onExpand && (
          <button className="btn btn--sm btn--ghost" onClick={onExpand}>
            {expanded ? "Hide" : "Manage"}
          </button>
        )}
        <button
          className={`btn btn--sm ${del.armed ? "btn--danger" : "btn--ghost"}`}
          onClick={del.trigger}
          style={del.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
        >
          {del.armed ? "Click again" : <Icon name="x" size={12} />}
        </button>
      </div>
      {expanded && expandedContent && (
        <div className="pt-2.5 pr-4 pb-3.5 pl-14 [border-top:1px_dashed_var(--border)] bg-bg-subtle">
          {expandedContent}
        </div>
      )}
    </div>
  );
}

function RoleProfilePreview({
  draftRole, draftActive, existingRoles, userName, username, avatarUrl,
}: {
  draftRole: Role;
  draftActive: boolean;
  existingRoles: Role[];
  userName: string;
  username: string | null;
  avatarUrl: string;
}) {
  const displayName = userName || "Your Name";
  const handle = username ? `@${username}` : "@you";
  return (
    <div className="border border-border rounded-md p-3.5 bg-bg-subtle flex items-start gap-3">
      <Avatar name={displayName} img={avatarUrl || undefined} size={44} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap gap-y-1">
          <span className="font-semibold text-base">{displayName}</span>
          {draftActive && (
            <span className="relative inline-flex">
              <RoleBadge role={draftRole} />
              <span className="absolute -top-1.5 -right-1.5 text-[9.5px] font-semibold py-px px-1 rounded-xs bg-accent text-accent-fg">
                draft
              </span>
            </span>
          )}
          {existingRoles.map(r => <RoleBadge key={r.id} role={r} />)}
        </div>
        <div className="text-sm text-text-muted mt-0.5">{handle}</div>
      </div>
    </div>
  );
}

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2.5">
      <div className="label-micro mb-1">{label}</div>
      {children}
    </div>
  );
}

// ── Audit ─────────────────────────────────────────────────────────────────────
function AuditTab() {
  const toast = useToast();
  const [entries, setEntries] = React.useState<AdminAuditEntry[]>([]);
  const [page, setPage] = React.useState(1);
  const [pageSize] = React.useState(50);
  const [total, setTotal] = React.useState(0);
  const [actionFilter, setActionFilter] = React.useState<string>("");
  const [targetFilter, setTargetFilter] = React.useState<string>("");
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await adminAuditLog({
        page, page_size: pageSize,
        action: actionFilter || undefined,
        target_type: targetFilter || undefined,
      });
      setEntries(r.entries || []);
      setTotal(r.total || 0);
    } catch (err) {
      toast.error(`Audit load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, actionFilter, targetFilter, toast]);

  React.useEffect(() => { load(); }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (loading && entries.length === 0) return <AdminTableSkeleton />;

  return (
    <>
      <div className="body-serif text-[15px] mb-5.5 text-text-dim max-w-170">
        <span className="text-text">{total}</span> recorded action{total === 1 ? "" : "s"}
      </div>
      <div className="card p-0">
        <div className="flex py-3 px-4 border-b border-b-border items-center gap-3">
          <input
            placeholder="action (e.g. user.approve)"
            value={actionFilter}
            onChange={e => { setActionFilter(e.target.value); setPage(1); }}
            className="w-full py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] max-w-55"
          />
          <input
            placeholder="target_type (e.g. user)"
            value={targetFilter}
            onChange={e => { setTargetFilter(e.target.value); setPage(1); }}
            className="w-full py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] max-w-55"
          />
        </div>
        <table className="w-full border-collapse text-md">
          <thead>
            <tr className="bg-bg-subtle">
              {["When", "Actor", "Action", "Target", "Payload"].map(h => (
                <th key={h} className="text-left py-2.5 px-4 font-medium text-md text-text-muted">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(e => (
              <tr key={e.id} className="border-t border-t-border">
                <td className="py-2.5 px-4 text-text-muted whitespace-nowrap">
                  {new Date(e.created_at).toLocaleString()}
                </td>
                <td className="py-2.5 px-4 font-code text-sm">{e.actor_id}</td>
                <td className="py-2.5 px-4">
                  <span className="chip">{e.action}</span>
                </td>
                <td className="py-2.5 px-4 text-text-dim">
                  <span className="chip">{e.target_type}</span>
                  <span className="ml-1.5 font-code text-sm">{e.target_id || "—"}</span>
                </td>
                <td className="py-2.5 px-4 font-code text-xs text-text-muted max-w-90 overflow-hidden text-ellipsis whitespace-nowrap"
                    title={JSON.stringify(e.payload)}>
                  {Object.keys(e.payload || {}).length ? JSON.stringify(e.payload) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex justify-between items-center py-2.5 px-4 border-t border-t-border text-sm text-text-muted">
          <div>Page {page} of {totalPages}</div>
          <div className="flex gap-1.5">
            <button className="btn btn--sm btn--ghost" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>Prev</button>
            <button className="btn btn--sm btn--ghost" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>Next</button>
          </div>
        </div>
      </div>
    </>
  );
}

// ── Feedback ─────────────────────────────────────────────────────────────────
function FeedbackTab() {
  const toast = useToast();
  const [feedback, setFeedback] = React.useState<AdminFeedbackEntry[]>([]);
  const [reports, setReports] = React.useState<AdminIssueReport[]>([]);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    try {
      const [f, r] = await Promise.all([adminListFeedback(), adminListIssueReports()]);
      setFeedback(f.feedback || []);
      setReports(r.reports || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  if (loading) return <AdminTableSkeleton />;

  const when = (iso: string) => new Date(iso).toLocaleDateString();

  return (
    <>
      <div className="card p-0 mb-5.5" data-testid="adminfb-feedback-card">
        <div className="py-3 px-4 border-b border-b-border font-semibold">
          Feedback ({feedback.length})
        </div>
        {feedback.length === 0 && (
          <div className="p-4 text-text-dim">No feedback yet.</div>
        )}
        {feedback.map((f) => {
          const stars = Math.max(0, Math.min(5, f.rating));
          return (
          <div key={f.id} className="py-3 px-4 border-b border-b-border" data-testid="adminfb-feedback-row">
            <div className="flex gap-3 text-text-dim text-md">
              <span>{when(f.created_at)}</span>
              <span className="text-text">{f.user_name || f.user_id}</span>
              <span>{f.type}</span>
              <span>{"★".repeat(stars)}{"☆".repeat(5 - stars)}</span>
              {f.topic && <span>{f.topic}</span>}
            </div>
            {f.comment && <div className="mt-1.5">{f.comment}</div>}
            {f.selected_options.length > 0 && (
              <div className="mt-1 text-md text-text-dim">
                {f.selected_options.join(" · ")}
              </div>
            )}
          </div>
          );
        })}
      </div>
      <div className="card p-0" data-testid="adminfb-issues-card">
        <div className="py-3 px-4 border-b border-b-border font-semibold">
          Issue reports ({reports.length})
        </div>
        {reports.length === 0 && (
          <div className="p-4 text-text-dim">No issue reports yet.</div>
        )}
        {reports.map((r) => (
          <div key={r.id} className="py-3 px-4 border-b border-b-border" data-testid="adminfb-issue-row">
            <div className="flex gap-3 text-text-dim text-md">
              <span>{when(r.created_at)}</span>
              <span className="text-text">{r.user_name || r.user_id}</span>
              <span>{r.topic}</span>
              {r.screenshot_urls.length > 0 && <span>{r.screenshot_urls.length} screenshot(s)</span>}
            </div>
            <div className="mt-1.5">{r.description}</div>
          </div>
        ))}
      </div>
    </>
  );
}
