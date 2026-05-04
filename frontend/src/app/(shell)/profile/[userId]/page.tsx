"use client";
import React from "react";
import { useParams } from "next/navigation";
import { TopBar } from "@/components/TopBar";
import { ProfileView } from "@/components/ProfileView";
import { ProfileSkeleton } from "@/components/Skeleton";
import { fetchPublicProfile } from "@/lib/api";
import type { UserProfile } from "@/lib/types";

export default function PublicProfilePage() {
  const params = useParams<{ userId: string }>();
  const userId = params?.userId;
  const [profile, setProfile] = React.useState<UserProfile | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!userId) return;
    setLoading(true);
    fetchPublicProfile(userId)
      .then(p => { setProfile(p); setError(null); })
      .catch(err => setError(String(err)))
      .finally(() => setLoading(false));
  }, [userId]);

  return (
    <div>
      <TopBar
        title={profile?.name || (loading ? "Loading…" : "Profile")}
        subtitle={profile?.username ? `@${profile.username}` : undefined}
      />
      <div style={{ padding: "20px 32px" }}>
        {loading && <ProfileSkeleton />}
        {error && !loading && (
          <div className="card" style={{ padding: 28, textAlign: "center", color: "var(--err)" }}>
            Couldn&apos;t load this profile. {error}
          </div>
        )}
        {!loading && !error && profile && <ProfileView profile={profile} />}
      </div>
    </div>
  );
}
