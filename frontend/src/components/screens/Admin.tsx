"use client";
import React from "react";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Avatar } from "../Avatar";
import { RoleBadge } from "../RoleBadge";
import { CustomSelect } from "../CustomSelect";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useUser } from "@/context/UserContext";
import {
  adminFetchUsers, adminApproveUser,
  adminListRoles, adminCreateRole, adminDeleteRole, adminAssignRole, adminRevokeRole,
  adminListAchievements, adminCreateAchievement, adminDeleteAchievement, adminGrantAchievement,
  adminListCosmetics, adminCreateCosmetic, adminDeleteCosmetic,
  IS_LOCAL_MODE,
} from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Role, Achievement, Cosmetic, CosmeticType, RarityTier, AchievementCategory } from "@/lib/types";

type Tab = "users" | "roles" | "achievements" | "cosmetics" | "analytics";
type AdminUser = {
  id: string;
  name: string;
  email: string;
  is_approved: boolean;
  is_admin?: boolean;
  last_sign_in?: string | null;
  created_at?: string;
  roles?: Role[];
};

const RARITIES: RarityTier[] = ["common", "uncommon", "rare", "epic", "legendary"];
const ACH_CATS: AchievementCategory[] = ["activity", "social", "milestone", "special"];
const COSMETIC_TYPES: CosmeticType[] = ["avatar_frame", "banner", "name_color", "title"];

const COSMETIC_BUCKET = "cosmetic-assets";

async function uploadCosmeticAsset(file: File): Promise<string> {
  if (IS_LOCAL_MODE) return URL.createObjectURL(file);
  const ext = file.name.split(".").pop() || "png";
  const path = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}.${ext}`;
  const { error } = await supabase.storage.from(COSMETIC_BUCKET).upload(path, file, { cacheControl: "3600", upsert: false });
  if (error) throw error;
  const { data } = supabase.storage.from(COSMETIC_BUCKET).getPublicUrl(path);
  return data.publicUrl;
}

export function Admin() {
  const { isAdmin } = useUser();
  const [tab, setTab] = React.useState<Tab>("users");

  if (!isAdmin) {
    return (
      <div>
        <TopBar breadcrumb="Admin" title="Admin Console" subtitle="Staff only" />
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}>
          You don&apos;t have admin access.
        </div>
      </div>
    );
  }

  const tabs: Tab[] = ["users", "roles", "achievements", "cosmetics", "analytics"];

  return (
    <div>
      <TopBar
        breadcrumb="Admin"
        title="Admin Console"
        subtitle="School-wide moderation and catalog management"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <div style={{ padding: "12px 32px", borderBottom: "1px solid var(--border)", display: "flex", gap: 4, overflowX: "auto" }}>
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: tab === t ? 600 : 400,
              color: tab === t ? "var(--text)" : "var(--text-dim)",
              borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent",
              textTransform: "capitalize",
              whiteSpace: "nowrap",
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <div style={{ padding: "24px 32px" }}>
        {tab === "users" && <UsersTab />}
        {tab === "roles" && <RolesTab />}
        {tab === "achievements" && <AchievementsTab />}
        {tab === "cosmetics" && <CosmeticsTab />}
        {tab === "analytics" && <AnalyticsTab />}
      </div>
    </div>
  );
}

// ── Users ────────────────────────────────────────────────────────────────────

function UsersTab() {
  const toast = useToast();
  const { userId: me } = useUser();
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  const [roles, setRoles] = React.useState<Role[]>([]);
  const [query, setQuery] = React.useState("");
  const [assignFor, setAssignFor] = React.useState<string | null>(null);
  const [assignRoleId, setAssignRoleId] = React.useState<string>("");

  const load = React.useCallback(async () => {
    try {
      const [u, r] = await Promise.all([adminFetchUsers(), adminListRoles()]);
      setUsers(u.users || []);
      setRoles(r.roles || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  const filtered = query
    ? users.filter(u =>
        (u.name || "").toLowerCase().includes(query.toLowerCase()) ||
        (u.email || "").toLowerCase().includes(query.toLowerCase()))
    : users;

  const approved = users.filter(u => u.is_approved).length;
  const pending = users.length - approved;

  const assign = async (uid: string) => {
    if (!assignRoleId) return;
    try {
      await adminAssignRole(uid, assignRoleId, me);
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

  const approvedPct = users.length ? Math.round((approved / users.length) * 100) : 0;
  return (
    <>
      {/* Prose strip replaces the previous 3-card hero-metric layout
          (anti-pattern: big-number + small-label + gradient accent). */}
      <div className="body-serif" style={{
        fontSize: 15, marginBottom: 22, color: "var(--text-dim)", maxWidth: 680,
      }}>
        <span style={{ color: "var(--text)" }}>{users.length}</span> student{users.length === 1 ? "" : "s"} · {" "}
        <span style={{ color: "var(--accent)" }}>{approved} approved</span>
        {users.length > 0 && <span> ({approvedPct}%)</span>}
        {pending > 0 && <> · <span style={{ color: "var(--warn)" }}>{pending} waiting</span></>}
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ display: "flex", padding: "12px 16px", borderBottom: "1px solid var(--border)", alignItems: "center", gap: 12 }}>
          <div style={{ position: "relative", flex: 1, maxWidth: 300 }}>
            <div style={{ position: "absolute", left: 10, top: 8, color: "var(--text-muted)" }}>
              <Icon name="search" size={14} />
            </div>
            <input
              placeholder="Search users…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              style={{
                width: "100%", padding: "7px 12px 7px 32px",
                border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
                fontSize: 13, background: "var(--bg-input)",
              }}
            />
          </div>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--bg-subtle)" }}>
              {["User", "Email", "Roles", "Status", "Joined", ""].map(h => (
                <th key={h} style={{ textAlign: "left", padding: "10px 16px", fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(u => (
              <tr key={u.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <Avatar name={u.name || "?"} size={28} />
                    <span style={{ fontWeight: 500 }}>{u.name}</span>
                  </div>
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-dim)" }}>{u.email}</td>
                <td style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
                    {(u.roles || []).map(r => (
                      <span key={r.id} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                        <RoleBadge role={r} />
                        <button
                          title="Revoke"
                          onClick={() => revoke(u.id, r.id)}
                          style={{ color: "var(--text-muted)", padding: "1px 4px" }}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                    {assignFor === u.id ? (
                      <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
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
                        className="btn btn--sm btn--ghost"
                        onClick={() => { setAssignFor(u.id); setAssignRoleId(""); }}
                        style={{ fontSize: 11 }}
                      >
                        + role
                      </button>
                    )}
                  </div>
                </td>
                <td style={{ padding: "10px 16px" }}>
                  <span className={`chip ${u.is_approved ? "chip--accent" : "chip--warn"}`}>
                    {u.is_approved ? "approved" : "pending"}
                  </span>
                </td>
                <td style={{ padding: "10px 16px", color: "var(--text-muted)" }}>
                  {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                </td>
                <td style={{ padding: "10px 16px", textAlign: "right" }}>
                  {!u.is_approved && (
                    <button
                      className="btn btn--sm btn--primary"
                      onClick={async () => { await adminApproveUser(u.id); load(); }}
                    >
                      Approve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
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
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 360px) 1fr", gap: 16 }}>
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>Preview</div>
        <RoleProfilePreview
          draftRole={previewRole}
          draftActive={Boolean(form.name.trim())}
          existingRoles={roles}
          userName={userName}
          username={username}
          avatarUrl={avatarUrl}
        />
        <div className="label-micro" style={{ marginTop: 18, marginBottom: 10 }}>Create role</div>
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
            style={fieldStyle}
          />
        </LabeledField>
        <LabeledField label="Slug">
          <input
            value={form.slug}
            onChange={e => {
              setSlugEdited(true);
              setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }));
            }}
            style={fieldStyle}
          />
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
            URL-friendly ID. Auto-filled from name; edit to override.
          </div>
        </LabeledField>
        <LabeledField label="Color">
          <input type="color" value={form.color} onChange={e => setForm(f => ({ ...f, color: e.target.value }))} style={{ ...fieldStyle, height: 36, padding: 2 }} />
        </LabeledField>
        <LabeledField label="Icon (emoji, optional)">
          <input value={form.icon} onChange={e => setForm(f => ({ ...f, icon: e.target.value }))} placeholder="🛡️ (leave blank to skip)" style={fieldStyle} />
        </LabeledField>
        <LabeledField label="Description">
          <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} style={fieldStyle} />
        </LabeledField>
        <div style={{ display: "flex", gap: 12, marginTop: 6 }}>
          <label style={checkLabel}>
            <input type="checkbox" checked={form.is_staff_assigned} onChange={e => setForm(f => ({ ...f, is_staff_assigned: e.target.checked }))} /> Staff-assigned
          </label>
          <label style={checkLabel}>
            <input type="checkbox" checked={form.is_earnable} onChange={e => setForm(f => ({ ...f, is_earnable: e.target.checked }))} /> Earnable
          </label>
        </div>
        <button className="btn btn--primary" onClick={create} disabled={saving} style={{ marginTop: 14, width: "100%" }}>
          {saving ? "Creating…" : "Create role"}
        </button>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
          <div className="label-micro">Roles · {roles.length}</div>
        </div>
        {roles.length === 0 && (
          <div style={{ padding: 28, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>No roles yet.</div>
        )}
        {roles.map(r => <CatalogRow key={r.id} left={<RoleBadge role={r} />} middle={r.description || r.slug} onDelete={() => del(r.id)} />)}
      </div>
    </div>
  );
}

// ── Achievements ─────────────────────────────────────────────────────────────

function AchievementsTab() {
  const toast = useToast();
  const [items, setItems] = React.useState<Achievement[]>([]);
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  const [form, setForm] = React.useState<{
    name: string; slug: string; description: string; icon: string;
    category: AchievementCategory; rarity: RarityTier; is_secret: boolean;
  }>({ name: "", slug: "", description: "", icon: "", category: "milestone", rarity: "common", is_secret: false });
  const [saving, setSaving] = React.useState(false);
  const [grant, setGrant] = React.useState<{ userId: string; achievementId: string }>({ userId: "", achievementId: "" });
  const [granting, setGranting] = React.useState(false);

  const load = async () => {
    try {
      const [r, u] = await Promise.all([adminListAchievements(), adminFetchUsers()]);
      setItems(r.achievements || []);
      setUsers(u.users || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    }
  };
  React.useEffect(() => { load(); }, []);

  const doGrant = async () => {
    if (!grant.userId || !grant.achievementId) {
      toast.warn("Pick a user and an achievement.");
      return;
    }
    setGranting(true);
    try {
      await adminGrantAchievement(grant.userId, grant.achievementId);
      toast.success("Achievement granted");
      setGrant({ userId: "", achievementId: "" });
    } catch (err) {
      toast.error(`Grant failed: ${String(err)}`);
    } finally {
      setGranting(false);
    }
  };

  const create = async () => {
    if (!form.name.trim() || !form.slug.trim()) {
      toast.warn("Name and slug are required.");
      return;
    }
    setSaving(true);
    try {
      await adminCreateAchievement({
        name: form.name.trim(),
        slug: form.slug.trim(),
        description: form.description.trim() || null,
        icon: form.icon.trim() || null,
        category: form.category,
        rarity: form.rarity,
        is_secret: form.is_secret,
      });
      setForm({ name: "", slug: "", description: "", icon: "", category: "milestone", rarity: "common", is_secret: false });
      await load();
      toast.success("Achievement created");
    } catch (err) {
      toast.error(`Create failed: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const del = async (id: string) => {
    try {
      await adminDeleteAchievement(id);
      await load();
      toast.success("Achievement deleted");
    } catch (err) {
      toast.error(`Delete failed: ${String(err)}`);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 360px) 1fr", gap: 16 }}>
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>Create achievement</div>
        <LabeledField label="Name"><input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} style={fieldStyle} /></LabeledField>
        <LabeledField label="Slug"><input value={form.slug} onChange={e => setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }))} style={fieldStyle} /></LabeledField>
        <LabeledField label="Description"><textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} style={fieldStyle} /></LabeledField>
        <LabeledField label="Icon (emoji)"><input value={form.icon} onChange={e => setForm(f => ({ ...f, icon: e.target.value }))} placeholder="🏆" style={fieldStyle} /></LabeledField>
        <LabeledField label="Category">
          <CustomSelect<AchievementCategory>
            value={form.category}
            onChange={v => setForm(f => ({ ...f, category: v }))}
            options={ACH_CATS.map(c => ({ value: c, label: c }))}
          />
        </LabeledField>
        <LabeledField label="Rarity">
          <CustomSelect<RarityTier>
            value={form.rarity}
            onChange={v => setForm(f => ({ ...f, rarity: v }))}
            options={RARITIES.map(r => ({ value: r, label: r }))}
          />
        </LabeledField>
        <label style={{ ...checkLabel, marginTop: 6 }}>
          <input type="checkbox" checked={form.is_secret} onChange={e => setForm(f => ({ ...f, is_secret: e.target.checked }))} /> Secret (hidden until earned)
        </label>
        <button className="btn btn--primary" onClick={create} disabled={saving} style={{ marginTop: 14, width: "100%" }}>
          {saving ? "Creating…" : "Create achievement"}
        </button>

        <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Grant to user</div>
          <LabeledField label="User">
            <CustomSelect
              size="sm"
              value={grant.userId}
              onChange={v => setGrant(g => ({ ...g, userId: v }))}
              options={users.map(u => ({ value: u.id, label: u.name || u.email, description: u.email }))}
              placeholder="Pick a user…"
            />
          </LabeledField>
          <LabeledField label="Achievement">
            <CustomSelect
              size="sm"
              value={grant.achievementId}
              onChange={v => setGrant(g => ({ ...g, achievementId: v }))}
              options={items.map(a => ({ value: a.id, label: a.name, description: a.rarity }))}
              placeholder="Pick one…"
            />
          </LabeledField>
          <button
            className="btn"
            onClick={doGrant}
            disabled={granting || !grant.userId || !grant.achievementId}
            style={{ width: "100%", marginTop: 4 }}
          >
            {granting ? "Granting…" : "Grant achievement"}
          </button>
        </div>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
          <div className="label-micro">Achievements · {items.length}</div>
        </div>
        {items.length === 0 && <div style={{ padding: 28, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>No achievements yet.</div>}
        {items.map(a => (
          <CatalogRow
            key={a.id}
            left={<span style={{ fontSize: 18 }}>{a.icon || "★"}</span>}
            middle={
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontWeight: 600 }}>{a.name}</span>
                <span className="chip" style={{ textTransform: "uppercase", fontSize: 10 }}>{a.rarity}</span>
                {a.is_secret && <span className="chip chip--warn">secret</span>}
              </span>
            }
            sub={a.description || a.slug}
            onDelete={() => del(a.id)}
          />
        ))}
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
      const url = await uploadCosmeticAsset(file);
      setForm(f => ({ ...f, asset_url: url }));
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
    <div style={{ display: "grid", gridTemplateColumns: "minmax(300px, 380px) 1fr", gap: 16 }}>
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div className="label-micro" style={{ marginBottom: 10 }}>Create cosmetic</div>
        <LabeledField label="Type">
          <CustomSelect<CosmeticType>
            value={form.type}
            onChange={v => setForm(f => ({ ...f, type: v, asset_url: "", css_value: "" }))}
            options={COSMETIC_TYPES.map(t => ({ value: t, label: t.replace("_", " ") }))}
          />
        </LabeledField>
        <LabeledField label="Name"><input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} style={fieldStyle} /></LabeledField>
        <LabeledField label="Slug"><input value={form.slug} onChange={e => setForm(f => ({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }))} style={fieldStyle} /></LabeledField>
        {needsAsset && (
          <LabeledField label="Asset (PNG/SVG)">
            <div style={{ display: "flex", gap: 6 }}>
              <input
                value={form.asset_url}
                onChange={e => setForm(f => ({ ...f, asset_url: e.target.value }))}
                placeholder="Upload or paste URL"
                style={{ ...fieldStyle, flex: 1 }}
              />
              <button
                className="btn btn--sm"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
              >
                <Icon name="up" size={12} /> {uploading ? "…" : "Upload"}
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                style={{ display: "none" }}
                onChange={e => onFilePicked(e.target.files?.[0] ?? null)}
              />
            </div>
            {form.asset_url && (
              <img src={form.asset_url} alt="" style={{ maxHeight: 56, marginTop: 6, borderRadius: "var(--r-sm)", border: "1px solid var(--border)" }} />
            )}
          </LabeledField>
        )}
        {needsCss && (
          <LabeledField label={form.type === "name_color" ? "CSS (color or gradient)" : "CSS (label)"}>
            <input
              value={form.css_value}
              onChange={e => setForm(f => ({ ...f, css_value: e.target.value }))}
              placeholder={form.type === "name_color" ? "linear-gradient(90deg, #ff7e5f, #feb47b)" : "Grandmaster"}
              style={fieldStyle}
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
            style={fieldStyle}
          />
        </LabeledField>
        <button className="btn btn--primary" onClick={create} disabled={saving || uploading} style={{ marginTop: 14, width: "100%" }}>
          {saving ? "Creating…" : "Create cosmetic"}
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {COSMETIC_TYPES.map(t => (
          <div key={t} className="card" style={{ padding: 0 }}>
            <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between" }}>
              <div className="label-micro" style={{ textTransform: "uppercase" }}>{t.replace("_", " ")}</div>
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{grouped[t].length}</span>
            </div>
            {grouped[t].length === 0 && (
              <div style={{ padding: 16, fontSize: 12, color: "var(--text-muted)", textAlign: "center" }}>None.</div>
            )}
            {grouped[t].map(c => (
              <CatalogRow
                key={c.id}
                left={c.asset_url ? (
                  <img src={c.asset_url} alt="" style={{ width: 28, height: 28, borderRadius: "var(--r-sm)", objectFit: "cover", border: "1px solid var(--border)" }} />
                ) : c.css_value ? (
                  <span style={{ padding: "2px 6px", fontSize: 10, borderRadius: "var(--r-sm)", background: c.css_value, color: "#fff", border: "1px solid var(--border)" }}>
                    sample
                  </span>
                ) : (
                  <span style={{ fontSize: 16 }}>◇</span>
                )}
                middle={
                  <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ fontWeight: 600 }}>{c.name}</span>
                    <span className="chip" style={{ fontSize: 10, textTransform: "uppercase" }}>{c.rarity}</span>
                  </span>
                }
                sub={c.slug}
                onDelete={() => del(c.id)}
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
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  React.useEffect(() => { adminFetchUsers().then(r => setUsers(r.users || [])).catch(() => {}); }, []);
  const approved = users.filter(u => u.is_approved).length;
  return (
    <div className="card" style={{ padding: "var(--pad-lg)" }}>
      <div className="label-micro">Overview</div>
      <div className="h-serif" style={{ fontSize: 24, marginTop: 6 }}>{users.length} users</div>
      <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 8 }}>
        {approved} approved · {users.length - approved} pending
      </div>
    </div>
  );
}

// ── Shared row + input helpers ───────────────────────────────────────────────

function CatalogRow({
  left, middle, sub, onDelete,
}: {
  left: React.ReactNode;
  middle: React.ReactNode;
  sub?: string;
  onDelete: () => void;
}) {
  const del = useConfirm(onDelete);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "10px 16px", borderTop: "1px solid var(--border)",
    }}>
      <div style={{ flexShrink: 0 }}>{left}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13 }}>{middle}</div>
        {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
      </div>
      <button
        className={`btn btn--sm ${del.armed ? "btn--danger" : "btn--ghost"}`}
        onClick={del.trigger}
        style={del.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
      >
        {del.armed ? "Click again" : <Icon name="x" size={12} />}
      </button>
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
    <div style={{
      border: "1px solid var(--border)",
      borderRadius: "var(--r-md)",
      padding: 14,
      background: "var(--bg-subtle)",
      display: "flex",
      alignItems: "flex-start",
      gap: 12,
    }}>
      <Avatar name={displayName} img={avatarUrl || undefined} size={44} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", rowGap: 4 }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{displayName}</span>
          {draftActive && (
            <span style={{ position: "relative", display: "inline-flex" }}>
              <RoleBadge role={draftRole} />
              <span style={{
                position: "absolute", top: -6, right: -6,
                fontSize: 8, fontWeight: 600, letterSpacing: "0.05em",
                padding: "1px 4px", borderRadius: 4,
                background: "var(--accent)", color: "#fff",
                textTransform: "uppercase",
              }}>
                draft
              </span>
            </span>
          )}
          {existingRoles.map(r => <RoleBadge key={r.id} role={r} />)}
        </div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>{handle}</div>
      </div>
    </div>
  );
}

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="label-micro" style={{ marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

const fieldStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  border: "1px solid var(--border)",
  borderRadius: "var(--r-sm)",
  fontSize: 13,
  background: "var(--bg-input)",
  fontFamily: "inherit",
};

const checkLabel: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-dim)",
};
