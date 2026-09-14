"use client";
import React from "react";
import { AvatarFrame } from "./AvatarFrame";
import { NameColorRenderer } from "./NameColorRenderer";
import { TitleFlair } from "./TitleFlair";
import { RoleBadge } from "./RoleBadge";
import { Icon } from "./Icon";
import { useToast } from "./ToastProvider";
import { useUser } from "@/context/UserContext";
import { fetchFriends, fetchFriendRequests, sendFriendRequest } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import type { UserProfile } from "@/lib/types";

// Rarity colors come only from the canonical --rarity-* tokens (globals.css).
const rarityVar = (r: string) => `var(--rarity-${r}, var(--text-muted))`;

type FriendStatus = "loading" | "friends" | "pending" | "eligible";

/**
 * The add-friend action on someone else's profile. `fetchFriends` is
 * self-only (Task 12), so the only way to know whether the viewer is already
 * friends with — or already has a request pending toward — this profile is
 * to fetch the VIEWER's own friends + outgoing requests and check membership.
 * That's worth two extra calls here: rendering "Add friend" to someone
 * already friended (or already pending) is a worse UX than a couple of
 * background fetches, and it's the only way "Request sent" survives a page
 * reload rather than resetting every time the component remounts.
 */
export function AddFriendAction({ profileUserId }: { profileUserId: string }) {
  const { userId: viewerId } = useUser();
  const toast = useToast();
  const [status, setStatus] = React.useState<FriendStatus>("loading");

  const checkStatus = React.useCallback(async () => {
    if (!viewerId || viewerId === profileUserId) return;
    try {
      const [friendsRes, requestsRes] = await Promise.all([
        fetchFriends(viewerId),
        fetchFriendRequests(viewerId),
      ]);
      if (friendsRes.friends.some((f) => f.user_id === profileUserId)) {
        setStatus("friends");
        return;
      }
      if (requestsRes.outgoing.some((r) => r.to_user_id === profileUserId)) {
        setStatus("pending");
        return;
      }
      setStatus("eligible");
    } catch {
      // Couldn't confirm status. Default to eligible rather than hiding the
      // action entirely — a stale "Add friend" that 409s is recoverable via
      // the toast in send(), unlike a button that silently never shows up.
      setStatus("eligible");
    }
  }, [viewerId, profileUserId]);

  React.useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  const send = async () => {
    if (!viewerId || status !== "eligible") return;
    setStatus("pending");
    try {
      await sendFriendRequest(viewerId, profileUserId);
      toast.success("Friend request sent");
    } catch (err) {
      // 409 means already friends, or a request is already pending in a
      // direction we didn't know about — resync to the server's truth
      // instead of guessing, and show the server's own explanation.
      toast.error(humanizeError(err, "Couldn't send that friend request."));
      await checkStatus();
    }
  };

  if (!viewerId || viewerId === profileUserId || status === "loading") return null;

  if (status === "friends") {
    return (
      <span className="chip chip--accent" data-testid="profile-friend-status">
        Friends
      </span>
    );
  }

  return (
    <button
      data-testid="profile-add-friend"
      className="btn btn--sm btn--primary"
      disabled={status === "pending"}
      onClick={send}
    >
      {status === "pending" ? "Request sent" : (
        <>
          <Icon name="plus" size={12} /> Add friend
        </>
      )}
    </button>
  );
}

export function ProfileView({ profile, embedded = false }: { profile: UserProfile; embedded?: boolean }) {
  const eq = profile.equipped_cosmetics || {};
  const roles = [...(profile.roles || [])].sort(
    (a, b) => (b.role.display_priority || 0) - (a.role.display_priority || 0),
  );

  const hero = (
    <section
      style={{
        display: "flex",
        gap: 20,
        alignItems: "flex-start",
        padding: "var(--pad-lg)",
        background: eq.banner?.asset_url
          ? `linear-gradient(135deg, color-mix(in oklab, ${eq.banner.css_value || "var(--accent)"} 35%, var(--bg-panel)) 0%, var(--bg-panel) 100%)`
          : "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-xl)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div style={{ position: "absolute", top: "var(--pad-lg)", right: "var(--pad-lg)" }}>
        <AddFriendAction profileUserId={profile.id} />
      </div>
      <div>
        <AvatarFrame
          name={profile.name || "?"}
          size={88}
          img={profile.avatar_url || undefined}
          frame={eq.avatar_frame ?? null}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <NameColorRenderer
            name={profile.name || "Unnamed"}
            cosmetic={eq.name_color ?? null}
            as="h1"
            style={{ fontFamily: "var(--font-display)", fontSize: 26, fontWeight: 500, margin: 0 }}
          />
          {eq.title && <TitleFlair cosmetic={eq.title} />}
        </div>
        {profile.username && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
            @{profile.username}
          </div>
        )}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
          {roles.map(r => (
            <RoleBadge key={r.role.id} role={r.role} />
          ))}
        </div>
        {profile.bio && (
          <p style={{ margin: "12px 0 0", fontSize: 13, color: "var(--text-dim)", lineHeight: 1.55 }}>
            {profile.bio}
          </p>
        )}
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12, fontSize: 12, color: "var(--text-muted)" }}>
          {profile.school && <Meta icon="tree" text={profile.school} />}
          {profile.year && <Meta icon="star" text={profile.year} />}
          {profile.location && <Meta icon="home" text={profile.location} />}
          {profile.website && (
            <a
              href={profile.website}
              target="_blank"
              rel="noreferrer"
              style={{ color: "var(--accent)", textDecoration: "underline", display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              <Icon name="send" size={11} /> {prettyUrl(profile.website)}
            </a>
          )}
        </div>
      </div>
    </section>
  );

  const studies = [
    profile.majors?.length && { label: "Majors", values: profile.majors },
    profile.minors?.length && { label: "Minors", values: profile.minors },
  ].filter(Boolean) as { label: string; values: string[] }[];

  const stats = profile.stats || ({} as UserProfile["stats"]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: embedded ? 0 : "20px 0", maxWidth: 900, margin: "0 auto" }}>
      {hero}

      {(stats.streak_count !== undefined || stats.session_count !== undefined) && (
        // One-line metric strip instead of a 4-card hero grid. Each
        // number is serif, labels are sans, separators are middots.
        <section
          className="body-serif"
          style={{
            fontSize: 14, color: "var(--text-dim)",
            padding: "10px 0", borderTop: "1px solid var(--border)",
            borderBottom: "1px solid var(--border)",
            display: "flex", flexWrap: "wrap", gap: "4px 14px",
          }}
        >
          <span><span className="h-serif" style={{ color: "var(--text)" }}>{stats.streak_count ?? 0}</span>-day streak</span>
          <span>·</span>
          <span><span className="h-serif" style={{ color: "var(--text)" }}>{stats.session_count ?? 0}</span> sessions</span>
          <span>·</span>
          <span><span className="h-serif" style={{ color: "var(--text)" }}>{stats.documents_count ?? 0}</span> documents</span>
          <span>·</span>
          <span><span className="h-serif" style={{ color: "var(--text)" }}>{stats.achievements_count ?? 0}</span> achievements</span>
        </section>
      )}

      {studies.length > 0 && (
        <section className="card" style={{ padding: "var(--pad-lg)" }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Fields of study</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {studies.map(s => (
              <div key={s.label} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)", minWidth: 60 }}>{s.label}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {s.values.map(v => (
                    <span key={v} className="chip">{v}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {(profile.featured_achievements?.length ?? 0) > 0 && (
        <section className="card" style={{ padding: "var(--pad-lg)" }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Featured achievements</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
            {profile.featured_achievements!.map(ua => {
              const c = rarityVar(ua.achievement.rarity);
              return (
                <div
                  key={ua.achievement.id}
                  style={{
                    padding: 12,
                    textAlign: "center",
                    border: `1px solid color-mix(in srgb, ${c} 20%, transparent)`,
                    background: `color-mix(in srgb, ${c} 6%, transparent)`,
                    borderRadius: "var(--r-md)",
                    borderTop: `3px solid ${c}`,
                  }}
                >
                  <div style={{ fontSize: 26, marginBottom: 4 }}>{ua.achievement.icon || "★"}</div>
                  <div style={{ fontSize: 11, fontWeight: 600 }}>{ua.achievement.name}</div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                    {ua.achievement.rarity}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {profile.stats === undefined || Object.keys(profile.stats || {}).length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", padding: 24 }}>
          This profile is private.
        </div>
      ) : null}
    </div>
  );
}

function Meta({ icon, text }: { icon: string; text: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <Icon name={icon} size={11} />
      {text}
    </span>
  );
}

function prettyUrl(url: string) {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "") + (u.pathname !== "/" ? u.pathname : "");
  } catch {
    return url;
  }
}
