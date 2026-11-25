"use client";
import React from "react";
import { AnimatePresence, motion, type MotionProps } from "framer-motion";
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
import { useMotionPresets } from "@/lib/motion";
import { AnimatedNumber } from "./AnimatedNumber";
import s from "./Admin.module.css";

type Tab = "users" | "allowlist" | "email" | "roles" | "flags" | "achievements" | "cosmetics" | "analytics" | "audit" | "feedback";

const RARITIES: RarityTier[] = ["common", "uncommon", "rare", "epic", "legendary"];
const COSMETIC_TYPES: CosmeticType[] = ["avatar_frame", "banner", "name_color", "title"];

/** A new role's starting colour. Data, not a design value: it is stored on the
 *  role and fed to a native colour input, which only takes a hex. */
const DEFAULT_ROLE_COLOR = "#8a7bc4";
/** An example name-colour value for the CSS field's placeholder (data the admin types). */
const NAME_COLOR_PLACEHOLDER = "linear-gradient(90deg, #ff7e5f, #feb47b)";
/** A feedback rating's scale. */
const MAX_STARS = 5;
/** How long the user search waits after the last keystroke. */
const SEARCH_DEBOUNCE_MS = 350;

/** Plain integer, no grouping: the summaries read "1234 users", as before. */
const plainCount = (v: number) => String(Math.round(v));

/** The admin's table head cells. */
function HeadRow({ cols }: { cols: string[] }) {
  return (
    <thead>
      <tr className={s.theadRow}>
        {cols.map(h => <th key={h} className={s.th}>{h}</th>)}
      </tr>
    </thead>
  );
}

/** Prev/Next under a paged table. */
function Pager({ page, totalPages, onPage, children }: {
  page: number; totalPages: number; onPage: (p: number) => void; children: React.ReactNode;
}) {
  return (
    <div className={s.pager}>
      <div>{children}</div>
      <div className={s.pagerButtons}>
        <button className="btn btn--sm btn--ghost" disabled={page <= 1} onClick={() => onPage(Math.max(1, page - 1))}>Prev</button>
        <button className="btn btn--sm btn--ghost" disabled={page >= totalPages} onClick={() => onPage(Math.min(totalPages, page + 1))}>Next</button>
      </div>
    </div>
  );
}

export function Admin() {
  const { isAdmin } = useUser();
  const [tab, setTab] = React.useState<Tab>("users");
  // The first tab paints still; only a switch fades the new one in.
  const [switched, setSwitched] = React.useState(false);
  const m = useMotionPresets();

  if (!isAdmin) {
    return (
      <div className={s.root}>
        <TopBar breadcrumb="Admin" title="Admin Console" subtitle="Staff only" />
        <div className={s.denied}>
          You don&apos;t have admin access.
        </div>
      </div>
    );
  }

  const tabs: Tab[] = ["users", "allowlist", "email", "roles", "flags", "achievements", "cosmetics", "analytics", "audit", "feedback"];

  return (
    <div className={s.root}>
      <TopBar
        breadcrumb="Admin"
        title="Admin Console"
        subtitle="School-wide moderation and catalog management"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <AdminReauthBanner />
      <div className={s.tabs}>
        {tabs.map((t) => (
          <button
            key={t}
            data-testid={`admin-tab-${t}`}
            onClick={() => { setTab(t); setSwitched(true); }}
            className={`${s.tab} ${tab === t ? s.tabActive : ""}`}
          >
            {t}
          </button>
        ))}
      </div>
      <motion.div
        key={tab}
        className={s.body}
        {...(m.fade as MotionProps)}
        initial={switched ? (m.fade.initial as MotionProps["initial"]) : false}
      >
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
      </motion.div>
    </div>
  );
}

// ── Users ────────────────────────────────────────────────────────────────────

function UsersTab() {
  const toast = useToast();
  const m = useMotionPresets();
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
    }, SEARCH_DEBOUNCE_MS);
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
      <div className={`body-serif ${s.lead}`} data-testid="admin-users-summary">
        <AnimatedNumber className={s.strong} value={total} format={plainCount} /> user{total === 1 ? "" : "s"}
        {committedQuery && <> · <span className={s.muted}>filter "{committedQuery}"</span></>}
      </div>
      <div className={`card ${s.flush}`}>
        <div className={s.toolbar}>
          <div className={s.search}>
            <div className={s.searchIcon}>
              <Icon name="search" size={14} />
            </div>
            <input
              placeholder="Search users…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className={`${s.field} ${s.searchField}`}
            />
          </div>
        </div>
        <div className={s.scrollX}>
          <table className={s.table}>
            <HeadRow cols={["User", "Email", "Roles", "Last seen", "Joined", ""]} />
            {/* Re-keyed per page and search, so each new page of rows staggers in. */}
            <motion.tbody key={`${committedQuery}|${page}`} variants={m.list.container} initial="hidden" animate="shown">
              {users.map(u => (
                <motion.tr key={u.id} variants={m.list.item} className={s.row}>
                  <td className={s.td}>
                    <div className={s.userCell}>
                      <Avatar name={u.name || u.email || "?"} size={28} />
                      {u.undecryptable ? (
                        <span
                          data-testid="admin-user-undecryptable"
                          title={`Encrypted with a different key than this server's; can't be read. User id: ${u.id}`}
                          className={s.italicMuted}
                        >
                          Unreadable record
                        </span>
                      ) : u.name ? (
                        <span title={u.name} className={`${s.clip} ${s.name}`}>{u.name}</span>
                      ) : (
                        <span className={s.italicMuted}>No profile name</span>
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
                  <td className={`${s.td} ${s.dim}`}>
                    <span title={u.email ?? undefined} className={s.clip}>{u.email ?? "—"}</span>
                  </td>
                  <td className={s.td}>
                    <div className={s.roleList}>
                      {(u.roles || []).map(r => (
                        <span key={r.id} className={s.roleItem}>
                          <RoleBadge role={r} />
                          <button
                            title="Revoke"
                            onClick={() => revoke(u.id, r.id)}
                            className={s.revoke}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                      {assignFor === u.id ? (
                        <span className={s.assign}>
                          <CustomSelect
                            ariaLabel="Role to add"
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
                          className={`btn btn--sm btn--ghost ${s.addRole}`}
                          onClick={() => { setAssignFor(u.id); setAssignRoleId(""); }}
                        >
                          + role
                        </button>
                      )}
                    </div>
                  </td>
                  <td className={`${s.td} ${s.muted}`}>
                    {u.last_sign_in_at ? new Date(u.last_sign_in_at).toLocaleDateString() : "—"}
                  </td>
                  <td className={`${s.td} ${s.muted}`}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td className={`${s.td} ${s.actionsCell}`}>
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
                </motion.tr>
              ))}
            </motion.tbody>
          </table>
        </div>
        <Pager page={page} totalPages={totalPages} onPage={setPage}>
          Page {page} of {totalPages} · {total} total
        </Pager>
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
      <p data-testid="admin-user-remove-body" className={s.dialogBody}>
        They&apos;ll lose access to Sapling the next time they load a page, and move to the Allowlist as a
        signup. Their account and data are kept, and approving them on the Allowlist lets them back in when
        they next sign in.
      </p>
      <div className={s.dialogActions}>
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
    name: "", slug: "", color: DEFAULT_ROLE_COLOR, icon: "", description: "",
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
      setForm({ name: "", slug: "", color: DEFAULT_ROLE_COLOR, icon: "", description: "", is_staff_assigned: true, is_earnable: false, display_priority: 0 });
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
      <div className={`card ${s.padded}`}>
        <div className={`label-micro ${s.labelGap}`}>Preview</div>
        <RoleProfilePreview
          draftRole={previewRole}
          draftActive={Boolean(form.name.trim())}
          existingRoles={roles}
          userName={userName}
          username={username}
          avatarUrl={avatarUrl}
        />
        <div className={`label-micro ${s.labelGapTop}`}>Create role</div>
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
            className={s.field}
          />
        </LabeledField>
        <LabeledField label="Slug">
          <input
            value={form.slug}
            onChange={e => {
              setSlugEdited(true);
              setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }));
            }}
            className={s.field}
          />
          <div className={s.hint}>
            URL-friendly ID. Auto-filled from name; edit to override.
          </div>
        </LabeledField>
        <LabeledField label="Color">
          <input type="color" value={form.color} onChange={e => setForm(f => ({ ...f, color: e.target.value }))} className={`${s.field} ${s.colorField}`} />
        </LabeledField>
        <LabeledField label="Icon (emoji, optional)">
          <input value={form.icon} onChange={e => setForm(f => ({ ...f, icon: e.target.value }))} placeholder="🛡️ (leave blank to skip)" className={s.field} />
        </LabeledField>
        <LabeledField label="Description">
          <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} className={s.field} />
        </LabeledField>
        <div className={s.checks}>
          <label className={s.checkLabel}>
            <input type="checkbox" checked={form.is_staff_assigned} onChange={e => setForm(f => ({ ...f, is_staff_assigned: e.target.checked }))} /> Staff-assigned
          </label>
          <label className={s.checkLabel}>
            <input type="checkbox" checked={form.is_earnable} onChange={e => setForm(f => ({ ...f, is_earnable: e.target.checked }))} /> Earnable
          </label>
        </div>
        <button className={`btn btn--primary ${s.submit}`} onClick={create} disabled={saving}>
          {saving ? "Creating…" : "Create role"}
        </button>
      </div>
      <div className={`card ${s.flush}`}>
        <div className={s.cardHead}>
          <div className="label-micro">Roles · {roles.length}</div>
        </div>
        {roles.length === 0 && (
          <div className={s.empty}>No roles yet.</div>
        )}
        <StaggerList>
          {roles.map(r => <CatalogRow key={r.id} left={<RoleBadge role={r} />} middle={r.description || r.slug} onDelete={() => del(r.id)} />)}
        </StaggerList>
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
      <div className={`card ${s.padded}`}>
        <div className={`label-micro ${s.labelGap}`}>Create cosmetic</div>
        <LabeledField label="Type">
          <CustomSelect<CosmeticType>
            ariaLabel="Type"
            value={form.type}
            onChange={v => setForm(f => ({ ...f, type: v, asset_url: "", css_value: "" }))}
            options={COSMETIC_TYPES.map(t => ({ value: t, label: t.replace("_", " ") }))}
          />
        </LabeledField>
        <LabeledField label="Name"><input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} className={s.field} /></LabeledField>
        <LabeledField label="Slug"><input value={form.slug} onChange={e => setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }))} className={s.field} /></LabeledField>
        {needsAsset && (
          <LabeledField label="Asset (PNG/SVG)">
            <div className={s.assetRow}>
              <input
                value={form.asset_url}
                onChange={e => setForm(f => ({ ...f, asset_url: e.target.value }))}
                placeholder="Upload or paste URL"
                className={`${s.field} ${s.grow}`}
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
                className={s.hiddenInput}
                onChange={e => onFilePicked(e.target.files?.[0] ?? null)}
              />
            </div>
            {form.asset_url && (
              <img src={form.asset_url} alt="" loading="lazy" decoding="async" className={s.assetPreview} />
            )}
          </LabeledField>
        )}
        {needsCss && (
          <LabeledField label={form.type === "name_color" ? "CSS (color or gradient)" : "CSS (label)"}>
            <input
              value={form.css_value}
              onChange={e => setForm(f => ({ ...f, css_value: e.target.value }))}
              placeholder={form.type === "name_color" ? NAME_COLOR_PLACEHOLDER : "Grandmaster"}
              className={s.field}
            />
          </LabeledField>
        )}
        <LabeledField label="Rarity">
          <CustomSelect<RarityTier>
            ariaLabel="Rarity"
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
            className={s.field}
          />
        </LabeledField>
        <button className={`btn btn--primary ${s.submit}`} onClick={create} disabled={saving || uploading}>
          {saving ? "Creating…" : "Create cosmetic"}
        </button>
      </div>
      <div className={s.stack}>
        {COSMETIC_TYPES.map(t => (
          <div key={t} className={`card ${s.flush}`}>
            <div className={s.groupHead}>
              <div className={`label-micro ${s.uppercase}`}>{t.replace("_", " ")}</div>
              <span className={s.count}>{grouped[t].length}</span>
            </div>
            {grouped[t].length === 0 && (
              <div className={s.emptySmall}>None.</div>
            )}
            <StaggerList>
            {grouped[t].map(c => (
              <CatalogRow
                key={c.id}
                left={c.asset_url ? (
                  <img src={c.asset_url} alt="" width={28} height={28} loading="lazy" decoding="async" className={s.thumb} />
                ) : c.css_value ? (
                  <span className={s.sample} style={{ "--sample-fill": c.css_value } as React.CSSProperties}>
                    sample
                  </span>
                ) : (
                  <span className={s.glyph}>◇</span>
                )}
                middle={
                  <span className={s.nameLine}>
                    <span className={s.bold}>{c.name}</span>
                    <span className={`chip ${s.rarity}`}>{c.rarity}</span>
                  </span>
                }
                sub={c.slug}
                onDelete={() => del(c.id)}
                onExpand={() => toggleOpen(c.id)}
                expanded={openId === c.id}
                expandedContent={
                  <div>
                    <div className={`label-micro ${s.linkLabel}`}>Roles that grant this</div>
                    <div className={s.chipRow}>
                      {allRoles.map(r => {
                        const on = (linkedRoleIdsByCosmetic[c.id] || []).includes(r.id);
                        return (
                          <button
                            key={r.id}
                            className={`chip ${s.linkChip} ${on ? "chip--accent" : s.linkChipOff}`}
                            onClick={() => toggleRoleLink(r.id, c.id)}
                          >
                            {r.name}
                          </button>
                        );
                      })}
                      {allRoles.length === 0 && <span className={s.note}>No roles defined yet.</span>}
                    </div>
                  </div>
                }
              />
            ))}
            </StaggerList>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Analytics ────────────────────────────────────────────────────────────────

function AnalyticsTab() {
  const toast = useToast();
  const m = useMotionPresets();
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
    <div className={s.analytics}>
      <div className="metric-grid">
        <MetricCard label="Users" value={totals.users} />
        <MetricCard label="Approved" value={totals.approved} accent />
        <MetricCard label="Awaiting approval" value={totals.pending} warn={totals.pending > 0} />
        <MetricCard label="Admins" value={totals.admins} />
      </div>
      <div className={`card ${s.padded}`}>
        <div className={`label-micro ${s.labelGap}`}>Signups · last 30 days</div>
        <Sparkline points={signups_by_day} accent />
      </div>
      <div className={`card ${s.padded}`}>
        <div className={`label-micro ${s.labelGap}`}>Approvals · last 30 days</div>
        <Sparkline points={approvals_by_day} />
      </div>
      <div className={`card ${s.flush}`}>
        <div className={s.cardHead}>
          <div className="label-micro">Role membership · {role_counts.length}</div>
        </div>
        {role_counts.length === 0 && (
          <div className={s.empty}>
            Nobody has any roles yet.
          </div>
        )}
        <motion.div variants={m.list.container} initial="hidden" animate="shown">
          {role_counts.map(rc => (
            <motion.div key={rc.slug} variants={m.list.item} className={s.roleCountRow}>
              <span className={s.dot} style={{ "--dot-fill": rc.color } as React.CSSProperties} />
              <span className={s.roleCountName}>{rc.name}</span>
              <AnimatedNumber className={s.roleCount} value={rc.count} format={plainCount} />
            </motion.div>
          ))}
        </motion.div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, accent, warn }: { label: string; value: number; accent?: boolean; warn?: boolean }) {
  const tone = accent ? s.metricAccent : warn ? s.metricWarn : "";
  return (
    <div className={`card ${s.padded}`}>
      <div className="label-micro">{label}</div>
      <div className={`h-serif ${s.metricValue} ${tone}`}>
        <AnimatedNumber value={value} format={plainCount} />
      </div>
    </div>
  );
}

/** The sparkline's drawing box (viewBox units; the SVG stretches to the
 *  card's width and --admin-spark-h), its inset, and its marks. */
const SPARK = { w: 600, h: 80, pad: 4, stroke: 2, dot: 2 } as const;

function Sparkline({ points, accent }: { points: { date: string; count: number }[]; accent?: boolean }) {
  if (points.length === 0) return <div className={s.note}>No data.</div>;
  const { w, h, pad } = SPARK;
  const max = Math.max(1, ...points.map(p => p.count));
  const stepX = (w - pad * 2) / Math.max(1, points.length - 1);
  const path = points.map((p, i) => {
    const x = pad + i * stepX;
    const y = h - pad - (p.count / max) * (h - pad * 2);
    return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  const stroke = accent ? "var(--accent)" : "var(--text-dim)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={s.spark}>
      <path d={path} fill="none" stroke={stroke} strokeWidth={SPARK.stroke} />
      {points.map((p, i) => (
        <circle key={p.date} cx={pad + i * stepX} cy={h - pad - (p.count / max) * (h - pad * 2)} r={SPARK.dot} fill={stroke}>
          <title>{`${p.date}: ${p.count}`}</title>
        </circle>
      ))}
    </svg>
  );
}

// ── Shared row + input helpers ───────────────────────────────────────────────

/** A catalog list whose rows rise in, staggered, as they arrive (after the
 *  first load, or one at a time as an admin creates them). */
function StaggerList({ children }: { children: React.ReactNode }) {
  const m = useMotionPresets();
  return (
    <motion.div variants={m.list.container} initial="hidden" animate="shown">
      {children}
    </motion.div>
  );
}

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
  const m = useMotionPresets();
  return (
    <motion.div variants={m.list.item}>
      <div className={s.catRow}>
        <div className={s.shrink0}>{left}</div>
        <div className={s.grow}>
          <div className={s.catMiddle}>{middle}</div>
          {sub && <div className={s.catSub}>{sub}</div>}
        </div>
        {onExpand && (
          <button className="btn btn--sm btn--ghost" onClick={onExpand}>
            {expanded ? "Hide" : "Manage"}
          </button>
        )}
        <button
          className={`btn btn--sm ${s.deleteBtn} ${del.armed ? `btn--danger ${s.armed}` : "btn--ghost"}`}
          onClick={del.trigger}
        >
          {del.armed ? "Click again" : <Icon name="x" size={12} />}
        </button>
      </div>
      <AnimatePresence initial={false}>
        {expanded && expandedContent && (
          <motion.div key="expanded" {...(m.collapse as MotionProps)}>
            <div className={s.expanded}>
              {expandedContent}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
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
  const m = useMotionPresets();
  return (
    <div className={s.preview}>
      <Avatar name={displayName} img={avatarUrl || undefined} size={44} />
      <div className={s.grow}>
        <div className={s.badges}>
          <span className={s.previewName}>{displayName}</span>
          <AnimatePresence initial={false}>
            {draftActive && (
              <motion.span key="draft" className={s.draftWrap} {...(m.scaleIn as MotionProps)}>
                <RoleBadge role={draftRole} />
                <span className={s.draftTag}>
                  draft
                </span>
              </motion.span>
            )}
          </AnimatePresence>
          {existingRoles.map(r => <RoleBadge key={r.id} role={r} />)}
        </div>
        <div className={s.handle}>{handle}</div>
      </div>
    </div>
  );
}

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className={s.labeled}>
      <div className={`label-micro ${s.labeledLabel}`}>{label}</div>
      {children}
    </div>
  );
}

// ── Audit ─────────────────────────────────────────────────────────────────────
function AuditTab() {
  const toast = useToast();
  const m = useMotionPresets();
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
      <div className={`body-serif ${s.lead}`}>
        <AnimatedNumber className={s.strong} value={total} format={plainCount} /> recorded action{total === 1 ? "" : "s"}
      </div>
      <div className={`card ${s.flush}`}>
        <div className={s.toolbar}>
          <input
            placeholder="action (e.g. user.approve)"
            value={actionFilter}
            onChange={e => { setActionFilter(e.target.value); setPage(1); }}
            className={`${s.field} ${s.filterField}`}
          />
          <input
            placeholder="target_type (e.g. user)"
            value={targetFilter}
            onChange={e => { setTargetFilter(e.target.value); setPage(1); }}
            className={`${s.field} ${s.filterField}`}
          />
        </div>
        <table className={s.table}>
          <HeadRow cols={["When", "Actor", "Action", "Target", "Payload"]} />
          {/* Re-keyed per page and filter, so each new set of entries staggers in. */}
          <motion.tbody key={`${actionFilter}|${targetFilter}|${page}`} variants={m.list.container} initial="hidden" animate="shown">
            {entries.map(e => (
              <motion.tr key={e.id} variants={m.list.item} className={s.row}>
                <td className={`${s.td} ${s.muted} ${s.nowrap}`}>
                  {new Date(e.created_at).toLocaleString()}
                </td>
                <td className={`${s.td} ${s.monoSm}`}>{e.actor_id}</td>
                <td className={s.td}>
                  <span className="chip">{e.action}</span>
                </td>
                <td className={`${s.td} ${s.dim}`}>
                  <span className="chip">{e.target_type}</span>
                  <span className={`${s.targetId} ${s.monoSm}`}>{e.target_id || "—"}</span>
                </td>
                <td className={`${s.td} ${s.payload}`}
                    title={JSON.stringify(e.payload)}>
                  {Object.keys(e.payload || {}).length ? JSON.stringify(e.payload) : "—"}
                </td>
              </motion.tr>
            ))}
          </motion.tbody>
        </table>
        <Pager page={page} totalPages={totalPages} onPage={setPage}>
          Page {page} of {totalPages}
        </Pager>
      </div>
    </>
  );
}

// ── Feedback ─────────────────────────────────────────────────────────────────
function FeedbackTab() {
  const toast = useToast();
  const m = useMotionPresets();
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
      <div className={`card ${s.flush} ${s.feedbackCard}`} data-testid="adminfb-feedback-card">
        <div className={`${s.cardHead} ${s.cardHeadBold}`}>
          Feedback ({feedback.length})
        </div>
        {feedback.length === 0 && (
          <div className={s.emptyDim}>No feedback yet.</div>
        )}
        <motion.div variants={m.list.container} initial="hidden" animate="shown">
        {feedback.map((f) => {
          const stars = Math.max(0, Math.min(MAX_STARS, f.rating));
          return (
          <motion.div key={f.id} variants={m.list.item} className={s.fbRow} data-testid="adminfb-feedback-row">
            <div className={s.fbMeta}>
              <span>{when(f.created_at)}</span>
              <span className={s.strong}>{f.user_name || f.user_id}</span>
              <span>{f.type}</span>
              <span>{"★".repeat(stars)}{"☆".repeat(MAX_STARS - stars)}</span>
              {f.topic && <span>{f.topic}</span>}
            </div>
            {f.comment && <div className={s.fbText}>{f.comment}</div>}
            {f.selected_options.length > 0 && (
              <div className={s.fbOptions}>
                {f.selected_options.join(" · ")}
              </div>
            )}
          </motion.div>
          );
        })}
        </motion.div>
      </div>
      <div className={`card ${s.flush}`} data-testid="adminfb-issues-card">
        <div className={`${s.cardHead} ${s.cardHeadBold}`}>
          Issue reports ({reports.length})
        </div>
        {reports.length === 0 && (
          <div className={s.emptyDim}>No issue reports yet.</div>
        )}
        <motion.div variants={m.list.container} initial="hidden" animate="shown">
        {reports.map((r) => (
          <motion.div key={r.id} variants={m.list.item} className={s.fbRow} data-testid="adminfb-issue-row">
            <div className={s.fbMeta}>
              <span>{when(r.created_at)}</span>
              <span className={s.strong}>{r.user_name || r.user_id}</span>
              <span>{r.topic}</span>
              {r.screenshot_urls.length > 0 && <span>{r.screenshot_urls.length} screenshot(s)</span>}
            </div>
            <div className={s.fbText}>{r.description}</div>
          </motion.div>
        ))}
        </motion.div>
      </div>
    </>
  );
}
