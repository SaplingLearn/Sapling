"use client";
import React from "react";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { Avatar } from "../Avatar";
import { CustomSelect } from "../CustomSelect";
import { ProfileView } from "../ProfileView";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import {
  fetchSettings,
  updateSettings,
  deleteAccount,
  updateProfile,
  checkUsername,
  fetchPublicProfile,
  uploadAvatar,
  fetchCosmetics,
  fetchCosmeticsCatalog,
  equipCosmetic,
  type CatalogCosmetic,
} from "@/lib/api";
import type { UserSettings, UserProfile, UserCosmetic, CosmeticType, EquippedCosmetics } from "@/lib/types";

type Tab = "profile" | "cosmetics" | "preferences" | "notifications" | "data" | "danger";

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <div
      onClick={() => onChange(!on)}
      style={{
        width: 36,
        height: 20,
        borderRadius: "var(--r-full)",
        background: on ? "var(--accent)" : "var(--bg-soft)",
        position: "relative",
        cursor: "pointer",
        transition: "all var(--dur) var(--ease)",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 2,
          left: on ? 18 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "#fff",
          boxShadow: "var(--shadow-sm)",
          transition: "all var(--dur) var(--ease)",
        }}
      />
    </div>
  );
}

type UsernameState = { status: "idle" | "checking" | "available" | "taken" | "invalid"; message?: string };

export function Settings() {
  const toast = useToast();
  const { userId, userName, avatarUrl, userReady, signOut, refreshProfile } = useUser();
  const [tab, setTab] = React.useState<Tab>("profile");
  const [settings, setSettings] = React.useState<UserSettings | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [previewOpen, setPreviewOpen] = React.useState(false);
  const [preview, setPreview] = React.useState<UserProfile | null>(null);
  const [usernameDraft, setUsernameDraft] = React.useState<string>("");
  const [usernameState, setUsernameState] = React.useState<UsernameState>({ status: "idle" });
  const usernameTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    fetchSettings(userId)
      .then(s => { setSettings(s); setUsernameDraft(s.username || ""); })
      .catch((e) => console.error("settings load", e));
  }, [userReady, userId]);

  const patch = async (updates: Partial<UserSettings>) => {
    if (!userId || !settings) return;
    const next = { ...settings, ...updates };
    setSettings(next);
    setSaving(true);
    try {
      await updateSettings(userId, updates);
    } catch (err) {
      console.error("settings save", err);
    } finally {
      setSaving(false);
    }
  };

  const avatarFileRef = React.useRef<HTMLInputElement | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = React.useState(false);

  const handleAvatarFile = async (file: File | null) => {
    if (!file || !userId) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Pick an image file (PNG or JPG).");
      if (avatarFileRef.current) avatarFileRef.current.value = "";
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error(`That file is ${(file.size / 1024 / 1024).toFixed(1)} MB — max is 5 MB.`);
      if (avatarFileRef.current) avatarFileRef.current.value = "";
      return;
    }
    setUploadingAvatar(true);
    try {
      await uploadAvatar(userId, file);
      await refreshProfile();
      toast.success("Avatar updated");
    } catch (err) {
      toast.error(`Upload failed: ${String(err)}`);
    } finally {
      setUploadingAvatar(false);
      if (avatarFileRef.current) avatarFileRef.current.value = "";
    }
  };

  const patchProfile = async (updates: { username?: string; display_name?: string; bio?: string; location?: string; website?: string }) => {
    if (!userId || !settings) return;
    setSaving(true);
    try {
      await updateProfile(userId, updates);
      setSettings(prev => prev ? { ...prev, ...updates } : prev);
    } catch (err) {
      toast.error(`Couldn't save: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  React.useEffect(() => {
    if (usernameTimer.current) clearTimeout(usernameTimer.current);
    const next = usernameDraft.trim().toLowerCase();
    if (!next || next === (settings?.username || "")) {
      setUsernameState({ status: "idle" });
      return;
    }
    setUsernameState({ status: "checking" });
    usernameTimer.current = setTimeout(async () => {
      try {
        const r = await checkUsername(next, userId || undefined);
        if (r.available) setUsernameState({ status: "available", message: "Available" });
        else if (r.reason === "invalid") setUsernameState({ status: "invalid", message: "3–24 chars, lowercase letters, digits, or _" });
        else setUsernameState({ status: "taken", message: "Already taken" });
      } catch {
        setUsernameState({ status: "idle" });
      }
    }, 400);
    return () => { if (usernameTimer.current) clearTimeout(usernameTimer.current); };
  }, [usernameDraft, settings?.username, userId]);

  const openPreview = async () => {
    if (!userId) return;
    try {
      const p = await fetchPublicProfile(userId);
      setPreview(p);
      setPreviewOpen(true);
    } catch (err) {
      toast.error(`Couldn't load preview: ${String(err)}`);
    }
  };

  const handleDelete = async () => {
    if (!userId) return;
    const conf = window.prompt('Type "DELETE" to confirm account deletion.');
    if (conf !== "DELETE") return;
    try {
      await deleteAccount(userId, conf);
      await signOut();
      window.location.href = "/auth";
    } catch (err) {
      alert(String(err));
    }
  };

  const tabs: Tab[] = ["profile", "preferences", "notifications", "data", "danger"];

  return (
    <div>
      <TopBar
        breadcrumb="Home / Settings"
        title="Settings"
        subtitle="Profile, preferences, and account"
        actions={
          <>
            {saving && <span className="chip chip--accent">saving…</span>}
            <button className="btn btn--sm" onClick={openPreview} disabled={!userId}>
              <Icon name="search" size={12} /> Preview profile
            </button>
          </>
        }
      />
      <div style={{ display: "flex", height: "calc(100vh - 112px)" }}>
        <div
          style={{
            width: 200,
            borderRight: "1px solid var(--border)",
            padding: "18px 12px",
            background: "var(--bg-subtle)",
          }}
        >
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "8px 12px",
                fontSize: 13,
                background: tab === t ? "var(--accent-soft)" : "transparent",
                color: tab === t ? "var(--accent)" : "var(--text-dim)",
                borderRadius: "var(--r-sm)",
                marginBottom: 2,
                fontWeight: tab === t ? 600 : 400,
                textTransform: "capitalize",
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <div style={{ flex: 1, padding: "24px 32px", overflowY: "auto" }}>
          {tab === "profile" && settings && (
            <div style={{ maxWidth: 640 }}>
              <div className="h-serif" style={{ fontSize: 22, marginBottom: 20 }}>Profile</div>
              <div
                className="card"
                style={{ padding: "var(--pad-lg)", display: "flex", gap: 20, alignItems: "center", marginBottom: 16 }}
              >
                <Avatar name={userName || "?"} size={72} img={avatarUrl || undefined} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 18, fontWeight: 600, fontFamily: "var(--font-display)" }}>
                    {userName}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>PNG or JPG, up to 5 MB.</div>
                </div>
                <input
                  ref={avatarFileRef}
                  type="file"
                  accept="image/*"
                  style={{ display: "none" }}
                  onChange={e => handleAvatarFile(e.target.files?.[0] ?? null)}
                />
                <button className="btn btn--sm" onClick={() => avatarFileRef.current?.click()} disabled={uploadingAvatar}>
                  <Icon name="pencil" size={12} /> {uploadingAvatar ? "Uploading…" : "Change avatar"}
                </button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 16, padding: "12px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                <div className="label-micro">Username</div>
                <div>
                  <div style={{ position: "relative" }}>
                    <span style={{ position: "absolute", left: 10, top: 9, fontSize: 13, color: "var(--text-muted)" }}>@</span>
                    <input
                      value={usernameDraft}
                      onChange={e => setUsernameDraft(e.target.value)}
                      onBlur={async () => {
                        const v = usernameDraft.trim().toLowerCase();
                        if (v && v !== (settings.username || "") && usernameState.status === "available") {
                          await patchProfile({ username: v });
                        } else if (!v && settings.username) {
                          setUsernameDraft(settings.username || "");
                        }
                      }}
                      placeholder="your-handle"
                      style={{
                        padding: "8px 12px 8px 26px",
                        background: "var(--bg-input)",
                        border: `1px solid ${usernameState.status === "taken" || usernameState.status === "invalid" ? "var(--err)" : "var(--border)"}`,
                        borderRadius: "var(--r-sm)",
                        fontSize: 13,
                        width: "100%",
                      }}
                    />
                  </div>
                  {usernameState.message && (
                    <div style={{
                      fontSize: 11,
                      marginTop: 4,
                      color: usernameState.status === "available" ? "var(--accent)"
                        : (usernameState.status === "checking" ? "var(--text-muted)" : "var(--err)"),
                    }}>
                      {usernameState.status === "checking" ? "Checking…" : usernameState.message}
                    </div>
                  )}
                </div>
              </div>

              {(
                [
                  ["Display name", "display_name"],
                  ["Bio", "bio"],
                  ["Location", "location"],
                  ["Website", "website"],
                ] as const
              ).map(([label, key]) => (
                <div
                  key={key}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "180px 1fr",
                    gap: 16,
                    padding: "12px 0",
                    borderBottom: "1px solid var(--border)",
                    alignItems: "center",
                  }}
                >
                  <div className="label-micro">{label}</div>
                  <input
                    defaultValue={settings[key] ?? ""}
                    onBlur={(e) => {
                      const v = e.target.value.trim();
                      if (v !== (settings[key] ?? "")) {
                        patchProfile({ [key]: v || undefined });
                      }
                    }}
                    style={{
                      padding: "8px 12px",
                      background: "var(--bg-input)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--r-sm)",
                      fontSize: 13,
                    }}
                  />
                </div>
              ))}
            </div>
          )}

          {tab === "cosmetics" && userId && (
            <CosmeticsManager userId={userId} />
          )}

          {tab === "preferences" && settings && (
            <div style={{ maxWidth: 640 }}>
              <div className="h-serif" style={{ fontSize: 22, marginBottom: 20 }}>Preferences</div>
              {(
                [
                  ["Theme", "theme", ["light", "dark"]],
                  ["Font size", "font_size", ["small", "medium", "large"]],
                  ["Profile visibility", "profile_visibility", ["public", "school", "private"]],
                ] as const
              ).map(([label, key, options]) => (
                <div
                  key={key}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "16px 0",
                    borderBottom: "1px solid var(--border)",
                    gap: 20,
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
                  <div style={{ minWidth: 180 }}>
                    <CustomSelect
                      size="sm"
                      value={(settings[key] as string) ?? options[0]}
                      onChange={(v) => patch({ [key]: v } as Partial<UserSettings>)}
                      options={options.map(o => ({ value: o, label: o[0].toUpperCase() + o.slice(1) }))}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "notifications" && settings && (
            <div style={{ maxWidth: 640 }}>
              <div className="h-serif" style={{ fontSize: 22, marginBottom: 20 }}>Notifications</div>
              {(
                [
                  ["Email", "notification_email"],
                  ["Push", "notification_push"],
                  ["In-app", "notification_in_app"],
                  ["Activity status visible", "activity_status_visible"],
                ] as const
              ).map(([label, key]) => (
                <div
                  key={key}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "14px 0",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <div style={{ fontSize: 13 }}>{label}</div>
                  <Toggle on={Boolean(settings[key])} onChange={(v) => patch({ [key]: v } as Partial<UserSettings>)} />
                </div>
              ))}
            </div>
          )}

          {tab === "data" && (
            <div style={{ maxWidth: 640 }}>
              <div className="h-serif" style={{ fontSize: 22, marginBottom: 20 }}>Your Data</div>
              <div className="card" style={{ padding: "var(--pad-lg)" }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Export your data</div>
                <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 12 }}>
                  Download a JSON bundle of your sessions, notes, and knowledge graph.
                </div>
                <button
                  className="btn btn--sm"
                  onClick={async () => {
                    if (!userId) return;
                    try {
                      const res = await fetch(
                        `${process.env.NEXT_PUBLIC_API_URL}/api/profile/${userId}/export?user_id=${encodeURIComponent(userId)}`,
                        { method: "POST" },
                      );
                      const data = await res.json();
                      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `sapling-export.json`;
                      a.click();
                      URL.revokeObjectURL(url);
                    } catch (err) {
                      alert(String(err));
                    }
                  }}
                >
                  Export
                </button>
              </div>
            </div>
          )}

          {tab === "danger" && (
            <div style={{ maxWidth: 640 }}>
              <div className="h-serif" style={{ fontSize: 22, marginBottom: 20, color: "var(--err)" }}>
                Danger Zone
              </div>
              <div className="card" style={{ padding: "var(--pad-lg)", borderColor: "var(--err)" }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Delete account</div>
                <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 12 }}>
                  Permanently delete your account and all data. This cannot be undone.
                </div>
                <button className="btn btn--sm btn--danger" onClick={handleDelete}>Delete my account</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {previewOpen && preview && (
        <PreviewModal profile={preview} onClose={() => setPreviewOpen(false)} />
      )}
    </div>
  );
}

const COSMETIC_TAB_LABELS: Record<CosmeticType, string> = {
  avatar_frame: "Frames",
  banner: "Banners",
  name_color: "Name colors",
  title: "Titles",
};

type CosmeticView = "owned" | "catalog";

function CosmeticsManager({ userId }: { userId: string }) {
  const toast = useToast();
  const { userName, avatarUrl, refreshProfile } = useUser();
  const [subTab, setSubTab] = React.useState<CosmeticType>("avatar_frame");
  const [view, setView] = React.useState<CosmeticView>("owned");
  const [owned, setOwned] = React.useState<Record<CosmeticType, UserCosmetic[]>>({
    avatar_frame: [], banner: [], name_color: [], title: [],
  });
  const [catalog, setCatalog] = React.useState<Record<CosmeticType, CatalogCosmetic[]>>({
    avatar_frame: [], banner: [], name_color: [], title: [],
  });
  const [equipped, setEquipped] = React.useState<EquippedCosmetics>({});
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [r, c] = await Promise.all([
        fetchCosmetics(userId),
        fetchCosmeticsCatalog(userId),
      ]);
      setOwned(r.cosmetics);
      setEquipped(r.equipped as EquippedCosmetics);
      setCatalog(c.catalog);
    } catch (err) {
      console.error("cosmetics load", err);
    }
  }, [userId]);

  React.useEffect(() => { load(); }, [load]);

  const equippedId = equipped[subTab]?.id ?? null;

  const equip = async (cosmeticId: string | null) => {
    setBusy(true);
    try {
      await equipCosmetic(userId, subTab, cosmeticId);
      await load();
      await refreshProfile();
      toast.success(cosmeticId ? "Equipped" : "Unequipped");
    } catch (err) {
      toast.error(`Couldn't update: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const ownedList = owned[subTab] || [];
  const catalogList = catalog[subTab] || [];
  const lockedCount = catalogList.filter(c => !c.owned).length;

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="h-serif" style={{ fontSize: 22, marginBottom: 12 }}>Cosmetics</div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--border)", marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 4 }}>
          {(Object.keys(COSMETIC_TAB_LABELS) as CosmeticType[]).map(t => (
            <button
              key={t}
              onClick={() => setSubTab(t)}
              style={{
                padding: "8px 14px", fontSize: 13,
                fontWeight: subTab === t ? 600 : 400,
                color: subTab === t ? "var(--text)" : "var(--text-dim)",
                borderBottom: subTab === t ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >
              {COSMETIC_TAB_LABELS[t]}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 4, padding: "4px 0" }}>
          {(["owned", "catalog"] as const).map(v => (
            <button
              key={v}
              onClick={() => setView(v)}
              style={{
                padding: "4px 10px", fontSize: 11, borderRadius: "var(--r-full)",
                background: view === v ? "var(--accent-soft)" : "transparent",
                color: view === v ? "var(--accent)" : "var(--text-dim)",
                border: `1px solid ${view === v ? "var(--accent-border)" : "var(--border)"}`,
                textTransform: "capitalize",
              }}
            >
              {v === "catalog" ? `Catalog · ${catalogList.length}` : `Owned · ${ownedList.length}`}
            </button>
          ))}
        </div>
      </div>

      {view === "owned" ? (
        ownedList.length === 0 ? (
          <div className="card" style={{ padding: 28, textAlign: "center", color: "var(--text-muted)" }}>
            No {COSMETIC_TAB_LABELS[subTab].toLowerCase()} unlocked yet.
            {catalogList.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <button className="btn btn--sm" onClick={() => setView("catalog")}>
                  Browse catalog ({catalogList.length})
                </button>
              </div>
            )}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
            {ownedList.map(uc => {
              const c = uc.cosmetic;
              const isEquipped = equippedId === c.id;
              return (
                <CosmeticCard
                  key={c.id}
                  cosmetic={c}
                  userName={userName}
                  avatarUrl={avatarUrl}
                  isEquipped={isEquipped}
                  locked={false}
                  disabled={busy}
                  onClick={() => equip(isEquipped ? null : c.id)}
                />
              );
            })}
          </div>
        )
      ) : (
        <>
          {catalogList.length === 0 ? (
            <div className="card" style={{ padding: 28, textAlign: "center", color: "var(--text-muted)" }}>
              Nothing in the catalog yet.
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
              {catalogList.map(c => {
                const isEquipped = equippedId === c.id;
                return (
                  <CosmeticCard
                    key={c.id}
                    cosmetic={c}
                    userName={userName}
                    avatarUrl={avatarUrl}
                    isEquipped={isEquipped}
                    locked={!c.owned}
                    unlockSource={c.unlock_source}
                    disabled={busy}
                    onClick={c.owned ? () => equip(isEquipped ? null : c.id) : undefined}
                  />
                );
              })}
            </div>
          )}
          {lockedCount > 0 && (
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 12, textAlign: "center" }}>
              {lockedCount} locked · earn achievements or unlock via the ways shown on each card.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CosmeticCard({
  cosmetic, userName, avatarUrl, isEquipped, locked, unlockSource, disabled, onClick,
}: {
  cosmetic: UserCosmetic["cosmetic"];
  userName: string;
  avatarUrl: string;
  isEquipped: boolean;
  locked: boolean;
  unlockSource?: string | null;
  disabled: boolean;
  onClick?: () => void;
}) {
  return (
    <div
      className="card"
      style={{
        padding: 12,
        display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
        borderTop: `3px solid var(--rarity-${cosmetic.rarity}, var(--border))`,
        outline: isEquipped ? "2px solid var(--accent)" : "none",
        outlineOffset: -1,
        opacity: locked ? 0.6 : 1,
        position: "relative",
      }}
    >
      {locked && (
        <span
          className="chip"
          style={{ position: "absolute", top: 8, right: 8, fontSize: 9, textTransform: "uppercase" }}
          title={unlockSource || "Locked"}
        >
          🔒 locked
        </span>
      )}
      <CosmeticPreview cosmetic={cosmetic} userName={userName} avatarUrl={avatarUrl} />
      <div style={{ fontSize: 12, fontWeight: 600, textAlign: "center" }}>{cosmetic.name}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {cosmetic.rarity}
      </div>
      {locked ? (
        <div style={{ fontSize: 10, color: "var(--text-muted)", textAlign: "center", minHeight: 14 }}>
          {unlockSource ? `Unlock: ${unlockSource}` : "Locked"}
        </div>
      ) : (
        <button
          className={`btn btn--sm ${isEquipped ? "" : "btn--primary"}`}
          onClick={onClick}
          disabled={disabled || !onClick}
          style={{ width: "100%" }}
        >
          {isEquipped ? "Unequip" : "Equip"}
        </button>
      )}
    </div>
  );
}

function CosmeticPreview({
  cosmetic, userName, avatarUrl,
}: {
  cosmetic: UserCosmetic["cosmetic"];
  userName: string;
  avatarUrl: string;
}) {
  if (cosmetic.type === "avatar_frame") {
    return (
      <div style={{ position: "relative", width: 64, height: 64 }}>
        <Avatar name={userName || "?"} size={52} img={avatarUrl || undefined} />
        {cosmetic.asset_url && (
          <img
            src={cosmetic.asset_url}
            alt=""
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", objectFit: "contain" }}
          />
        )}
      </div>
    );
  }
  if (cosmetic.type === "banner" && cosmetic.asset_url) {
    return (
      <div style={{ width: "100%", height: 48, borderRadius: "var(--r-sm)", overflow: "hidden", border: "1px solid var(--border)" }}>
        <img src={cosmetic.asset_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    );
  }
  if (cosmetic.type === "name_color") {
    const css = cosmetic.css_value || "var(--text)";
    const isGradient = /gradient\(/i.test(css);
    const style: React.CSSProperties = isGradient
      ? { backgroundImage: css, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }
      : { color: css };
    return <div className="h-serif" style={{ fontSize: 18, fontWeight: 600, ...style }}>{userName || "Preview"}</div>;
  }
  if (cosmetic.type === "title") {
    return (
      <span className="chip" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.1em" }}>
        {cosmetic.css_value || cosmetic.name}
      </span>
    );
  }
  return null;
}

function PreviewModal({ profile, onClose }: { profile: UserProfile; onClose: () => void }) {
  React.useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 120,
        background: "rgba(19,38,16,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--bg)", borderRadius: "var(--r-lg)",
          border: "1px solid var(--border)",
          maxWidth: 920, width: "100%", maxHeight: "88vh", overflow: "auto",
        }}
      >
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "14px 20px", borderBottom: "1px solid var(--border)",
          position: "sticky", top: 0, background: "var(--bg)", zIndex: 1,
        }}>
          <div className="label-micro">Profile preview</div>
          <button className="btn btn--sm btn--ghost" onClick={onClose} aria-label="Close">
            <Icon name="x" size={12} /> Close
          </button>
        </div>
        <div style={{ padding: 20 }}>
          <ProfileView profile={profile} embedded />
        </div>
      </div>
    </div>
  );
}
