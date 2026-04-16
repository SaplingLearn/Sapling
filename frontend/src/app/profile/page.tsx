'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { fetchPublicProfile, fetchAchievements } from '@/lib/api';
import type { UserProfile, UserAchievement, Achievement } from '@/lib/types';
import AvatarFrame from '@/components/AvatarFrame';
import NameColorRenderer from '@/components/NameColorRenderer';
import TitleFlair from '@/components/TitleFlair';
import RoleBadge from '@/components/RoleBadge';
import AchievementShowcase from '@/components/AchievementShowcase';
import Link from 'next/link';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

export default function ProfilePage() {
  return (
    <Suspense fallback={
      <div style={{ maxWidth: '720px', margin: '40px auto', padding: '0 20px', fontFamily: UI_FONT }}>
        <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>Loading profile...</div>
      </div>
    }>
      <ProfileContent />
    </Suspense>
  );
}

function ProfileContent() {
  const searchParams = useSearchParams();
  const profileUserId = searchParams.get('id') || '';
  const { userId: currentUserId } = useUser();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [achievements, setAchievements] = useState<{ earned: UserAchievement[]; available: Achievement[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const isOwnProfile = currentUserId === profileUserId;

  useEffect(() => {
    if (!profileUserId) return;
    setLoading(true);
    setError('');

    const loadProfile = fetchPublicProfile(profileUserId)
      .then(data => setProfile(data))
      .catch(e => setError(e.message));

    const loadAchievements = fetchAchievements(profileUserId)
      .then(data => setAchievements(data))
      .catch(() => {});

    Promise.all([loadProfile, loadAchievements]).finally(() => setLoading(false));
  }, [profileUserId]);

  if (loading) {
    return (
      <div style={{ maxWidth: '720px', margin: '40px auto', padding: '0 20px', fontFamily: UI_FONT }}>
        <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>Loading profile...</div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div style={{ maxWidth: '720px', margin: '40px auto', padding: '0 20px', fontFamily: UI_FONT }}>
        <div style={{ color: 'var(--brand-struggle)', fontSize: '13px' }}>{error || 'Profile not found'}</div>
      </div>
    );
  }

  const yearLabel = profile.year
    ? profile.year.charAt(0).toUpperCase() + profile.year.slice(1)
    : null;

  return (
    <div style={{ maxWidth: '720px', margin: '0 auto', padding: '32px 20px', fontFamily: UI_FONT }}>
      {/* Header: Avatar + Name + Roles */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '20px',
        marginBottom: '24px',
      }}>
        <AvatarFrame
          userId={profile.id}
          name={profile.name}
          size={80}
          avatarUrl={profile.avatar_url || undefined}
          frameUrl={profile.equipped_cosmetics?.avatar_frame?.asset_url}
        />
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '22px', fontWeight: 700 }}>
              <NameColorRenderer
                name={profile.name}
                cssValue={profile.equipped_cosmetics?.name_color?.css_value}
              />
            </span>
            {profile.equipped_cosmetics?.title && (
              <TitleFlair
                title={profile.equipped_cosmetics.title.name}
                rarity={profile.equipped_cosmetics.title.rarity}
              />
            )}
          </div>
          {profile.username && (
            <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '2px' }}>@{profile.username}</div>
          )}
          {profile.roles.length > 0 && (
            <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '6px' }}>
              {profile.roles.map(ur => (
                <RoleBadge key={ur.role.id} role={ur.role} size="sm" />
              ))}
            </div>
          )}
        </div>
        {isOwnProfile && (
          <Link href="/settings">
            <button className="btn-ghost" style={{ whiteSpace: 'nowrap', fontSize: '13px' }}>Edit profile</button>
          </Link>
        )}
      </div>

      {/* Bio */}
      {profile.bio && (
        <div style={{
          fontSize: '14px',
          color: 'var(--text)',
          lineHeight: 1.6,
          marginBottom: '20px',
        }}>
          {profile.bio}
        </div>
      )}

      {/* Info Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: '12px 24px',
        marginBottom: '24px',
        padding: '16px 20px',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
      }}>
        {profile.school && (
          <InfoRow label="University" value={profile.school} />
        )}
        {yearLabel && (
          <InfoRow label="Year" value={yearLabel} />
        )}
        {profile.majors && profile.majors.length > 0 && (
          <InfoRow label={profile.majors.length > 1 ? 'Majors' : 'Major'} value={profile.majors.join(', ')} />
        )}
        {profile.minors && profile.minors.length > 0 && (
          <InfoRow label={profile.minors.length > 1 ? 'Minors' : 'Minor'} value={profile.minors.join(', ')} />
        )}
        {profile.created_at && (
          <InfoRow
            label="Joined"
            value={new Date(profile.created_at).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
          />
        )}
        {profile.location && (
          <InfoRow label="Location" value={profile.location} />
        )}
        {profile.website && (
          <div>
            <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '2px' }}>Website</div>
            <a
              href={profile.website.startsWith('http') ? profile.website : `https://${profile.website}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: '13px', color: 'var(--accent)', textDecoration: 'none' }}
            >
              {profile.website}
            </a>
          </div>
        )}
      </div>

      {/* Stats */}
      {profile.stats && Object.keys(profile.stats).length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '10px',
          marginBottom: '24px',
        }}>
          {[
            { label: 'Streak', value: profile.stats.streak_count ?? 0 },
            { label: 'Sessions', value: profile.stats.session_count ?? 0 },
            { label: 'Documents', value: profile.stats.documents_count ?? 0 },
            { label: 'Achievements', value: profile.stats.achievements_count ?? 0 },
          ].map(stat => (
            <div key={stat.label} style={{
              background: 'var(--bg-panel)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-md)',
              padding: '14px 12px',
              textAlign: 'center',
            }}>
              <div style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text)' }}>{stat.value}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{stat.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Featured Achievements */}
      {profile.featured_achievements && profile.featured_achievements.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <AchievementShowcase
            achievements={profile.featured_achievements}
            isOwnProfile={isOwnProfile}
          />
        </div>
      )}

      {/* All Achievements */}
      {achievements && achievements.earned.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text)', marginBottom: '12px' }}>
            Achievements ({achievements.earned.length})
          </h3>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: '10px',
          }}>
            {achievements.earned.map(ua => (
              <div key={ua.achievement.id} style={{
                padding: '12px 14px',
                background: 'var(--bg-panel)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
              }}>
                <span style={{ fontSize: '20px' }}>{ua.achievement.icon || '🏆'}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {ua.achievement.name}
                  </div>
                  {ua.achievement.description && (
                    <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '1px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ua.achievement.description}
                    </div>
                  )}
                  <div style={{ fontSize: '10px', color: 'var(--text-dim)', marginTop: '2px' }}>
                    {new Date(ua.earned_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                  </div>
                </div>
                <RarityDot rarity={ua.achievement.rarity} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '2px' }}>{label}</div>
      <div style={{ fontSize: '13px', color: 'var(--text)', fontWeight: 500 }}>{value}</div>
    </div>
  );
}

const RARITY_COLORS: Record<string, string> = {
  common: '#9ca3af',
  uncommon: '#22c55e',
  rare: '#3b82f6',
  epic: '#a855f7',
  legendary: '#f59e0b',
};

function RarityDot({ rarity }: { rarity: string }) {
  return (
    <div
      title={rarity.charAt(0).toUpperCase() + rarity.slice(1)}
      style={{
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: RARITY_COLORS[rarity] || RARITY_COLORS.common,
        flexShrink: 0,
      }}
    />
  );
}
