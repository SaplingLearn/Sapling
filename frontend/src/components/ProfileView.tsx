"use client";
import React from "react";
import { AvatarFrame } from "./AvatarFrame";
import { NameColorRenderer } from "./NameColorRenderer";
import { TitleFlair } from "./TitleFlair";
import { RoleBadge } from "./RoleBadge";
import { Icon } from "./Icon";
import { useToast } from "./ToastProvider";
import { useUser } from "@/context/UserContext";
import {
  fetchFriends, fetchFriendRequests, sendFriendRequest, acceptFriendRequest, cancelFriendRequest,
} from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import type { UserProfile } from "@/lib/types";

// Rarity colors come only from the canonical --rarity-* tokens (globals.css).
const rarityVar = (r: string) => `var(--rarity-${r}, var(--text-muted))`;

// "pending" = the viewer sent a request; "incoming" = this profile sent the
// viewer one (#764: that used to render a plain "Add friend" that 409d).
type FriendStatus = "loading" | "friends" | "pending" | "incoming" | "eligible";

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
  // The request behind "pending"/"incoming" — what Cancel/Accept act on.
  const [requestId, setRequestId] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  // #764: a different profile starts from "loading", never from the last
  // profile's status (React's adjust-state-during-render pattern).
  const [statusFor, setStatusFor] = React.useState(profileUserId);
  if (statusFor !== profileUserId) {
    setStatusFor(profileUserId);
    setStatus("loading");
    setRequestId(null);
  }
  // A response for a profile we have since navigated away from must not
  // land on the new one (ProfileView also keys this component by profile id).
  const latestProfile = React.useRef(profileUserId);
  React.useEffect(() => { latestProfile.current = profileUserId; }, [profileUserId]);

  const checkStatus = React.useCallback(async () => {
    if (!viewerId || viewerId === profileUserId) return;
    const apply = (next: FriendStatus, id: string | null = null) => {
      if (latestProfile.current !== profileUserId) return;
      setStatus(next);
      setRequestId(id);
    };
    try {
      const [friendsRes, requestsRes] = await Promise.all([
        fetchFriends(viewerId),
        fetchFriendRequests(viewerId),
      ]);
      if (friendsRes.friends.some((f) => f.user_id === profileUserId)) {
        apply("friends");
        return;
      }
      const incoming = requestsRes.incoming.find((r) => r.from_user_id === profileUserId);
      if (incoming) {
        apply("incoming", incoming.id);
        return;
      }
      const outgoing = requestsRes.outgoing.find((r) => r.to_user_id === profileUserId);
      if (outgoing) {
        apply("pending", outgoing.id);
        return;
      }
      apply("eligible");
    } catch {
      // Couldn't confirm status. Default to eligible rather than hiding the
      // action entirely — a stale "Add friend" that 409s is recoverable via
      // the toast in send(), unlike a button that silently never shows up.
      apply("eligible");
    }
  }, [viewerId, profileUserId]);

  React.useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  const send = async () => {
    if (!viewerId || status !== "eligible") return;
    setStatus("pending");
    try {
      const res = await sendFriendRequest(viewerId, profileUserId);
      setRequestId(res?.request?.id ?? null);
      toast.success("Friend request sent");
    } catch (err) {
      // 409 means already friends, or a request is already pending in a
      // direction we didn't know about — resync to the server's truth
      // instead of guessing, and show the server's own explanation.
      toast.error(humanizeError(err, "Couldn't send that friend request."));
      await checkStatus();
    }
  };

  // Accept / Cancel: on success go straight to the new state; on a lost race
  // (409/404) show the server's reason and resync.
  const respond = async (action: "accept" | "cancel") => {
    if (!viewerId || !requestId || busy) return;
    setBusy(true);
    try {
      if (action === "accept") {
        await acceptFriendRequest(requestId, viewerId);
        toast.success("Friend request accepted");
        setStatus("friends");
      } else {
        await cancelFriendRequest(requestId, viewerId);
        toast.success("Friend request cancelled");
        setStatus("eligible");
      }
      setRequestId(null);
    } catch (err) {
      toast.error(humanizeError(
        err, action === "accept" ? "Couldn't accept that request." : "Couldn't cancel that request.",
      ));
      await checkStatus();
    } finally {
      setBusy(false);
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

  if (status === "incoming") {
    return (
      <button
        data-testid="profile-accept-friend"
        className="btn btn--sm btn--primary"
        disabled={busy}
        onClick={() => respond("accept")}
      >
        <Icon name="check" size={12} /> Accept friend request
      </button>
    );
  }

  if (status === "pending" && requestId) {
    return (
      <span style={{ display: "inline-flex", gap: 6 }}>
        <button data-testid="profile-add-friend" className="btn btn--sm btn--primary" disabled>
          Request sent
        </button>
        <button
          data-testid="profile-cancel-friend-request"
          className="btn btn--sm btn--ghost"
          disabled={busy}
          onClick={() => respond("cancel")}
        >
          Cancel
        </button>
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
        <AddFriendAction key={profile.id} profileUserId={profile.id} />
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
