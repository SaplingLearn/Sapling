'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { fetchPublicProfile } from '@/lib/api';
import type { UserProfile } from '@/lib/types';
import ProfileBanner from '@/components/ProfileBanner';
import AvatarFrame from '@/components/AvatarFrame';
import NameColorRenderer from '@/components/NameColorRenderer';
import TitleFlair from '@/components/TitleFlair';
import RoleBadge from '@/components/RoleBadge';
import AchievementShowcase from '@/components/AchievementShowcase';
import Link from 'next/link';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

export default function ProfilePage() {
  const searchParams = useSearchParams();
  const profileUserId = searchParams.get('id') || '';
  const { userId: currentUserId } = useUser();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const isOwnProfile = currentUserId === profileUserId;

  useEffect(() => {
    if (!profileUserId) return;
    setLoading(true);
    fetchPublicProfile(profileUserId)
      .then(data => {
        setProfile(data);
        setLoading(false);
      })
      .catch(e => {
        setError(e.message);
        setLoading(false);
      });
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

  return (
    <div style={{ maxWidth: '720px', margin: '0 auto', padding: '24px 20px', fontFamily: UI_FONT }}>
      {/* 1. Banner */}
      <ProfileBanner bannerUrl={profile.equipped_cosmetics?.banner?.asset_url} />

      {/* 2. Avatar row */}
      <div style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: '16px',
        marginTop: '-32px',
        paddingLeft: '16px',
        position: 'relative',
        zIndex: 1,
      }}>
        <AvatarFrame
          userId={profile.id}
          name={profile.name}
          size={72}
          avatarUrl={profile.avatar_url || undefined}
          frameUrl={profile.equipped_cosmetics?.avatar_frame?.asset_url}
        />
        <div style={{ flex: 1, paddingBottom: '4px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '20px', fontWeight: 700 }}>
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
          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}>
            {profile.roles.map(ur => (
              <RoleBadge key={ur.role.id} role={ur.role} size="sm" />
            ))}
          </div>
        </div>
      </div>

      {/* 3. Secondary info */}
      <div style={{
        marginTop: '16px',
        padding: '16px',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
      }}>
        {profile.username && (
          <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginBottom: '4px' }}>@{profile.username}</div>
        )}
        {profile.bio && (
          <div style={{ fontSize: '14px', color: 'var(--text)', marginBottom: '8px', lineHeight: 1.5 }}>{profile.bio}</div>
        )}
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '12px', color: 'var(--text-dim)' }}>
          {profile.location && (
            <span>{profile.location}</span>
          )}
          {profile.website && (
            <a
              href={profile.website.startsWith('http') ? profile.website : `https://${profile.website}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--accent)', textDecoration: 'none' }}
            >
              {profile.website}
            </a>
          )}
          {profile.created_at && (
            <span>Joined {new Date(profile.created_at).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}</span>
          )}
        </div>
      </div>

      {/* 4. Achievement Showcase */}
      {profile.featured_achievements && profile.featured_achievements.length > 0 && (
        <div style={{ marginTop: '16px' }}>
          <AchievementShowcase
            achievements={profile.featured_achievements}
            isOwnProfile={isOwnProfile}
          />
        </div>
      )}

      {/* 5. Stats */}
      {profile.stats && Object.keys(profile.stats).length > 0 && (
        <div style={{
          marginTop: '16px',
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '10px',
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
              padding: '12px',
              textAlign: 'center',
            }}>
              <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text)' }}>{stat.value}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{stat.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* 6. Edit profile button */}
      {isOwnProfile && (
        <div style={{ marginTop: '16px' }}>
          <Link href="/settings">
            <button className="btn-ghost" style={{ width: '100%' }}>Edit profile</button>
          </Link>
        </div>
      )}
    </div>
  );
}
