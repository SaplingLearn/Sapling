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
import type { UserAchievement, UserProfile } from "@/lib/types";
import {
  hasStatsStrip, heroBackground, isPrivateProfile, prettyUrl, safeWebsiteHref, sortRolesByPriority, studiesOf,
  type StudyGroup,
} from "./profileViewHelpers";
import { sentenceCase } from "@/lib/sentenceCase";
import { cn } from "@/lib/cn";

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
      <span className="inline-flex gap-1.5">
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
  const studies = studiesOf(profile);

  const stats = profile.stats || ({} as UserProfile["stats"]);

  return (
    <div className={cn("flex flex-col gap-4 max-w-225 my-0 mx-auto", embedded ? "p-0" : "py-5 px-0")}>
      <ProfileHero profile={profile} />

      {hasStatsStrip(stats) && <StatsStrip stats={stats} />}

      {studies.length > 0 && <FieldsOfStudy studies={studies} />}

      {(profile.featured_achievements?.length ?? 0) > 0 && (
        <FeaturedAchievements achievements={profile.featured_achievements!} />
      )}

      {isPrivateProfile(profile.stats) ? (
        <div className="text-sm text-text-muted text-center p-6">
          This profile is private.
        </div>
      ) : null}
    </div>
  );
}

function ProfileHero({ profile }: { profile: UserProfile }) {
  const eq = profile.equipped_cosmetics || {};
  const roles = sortRolesByPriority(profile.roles);

  return (
    <section
      className="flex gap-5 items-start p-(--pad-lg) border border-border rounded-xl relative overflow-hidden" style={{ background: heroBackground(eq.banner) }}
    >
      <div className="absolute top-(--pad-lg) right-(--pad-lg)">
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
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2.5 flex-wrap">
          <NameColorRenderer
            name={profile.name || "Unnamed"}
            cosmetic={eq.name_color ?? null}
            as="h1"
            style={{ fontFamily: "var(--font-display)", fontSize: 26, fontWeight: 500, margin: 0 }}
          />
          {eq.title && <TitleFlair cosmetic={eq.title} />}
        </div>
        {profile.username && (
          <div className="text-sm text-text-muted mt-1">
            @{profile.username}
          </div>
        )}
        <div className="flex gap-1.5 flex-wrap mt-2.5">
          {roles.map(r => (
            <RoleBadge key={r.role.id} role={r.role} />
          ))}
        </div>
        {profile.bio && (
          <p className="mt-3 mx-0 mb-0 text-md text-text-dim leading-[1.55]">
            {profile.bio}
          </p>
        )}
        <ProfileMetaRow profile={profile} />
      </div>
    </section>
  );
}

function ProfileMetaRow({ profile }: { profile: UserProfile }) {
  // Only an http(s) URL becomes a link; any other value is not shown.
  const websiteHref = safeWebsiteHref(profile.website);
  return (
    <div className="flex gap-3.5 flex-wrap mt-3 text-sm text-text-muted">
      {profile.school && <Meta icon="tree" text={profile.school} />}
      {profile.year && <Meta icon="star" text={profile.year} />}
      {profile.location && <Meta icon="home" text={profile.location} />}
      {websiteHref && (
        <a
          href={websiteHref}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="text-accent underline inline-flex items-center gap-1"
        >
          <Icon name="send" size={11} /> {prettyUrl(websiteHref)}
        </a>
      )}
    </div>
  );
}

// One-line metric strip instead of a 4-card hero grid. Each
// number is serif, labels are sans, separators are middots.
function StatsStrip({ stats }: { stats: UserProfile["stats"] }) {
  return (
    <section
      className="body-serif text-base text-text-dim py-2.5 px-0 border-t border-t-border border-b border-b-border flex flex-wrap gap-y-1 gap-x-3.5"
    >
      <span><span className="h-serif text-text">{stats.streak_count ?? 0}</span>-day streak</span>
      <span>·</span>
      <span><span className="h-serif text-text">{stats.session_count ?? 0}</span> sessions</span>
      <span>·</span>
      <span><span className="h-serif text-text">{stats.documents_count ?? 0}</span> documents</span>
      <span>·</span>
      <span><span className="h-serif text-text">{stats.achievements_count ?? 0}</span> achievements</span>
    </section>
  );
}

function FieldsOfStudy({ studies }: { studies: StudyGroup[] }) {
  return (
    <section className="card p-(--pad-lg)">
      <div className="label-micro mb-2.5">Fields of study</div>
      <div className="flex flex-col gap-2.5">
        {studies.map(s => (
          <div key={s.label} className="flex gap-2.5 items-baseline">
            <div className="text-sm text-text-muted min-w-15">{s.label}</div>
            <div className="flex flex-wrap gap-1.5">
              {s.values.map(v => (
                <span key={v} className="chip">{v}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function FeaturedAchievements({ achievements }: { achievements: UserAchievement[] }) {
  return (
    <section className="card p-(--pad-lg)">
      <div className="label-micro mb-2.5">Featured achievements</div>
      <div className="grid grid-cols-[repeat(auto-fill,_minmax(140px,_1fr))] gap-2.5">
        {achievements.map(ua => (
          <FeaturedAchievementCard key={ua.achievement.id} achievement={ua.achievement} />
        ))}
      </div>
    </section>
  );
}

function FeaturedAchievementCard({ achievement }: { achievement: UserAchievement["achievement"] }) {
  const c = rarityVar(achievement.rarity);
  return (
    <div
      className="p-3 text-center rounded-md" style={{ border: `1px solid color-mix(in srgb, ${c} 20%, transparent)`, background: `color-mix(in srgb, ${c} 6%, transparent)`, borderTop: `3px solid ${c}` }}
    >
      <div className="text-3xl mb-1">{achievement.icon || "★"}</div>
      <div className="text-xs font-semibold">{achievement.name}</div>
      <div className="text-sm text-text-muted mt-0.5">
        {sentenceCase(achievement.rarity)}
      </div>
    </div>
  );
}

function Meta({ icon, text }: { icon: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-[5px]">
      <Icon name={icon} size={11} />
      {text}
    </span>
  );
}
