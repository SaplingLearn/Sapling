"use client";
import { PanelModal } from "@/components/ui/PanelModal";
import React from "react";
import Link from "next/link";
import { TopBar } from "../TopBar";
import { FullHeightScreen } from "../FullHeightScreen";
import { Icon } from "../Icon";
import { Avatar } from "../Avatar";
import { CustomSelect } from "../CustomSelect";
import { ProfileView } from "../ProfileView";
import { SettingsFormSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import {
  updateSettings,
  deleteAccount,
  updateProfile,
  checkUsername,
  fetchPublicProfile,
  uploadAvatar,
  fetchCosmetics,
  fetchCosmeticsCatalog,
  equipCosmetic,
  exportData,
  type CatalogCosmetic,
} from "@/lib/api";
import type { UserSettings, UserProfile, UserCosmetic, CosmeticType, EquippedCosmetics } from "@/lib/types";
import { useLayoutPref, type LayoutPref } from "@/lib/useLayoutPref";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { readAccountSettings } from "@/lib/accountSettings";
import {
  getAnalyticsState,
  getServerAnalyticsState,
  chooseAnalytics,
  subscribeAnalytics,
  type AnalyticsState,
} from "@/lib/analytics";
import {
  usernameBorderColor,
  usernameMessageColor,
  usernameMessageText,
  type UsernameState,
} from "./settingsUsername";
import { humanizeError } from "@/lib/errorMessage";
import { sentenceCase } from "@/lib/sentenceCase";
import { cn } from "@/lib/cn";

type Tab = "profile" | "cosmetics" | "preferences" | "notifications" | "data";

/**
 * The settings on/off switch: a real `<button role="switch">`, so it is
 * focusable, keyboard-operable and announces its state. Name it with
 * `ariaLabelledBy` (the id of its visible label).
 */
function Toggle({
  on,
  onChange,
  disabled = false,
  ariaLabelledBy,
  testId,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  ariaLabelledBy?: string;
  testId?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-labelledby={ariaLabelledBy}
      data-testid={testId}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn("shrink-0 w-9 h-5 p-0 border-0 rounded-[var(--r-full)] relative [transition:all_var(--dur)_var(--ease)]", on ? "bg-accent" : "bg-bg-soft", disabled ? "cursor-not-allowed" : "cursor-pointer", disabled ? "opacity-50" : "opacity-100")}
    >
      <span
        aria-hidden
        className={cn("absolute top-0.5 w-4 h-4 rounded-[50%] bg-accent-fg shadow-sm [transition:all_var(--dur)_var(--ease)]", on ? "left-4.5" : "left-0.5")}
      />
    </button>
  );
}

export function Settings() {
  const toast = useToast();
  const { userId, userName, avatarUrl, userReady, signOut, setAvatarUrl } = useUser();
  const [tab, setTab] = React.useState<Tab>("profile");
  const [settings, setSettings] = React.useState<UserSettings | null>(null);
  const [layoutPref, setLayoutPref] = useLayoutPref();
  // Per-field in-flight saves (#769): a count per settings key, so the
  // "saving…" chip stays up until the LAST overlapping save settles (one
  // shared boolean was cleared by whichever finished first) and a field's own
  // control can tell its save is still running.
  const [savingFields, setSavingFields] = React.useState<Record<string, number>>({});
  const saving = Object.keys(savingFields).length > 0;
  const trackSaving = React.useCallback((keys: string[], delta: 1 | -1) => {
    setSavingFields(prev => {
      const next = { ...prev };
      for (const k of keys) {
        const n = (next[k] ?? 0) + delta;
        if (n > 0) next[k] = n;
        else delete next[k];
      }
      return next;
    });
  }, []);
  // Rollback bookkeeping for patch() (#769). `confirmed` = the last value the
  // server accepted per key; `fieldSeq` = the latest save per key, so only
  // the newest save to a field may roll it back.
  const confirmedRef = React.useRef<Partial<UserSettings>>({});
  const fieldSeq = React.useRef<Record<string, number>>({});
  const usernameReq = useLatestRequest();
  const [previewOpen, setPreviewOpen] = React.useState(false);
  const [preview, setPreview] = React.useState<UserProfile | null>(null);
  const [usernameDraft, setUsernameDraft] = React.useState<string>("");
  const [usernameState, setUsernameState] = React.useState<UsernameState>({ status: "idle" });
  const usernameTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    // The `/settings` payload can come back with the profile identity fields
    // (display name, username, bio, location, website) unset, which would
    // leave the Profile form blank and risk a save wiping the stored values.
    // Seed those fields from the public profile as a fallback so the inputs
    // reflect what's actually stored. The profile fetch is best-effort — a
    // failure there must not block settings from loading.
    // readAccountSettings shares one in-flight GET with the UserProvider's
    // analytics read and feeds `analytics_opt_out` to the analytics switch
    // below (lib/accountSettings.ts), so the form and the switch agree.
    Promise.all([
      readAccountSettings(userId),
      fetchPublicProfile(userId).catch(() => null),
    ])
      .then(([s, profile]) => {
        const seeded: UserSettings = {
          ...s,
          display_name: s.display_name || profile?.name || null,
          username: s.username || profile?.username || null,
          bio: s.bio || profile?.bio || null,
          location: s.location || profile?.location || null,
          website: s.website || profile?.website || null,
        };
        setSettings(seeded);
        confirmedRef.current = { ...seeded };
        setUsernameDraft(seeded.username || "");
        if (seeded.accent_color) {
          document.documentElement.style.setProperty("--accent", seeded.accent_color);
        }
      })
      .catch((e) => console.error("settings load", e));
  }, [userReady, userId]);

  // Optimistic, with rollback (#769): the control flips at once; if the save
  // fails, each field this save still owns (no newer save to it since) goes
  // back to the last value the server accepted, and the student is told.
  const patch = async (updates: Partial<UserSettings>) => {
    if (!userId || !settings) return;
    const keys = Object.keys(updates) as (keyof UserSettings)[];
    const mySeq: Record<string, number> = {};
    for (const k of keys) mySeq[k] = fieldSeq.current[k] = (fieldSeq.current[k] ?? 0) + 1;
    setSettings(prev => (prev ? { ...prev, ...updates } : prev));
    trackSaving(keys, 1);
    try {
      await updateSettings(userId, updates);
      Object.assign(confirmedRef.current, updates);
    } catch (err) {
      console.error("settings save", err);
      const owned = keys.filter(k => fieldSeq.current[k] === mySeq[k]);
      if (owned.length > 0) {
        const revert: Partial<UserSettings> = {};
        for (const k of owned) Object.assign(revert, { [k]: confirmedRef.current[k] });
        setSettings(prev => (prev ? { ...prev, ...revert } : prev));
        if ("accent_color" in revert) {
          // The accent is painted straight onto :root at pick time.
          if (revert.accent_color) document.documentElement.style.setProperty("--accent", revert.accent_color);
          else document.documentElement.style.removeProperty("--accent");
        }
        toast.error("Couldn't save that setting, so it's been changed back. Please try again.");
      }
    } finally {
      trackSaving(keys, -1);
    }
  };

  // Product analytics. The account flag is the single source of truth, for
  // this browser's pageviews and the backend's PostHog mirror alike, so it
  // is saved whether or not this browser sends anything. Opting out stops
  // capture here at once, then saves; opting in saves FIRST and only then
  // starts capture. The switch is disabled while a save is in flight, so
  // toggles cannot overlap (chooseAnalytics also refuses).
  const [analyticsSaving, setAnalyticsSaving] = React.useState(false);
  const setAnalyticsPreference = async (enabled: boolean) => {
    if (!userId || analyticsSaving) return;
    setAnalyticsSaving(true);
    try {
      const result = await chooseAnalytics(userId, enabled, (optOut) =>
        updateSettings(userId, { analytics_opt_out: optOut }),
      );
      if (result === "failed") {
        toast.error(
          enabled
            ? "Couldn't turn product analytics back on. Please try again."
            : "Couldn't save that to your account, so it's off in this browser for this visit only — retry from Settings → Data.",
        );
      }
    } finally {
      setAnalyticsSaving(false);
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

    // Optimistic UI: paint the picked image immediately via a local
    // blob URL so the user sees their face in the avatar circle the
    // instant they pick the file. The actual upload + Supabase
    // round-trip can take 1–3s on slow connections; without this,
    // there's a visible delay between "Avatar updated" toast and
    // the image appearing.
    //
    // We capture the previous URL up front so we can revert on
    // failure, and revoke the blob URL once we either swap to the
    // real Supabase URL or roll back, to free its memory.
    const previousAvatar = avatarUrl;
    const blobUrl = URL.createObjectURL(file);
    setAvatarUrl(blobUrl);
    setUploadingAvatar(true);
    try {
      const result = await uploadAvatar(userId, file);
      // Swap to the canonical Supabase URL with a cache-bust so
      // re-uploads on the same deterministic path actually refresh.
      // No need to call refreshProfile() — we already have the URL,
      // and skipping the extra /api/auth/me round-trip removes ~50–
      // 200ms of latency from the perceived flow.
      const sep = result.avatar_url.includes("?") ? "&" : "?";
      setAvatarUrl(`${result.avatar_url}${sep}v=${Date.now()}`);
      toast.success("Avatar updated");
    } catch (err) {
      // Revert to whatever the user had before so the optimistic
      // paint doesn't leave a ghost of a file that never landed.
      setAvatarUrl(previousAvatar);
      toast.error(humanizeError(err, "Couldn't upload that image. Try again."));
    } finally {
      // Always free the blob URL — whether we swapped to the
      // server URL or reverted, the blob is no longer referenced.
      URL.revokeObjectURL(blobUrl);
      setUploadingAvatar(false);
      if (avatarFileRef.current) avatarFileRef.current.value = "";
    }
  };

  const patchProfile = async (updates: { username?: string; display_name?: string; bio?: string; location?: string; website?: string }) => {
    if (!userId || !settings) return;
    const keys = Object.keys(updates);
    trackSaving(keys, 1);
    try {
      await updateProfile(userId, updates);
      setSettings(prev => prev ? { ...prev, ...updates } : prev);
      Object.assign(confirmedRef.current, updates);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't save your settings. Try again."));
    } finally {
      trackSaving(keys, -1);
    }
  };

  React.useEffect(() => {
    if (usernameTimer.current) clearTimeout(usernameTimer.current);
    const next = usernameDraft.trim().toLowerCase();
    if (!next || next === (settings?.username || "")) {
      usernameReq.cancel();
      setUsernameState({ status: "idle" });
      return;
    }
    setUsernameState({ status: "checking" });
    // Clearing the debounce timer doesn't stop a check already in flight: a
    // late reply for an older draft used to mark THIS draft available (#769).
    const run = usernameReq.begin();
    usernameTimer.current = setTimeout(async () => {
      try {
        const r = await checkUsername(next, userId || undefined);
        if (!run.isCurrent()) return;
        if (r.available) setUsernameState({ status: "available", message: "Available", checked: next });
        else if (r.reason === "invalid") setUsernameState({ status: "invalid", message: "3–24 chars, lowercase letters, digits, or _", checked: next });
        else setUsernameState({ status: "taken", message: "Already taken", checked: next });
      } catch {
        if (run.isCurrent()) setUsernameState({ status: "idle" });
      }
    }, 400);
    return () => {
      if (usernameTimer.current) clearTimeout(usernameTimer.current);
      usernameReq.cancel();
    };
  }, [usernameDraft, settings?.username, userId, usernameReq]);

  const openPreview = async () => {
    if (!userId) return;
    try {
      const p = await fetchPublicProfile(userId);
      setPreview(p);
      setPreviewOpen(true);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't load that preview."));
    }
  };

  const handleDelete = async () => {
    if (!userId) return;
    const conf = window.prompt(
      'Type "DELETE" to delete your account. It is hidden now and its personal data is erased in 30 days.',
    );
    if (conf !== "DELETE") return;
    try {
      await deleteAccount(userId, conf);
      await signOut();
      window.location.href = "/";
    } catch (err) {
      // Was a bare `alert(String(err))`: a browser dialog showing the raw
      // response body. This screen has a toaster like every other one.
      toast.error(humanizeError(err, "Couldn't delete your account. Try again."));
    }
  };

  const tabs: Tab[] = ["profile", "cosmetics", "preferences", "notifications", "data"];

  return (
    <FullHeightScreen>
      <TopBar
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
      {/* Fills whatever `<main>` leaves below TopBar. `minHeight: 0` lets this
          shrink past its content so the panes below scroll internally rather
          than pushing the screen taller than `<main>`. */}
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0 py-6 px-8 overflow-y-auto">
          {!settings && tab !== "cosmetics" && <SettingsFormSkeleton />}
          {tab === "profile" && settings && (
            <div className="max-w-160 my-0 mx-auto">
              <div className="h-serif text-2xl mb-5">Profile</div>
              <div
                className="card p-(--pad-lg) flex gap-5 items-center mb-4"
              >
                <Avatar name={userName || "?"} size={72} img={avatarUrl || undefined} />
                <div className="flex-1">
                  <div className="text-xl font-semibold font-display">
                    {userName}
                  </div>
                  <div className="text-sm text-text-muted mt-0.5">PNG or JPG, up to 5 MB.</div>
                </div>
                <input
                  ref={avatarFileRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={e => handleAvatarFile(e.target.files?.[0] ?? null)}
                />
                <button className="btn btn--sm" onClick={() => avatarFileRef.current?.click()} disabled={uploadingAvatar}>
                  <Icon name="pencil" size={12} /> {uploadingAvatar ? "Uploading…" : "Change avatar"}
                </button>
              </div>
              <div className="settings-field-row">
                <div className="label-micro">Username</div>
                <div>
                  <div className="relative">
                    <span className="absolute left-2.5 top-[9px] text-md text-text-muted">@</span>
                    <input
                      value={usernameDraft}
                      onChange={e => setUsernameDraft(e.target.value)}
                      onBlur={async () => {
                        const v = usernameDraft.trim().toLowerCase();
                        // Save only the draft that was actually verified (#769).
                        if (
                          v && v !== (settings.username || "")
                          && usernameState.status === "available" && usernameState.checked === v
                        ) {
                          await patchProfile({ username: v });
                        } else if (!v && settings.username) {
                          setUsernameDraft(settings.username || "");
                        }
                      }}
                      placeholder="your-handle"
                      className="pt-2 pr-3 pb-2 pl-6.5 bg-bg-input rounded-sm text-md w-full" style={{ border: `1px solid ${usernameBorderColor(usernameState.status)}` }}
                    />
                  </div>
                  {usernameState.message && (
                    <div className="text-xs mt-1" style={{ color: usernameMessageColor(usernameState.status) }}>
                      {usernameMessageText(usernameState)}
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
                <div key={key} className="settings-field-row">
                  <div className="label-micro">{label}</div>
                  <input
                    defaultValue={settings[key] ?? ""}
                    onBlur={(e) => {
                      const v = e.target.value.trim();
                      if (v !== (settings[key] ?? "")) {
                        patchProfile({ [key]: v || undefined });
                      }
                    }}
                    className="py-2 px-3 bg-bg-input border border-border rounded-sm text-md"
                  />
                </div>
              ))}

              <div
                className="flex justify-between items-center py-4 px-0 gap-5 mt-2"
              >
                <div>
                  <div className="text-md font-medium">Sign out</div>
                  <div className="text-xs text-text-dim mt-0.5">
                    End your session on this device.
                  </div>
                </div>
                <button
                  className="btn btn--sm"
                  onClick={async () => {
                    await signOut();
                    window.location.href = "/";
                  }}
                >
                  <Icon name="logout" size={12} /> Sign out
                </button>
              </div>
            </div>
          )}

          {tab === "cosmetics" && userId && (
            <CosmeticsManager userId={userId} />
          )}

          {tab === "preferences" && settings && (
            <div className="max-w-160 my-0 mx-auto">
              <div className="h-serif text-2xl mb-5">Preferences</div>
              <div
                className="flex justify-between items-center py-4 px-0 border-b border-b-border gap-5"
              >
                <div>
                  <div className="text-md font-medium">Layout</div>
                  <div className="text-xs text-text-dim mt-0.5">
                    Choose between a top navigation bar or a full-height sidebar.
                    Falls back to top nav on small screens.
                  </div>
                </div>
                <div className="min-w-45">
                  <CustomSelect
                    size="sm"
                    value={layoutPref}
                    onChange={(v) => setLayoutPref(v as LayoutPref)}
                    options={[
                      { value: "sidebar", label: "Sidebar (default)" },
                      { value: "topnav",  label: "Top nav" },
                    ]}
                  />
                </div>
              </div>
              {(
                [
                  ["Theme", "theme", ["light"]],
                  ["Font size", "font_size", ["small", "medium", "large"]],
                  ["Profile visibility", "profile_visibility", ["public", "school", "private"]],
                ] as const
              ).map(([label, key, options]) => (
                <div
                  key={key}
                  className="flex justify-between items-center py-4 px-0 border-b border-b-border gap-5"
                >
                  <div className="text-md font-medium">{label}</div>
                  <div className="min-w-45">
                    <CustomSelect
                      size="sm"
                      value={(settings[key] as string) ?? options[0]}
                      onChange={(v) => patch({ [key]: v } as Partial<UserSettings>)}
                      options={options.map(o => ({ value: o, label: o[0].toUpperCase() + o.slice(1) }))}
                    />
                  </div>
                </div>
              ))}
              <div
                className="flex justify-between items-center py-4 px-0 border-b border-b-border gap-5"
              >
                <div>
                  <div className="text-md font-medium">Accent color</div>
                  <div className="text-xs text-text-dim mt-0.5">
                    Hue used for highlights and active states.
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {["#2b5221", "#2b8c96", "#e8a33a", "#8a63d2", "#dc2626"].map(c => {
                    const active = (settings.accent_color ?? "#2b5221") === c;
                    return (
                      <button
                        key={c}
                        onClick={() => {
                          document.documentElement.style.setProperty("--accent", c);
                          patch({ accent_color: c });
                        }}
                        aria-label={`Accent ${c}`}
                        className={cn("w-6 h-6 rounded-[50%] cursor-pointer p-0 [transition:transform_var(--dur)_var(--ease)]", active ? "border-2 border-text" : "border-2 border-transparent")} style={{ background: c, outline: active ? `2px solid ${c}` : "none", outlineOffset: 2 }}
                      />
                    );
                  })}
                  <label
                    className="relative w-6 h-6 rounded-[50%] [background:conic-gradient(from_0deg,_#ff6b6b,_#f9d423,_#6bcf7f,_#4dabf7,_#b197fc,_#ff6b6b)] cursor-pointer border-2 border-transparent"
                    title="Custom color"
                  >
                    <input
                      type="color"
                      value={settings.accent_color ?? "#2b5221"}
                      onChange={e => {
                        document.documentElement.style.setProperty("--accent", e.target.value);
                        patch({ accent_color: e.target.value });
                      }}
                      className="absolute inset-0 opacity-0 cursor-pointer"
                    />
                  </label>
                </div>
              </div>
            </div>
          )}

          {tab === "notifications" && settings && (
            <div className="max-w-160 my-0 mx-auto">
              <div className="h-serif text-2xl mb-5">Notifications</div>
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
                  className="flex justify-between items-center py-3.5 px-0 border-b border-b-border"
                >
                  <div className="text-md" id={`settings-toggle-${key}-label`}>{label}</div>
                  <Toggle
                    on={Boolean(settings[key])}
                    onChange={(v) => patch({ [key]: v } as Partial<UserSettings>)}
                    disabled={Boolean(savingFields[key])}
                    ariaLabelledBy={`settings-toggle-${key}-label`}
                    testId={`settings-toggle-${key}`}
                  />
                </div>
              ))}
            </div>
          )}

          {tab === "data" && (
            <div className="max-w-160 my-0 mx-auto">
              <div className="h-serif text-2xl mb-5">Your Data</div>
              <div className="card p-(--pad-lg)">
                <div className="font-semibold mb-1">Export your data</div>
                <div className="text-sm text-text-dim mb-3">
                  Download a JSON bundle of your sessions, notes, and knowledge graph.
                </div>
                <button
                  className="btn btn--sm"
                  onClick={async () => {
                    if (!userId) return;
                    try {
                      const data = await exportData(userId);
                      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `sapling-export.json`;
                      a.click();
                      URL.revokeObjectURL(url);
                      toast.success("Data exported.");
                    } catch (err) {
                      toast.error(humanizeError(err, "Couldn't export your data. Try again."));
                    }
                  }}
                >
                  Export
                </button>
              </div>

              <AnalyticsPreference
                onChange={(enabled) => void setAnalyticsPreference(enabled)}
                onRetry={() => void setAnalyticsPreference(false)}
                onReload={() => {
                  // Feeds the switch through lib/accountSettings.ts; a failure
                  // shows as `unreadable` again, with this button.
                  if (userId) readAccountSettings(userId).catch(() => {});
                }}
                saving={analyticsSaving}
              />

              <div
                className="h-serif text-xl mt-7 mx-0 mb-3 text-err"
              >
                Danger Zone
              </div>
              <div className="card p-(--pad-lg) border-err">
                <div className="font-semibold mb-1">Delete account</div>
                <div className="text-sm text-text-dim mb-3">
                  Your account is hidden and you are signed out right away, and your Google and
                  Gradescope connections are removed. Your personal data is permanently erased
                  30 days later. Records without your content (AI usage and cost, usage
                  telemetry) are kept; see section 5 of the{" "}
                  <Link href="/privacy" className="text-accent">
                    Privacy Policy
                  </Link>
                  .
                </div>
                <button className="btn btn--sm btn--danger" onClick={handleDelete}>Delete my account</button>
              </div>
            </div>
          )}
        </div>
        <div
          className="w-50 shrink-0 border-l border-l-border py-4.5 px-3 bg-bg-subtle overflow-y-auto"
        >
          {tabs.map((t) => (
            <button
              key={t}
              data-testid={`settings-tab-${t}`}
              onClick={() => setTab(t)}
              className={cn("block w-full text-left py-2 px-3 text-md rounded-sm mb-0.5 capitalize [transition:background_var(--dur-fast)_var(--ease),_color_var(--dur-fast)_var(--ease)]", tab === t ? "bg-bg-soft" : "bg-transparent", tab === t ? "text-text" : "text-text-dim", tab === t ? "font-semibold" : "font-normal")}
            >
              {t}
            </button>
          ))}
          {/* Connected accounts lives at its own route so we can list providers
              independently of the in-page tab state. Styled like a tab button
              for visual continuity with the rest of the sidebar. */}
          <Link
            href="/settings/connections"
            className="block w-full text-left py-2 px-3 text-md text-text-dim rounded-sm mt-1.5 no-underline border-t border-t-border pt-3.5 [transition:background_var(--dur-fast)_var(--ease),_color_var(--dur-fast)_var(--ease)]"
          >
            Connected accounts ↗
          </Link>
        </div>
      </div>

      {previewOpen && preview && (
        <PreviewModal profile={preview} onClose={() => setPreviewOpen(false)} />
      )}
    </FullHeightScreen>
  );
}

/** The status line under the analytics switch, per state — what is actually true. */
const ANALYTICS_NOTES: Record<AnalyticsState, string> = {
  unknown: "Loading your saved setting…",
  unreadable: "We couldn't load your saved setting, so we can't show it yet.",
  unset:
    "No choice is saved to your account yet, so this browser sends no page views. Switch it on to share usage data.",
  on: "On — saved to your account, so it applies wherever you sign in. Nothing about it is stored in your browser.",
  on_browser_blocked:
    "On — saved to your account. Your browser's Do Not Track or Global Privacy Control signal is on, so this browser sends no page views and we share no actions from its requests, but some background processing on your documents can still be shared; switch this off to opt out of everything, wherever you sign in.",
  on_not_running:
    "On — saved to your account. Page views couldn't start in this browser (a blocker may have stopped them).",
  off: "Off — saved to your account, so none of this is shared, wherever you sign in.",
  off_unsaved:
    "Off in this browser for this visit only — we couldn't save it to your account, so our servers may still share usage data, and it will be back on next visit.",
};

/**
 * Product-analytics opt-out (PostHog). It follows the signed-in student's
 * ACCOUNT (`analytics_opt_out`), which governs both this browser's pageviews
 * and the backend's own PostHog mirror (#677) — so the switch is usable as
 * soon as the account has answered, whether or not this build sends
 * pageviews, the admin `product_analytics` flag is on, or DNT/GPC is set
 * (src/lib/analytics.ts). It is disabled only until that answer arrives (with
 * a "Try again" after a failed read) and while a save is in flight. After a
 * failed opt-out save it shows "off in this browser for this visit only"
 * with a retry, never "saved".
 */
function AnalyticsPreference({
  onChange,
  onRetry,
  onReload,
  saving,
}: {
  onChange: (enabled: boolean) => void;
  onRetry: () => void;
  onReload: () => void;
  saving: boolean;
}) {
  const state = React.useSyncExternalStore(
    subscribeAnalytics,
    getAnalyticsState,
    getServerAnalyticsState,
  );
  const on = state === "on" || state === "on_browser_blocked" || state === "on_not_running";
  const loaded = state !== "unknown" && state !== "unreadable";

  return (
    <div className="card p-(--pad-lg) mt-4" data-testid="settings-analytics">
      <div className="flex justify-between items-start gap-5">
        <div>
          <div className="font-semibold mb-1" id="settings-analytics-label">
            Product analytics
          </div>
          <div className="text-sm text-text-dim">
            Share how you use Sapling with PostHog, our analytics provider, so we can see what to
            improve: the app pages you view (with basic browser and device details, but not your IP
            address), actions you take (like starting a quiz, messaging the
            tutor or uploading a document), the AI model, token counts and cost behind each AI
            response, and error reports from our servers. It&apos;s tied to your Sapling account ID —
            never your name or email, and never what you type or the text of your notes, documents,
            messages or AI replies. Turning it off stops all of this within about a minute.{" "}
            <Link href="/privacy" className="text-accent">Privacy Policy</Link>
          </div>
          <div className="text-xs text-text-muted mt-1.5" data-testid="settings-analytics-note">
            {ANALYTICS_NOTES[state]}
            {state === "unreadable" && (
              <>
                {" "}
                <button
                  type="button"
                  className="btn btn--sm ml-1"
                  data-testid="settings-analytics-reload"
                  onClick={onReload}
                >
                  Try again
                </button>
              </>
            )}
            {state === "off_unsaved" && (
              <>
                {" "}
                <button
                  type="button"
                  className="btn btn--sm ml-1"
                  data-testid="settings-analytics-retry"
                  disabled={saving}
                  onClick={onRetry}
                >
                  Retry saving
                </button>
              </>
            )}
          </div>
        </div>
        <Toggle
          on={on}
          onChange={onChange}
          disabled={!loaded || saving}
          ariaLabelledBy="settings-analytics-label"
          testId="settings-analytics-toggle"
        />
      </div>
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
      toast.error(humanizeError(err, "Couldn't update that. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const ownedList = owned[subTab] || [];
  const catalogList = catalog[subTab] || [];
  const lockedCount = catalogList.filter(c => !c.owned).length;

  return (
    <div className="max-w-180 my-0 mx-auto">
      <div className="h-serif text-2xl mb-3">Cosmetics</div>
      <div className="flex justify-between items-center border-b border-b-border mb-4">
        <div className="flex gap-1">
          {(Object.keys(COSMETIC_TAB_LABELS) as CosmeticType[]).map(t => (
            <button
              key={t}
              onClick={() => setSubTab(t)}
              className={cn("py-2 px-3.5 text-md", subTab === t ? "font-semibold" : "font-normal", subTab === t ? "text-text" : "text-text-dim", subTab === t ? "border-b-2 border-b-text" : "border-b-2 border-b-transparent")}
            >
              {COSMETIC_TAB_LABELS[t]}
            </button>
          ))}
        </div>
        <div className="flex gap-1 py-1 px-0">
          {(["owned", "catalog"] as const).map(v => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn("py-1 px-2.5 text-xs rounded-[var(--r-full)] border border-border capitalize", view === v ? "bg-bg-soft" : "bg-transparent", view === v ? "text-text" : "text-text-dim")}
            >
              {v === "catalog" ? `Catalog · ${catalogList.length}` : `Owned · ${ownedList.length}`}
            </button>
          ))}
        </div>
      </div>

      {view === "owned" ? (
        ownedList.length === 0 ? (
          <div className="card p-7 text-center text-text-muted">
            No {COSMETIC_TAB_LABELS[subTab].toLowerCase()} unlocked yet.
            {catalogList.length > 0 && (
              <div className="mt-2">
                <button className="btn btn--sm" onClick={() => setView("catalog")}>
                  Browse catalog ({catalogList.length})
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,_minmax(180px,_1fr))] gap-3">
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
            <div className="card p-7 text-center text-text-muted">
              Nothing in the catalog yet.
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,_minmax(180px,_1fr))] gap-3">
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
            <div className="text-xs text-text-muted mt-3 text-center">
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
      className={cn("card", "p-3 flex flex-col items-center gap-2 [outline-offset:-1px] relative", isEquipped ? "[outline:2px_solid_var(--accent)]" : "outline-none", locked ? "opacity-60" : "opacity-100")}
      style={{ borderTop: `3px solid var(--rarity-${cosmetic.rarity}, var(--border))` }}
    >
      {locked && (
        <span
          className="chip absolute top-2 right-2 text-xs"
          title={unlockSource || "Locked"}
        >
          🔒 locked
        </span>
      )}
      <CosmeticPreview cosmetic={cosmetic} userName={userName} avatarUrl={avatarUrl} />
      <div className="text-sm font-semibold text-center">{cosmetic.name}</div>
      <div className="text-sm text-text-muted">{sentenceCase(cosmetic.rarity)}</div>
      {locked ? (
        <div className="text-2xs text-text-muted text-center min-h-3.5">
          {unlockSource ? `Unlock: ${unlockSource}` : "Locked"}
        </div>
      ) : (
        <button
          className={cn(`btn btn--sm ${isEquipped ? "" : "btn--primary"}`, "w-full")}
          onClick={onClick}
          disabled={disabled || !onClick}
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
      <div className="relative w-16 h-16">
        <Avatar name={userName || "?"} size={52} img={avatarUrl || undefined} />
        {cosmetic.asset_url && (
          <img
            src={cosmetic.asset_url}
            alt=""
            width={64}
            height={64}
            loading="lazy"
            decoding="async"
            className="absolute inset-0 w-full h-full pointer-events-none object-contain"
          />
        )}
      </div>
    );
  }
  if (cosmetic.type === "banner" && cosmetic.asset_url) {
    return (
      <div className="w-full h-12 rounded-sm overflow-hidden border border-border">
        <img src={cosmetic.asset_url} alt="" width={180} height={48} loading="lazy" decoding="async" className="w-full h-full object-cover" />
      </div>
    );
  }
  if (cosmetic.type === "name_color") {
    const css = cosmetic.css_value || "var(--text)";
    const isGradient = /gradient\(/i.test(css);
    const style: React.CSSProperties = isGradient
      ? { backgroundImage: css, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }
      : { color: css };
    return <div className="h-serif text-xl font-semibold" style={{ ...style }}>{userName || "Preview"}</div>;
  }
  if (cosmetic.type === "title") {
    return (
      <span className="chip text-sm">
        {cosmetic.css_value || cosmetic.name}
      </span>
    );
  }
  return null;
}

function PreviewModal({ profile, onClose }: { profile: UserProfile; onClose: () => void }) {
  return (
    <PanelModal label="Profile preview" onClose={onClose} maxWidth="max-w-230" maxHeight="max-h-[88vh]">
        <div className="p-5">
          <ProfileView profile={profile} embedded />
        </div>
    </PanelModal>
  );
}
