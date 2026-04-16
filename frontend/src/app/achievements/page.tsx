'use client';

import { useEffect, useState } from 'react';
import { useUser } from '@/context/UserContext';
import { fetchAchievements } from '@/lib/api';
import type { Achievement, UserAchievement, AchievementCategory } from '@/lib/types';
import AchievementCard from '@/components/AchievementCard';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const CATEGORIES: { key: AchievementCategory | 'all'; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'activity', label: 'Activity' },
  { key: 'social', label: 'Social' },
  { key: 'milestone', label: 'Milestone' },
  { key: 'special', label: 'Special' },
];

export default function AchievementsPage() {
  const { userId } = useUser();
  const [earned, setEarned] = useState<UserAchievement[]>([]);
  const [available, setAvailable] = useState<Achievement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<AchievementCategory | 'all'>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return;
    setLoading(true);
    fetchAchievements(userId)
      .then(data => {
        setEarned(data.earned || []);
        setAvailable(data.available || []);
        setLoading(false);
      })
      .catch(e => {
        setError(e.message);
        setLoading(false);
      });
  }, [userId]);

  const filterFn = (category: string) =>
    filter === 'all' || category === filter;

  const filteredEarned = earned.filter(ua => filterFn(ua.achievement.category));
  const filteredAvailable = available.filter(a => filterFn(a.category));

  if (loading) {
    return (
      <div style={{ maxWidth: '720px', margin: '40px auto', padding: '0 20px', fontFamily: UI_FONT }}>
        <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>Loading achievements...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: '720px', margin: '40px auto', padding: '0 20px', fontFamily: UI_FONT }}>
        <div style={{ color: 'var(--brand-struggle)', fontSize: '13px' }}>{error}</div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: '720px', margin: '0 auto', padding: '24px 20px', fontFamily: UI_FONT }}>
      <h1 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '4px', color: 'var(--text)' }}>Achievements</h1>
      <p style={{ fontSize: '13px', color: 'var(--text-dim)', marginBottom: '20px' }}>
        Track your progress and unlock achievements as you learn.
      </p>

      {/* Category filters */}
      <div style={{ display: 'flex', gap: '6px', marginBottom: '20px', flexWrap: 'wrap' }}>
        {CATEGORIES.map(cat => (
          <button
            key={cat.key}
            onClick={() => setFilter(cat.key)}
            className={filter === cat.key ? 'pill pill-active' : 'pill pill-inactive'}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Earned achievements */}
      {filteredEarned.length > 0 && (
        <div style={{ marginBottom: '24px' }}>
          <div className="label" style={{ marginBottom: '10px' }}>Earned ({filteredEarned.length})</div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            gap: '10px',
          }}>
            {filteredEarned.map(ua => (
              <div key={ua.achievement.id}>
                <AchievementCard
                  achievement={ua.achievement}
                  earned={true}
                  earnedAt={ua.earned_at}
                  onPress={() => setExpandedId(expandedId === ua.achievement.id ? null : ua.achievement.id)}
                />
                {expandedId === ua.achievement.id && (
                  <div style={{
                    marginTop: '4px',
                    padding: '10px',
                    background: 'var(--bg-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    color: 'var(--text-secondary)',
                    animation: 'fade-in var(--dur-base) var(--ease-out) both',
                  }}>
                    <div style={{ marginBottom: '4px' }}>{ua.achievement.description}</div>
                    <div style={{ color: 'var(--text-dim)' }}>
                      Rarity: {ua.achievement.rarity} | Earned: {new Date(ua.earned_at).toLocaleDateString()}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Locked achievements */}
      {filteredAvailable.length > 0 && (
        <div>
          <div className="label" style={{ marginBottom: '10px' }}>Locked ({filteredAvailable.length})</div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            gap: '10px',
          }}>
            {filteredAvailable.map(ach => (
              <AchievementCard
                key={ach.id}
                achievement={ach}
                earned={false}
                isSecret={ach.is_secret}
              />
            ))}
          </div>
        </div>
      )}

      {filteredEarned.length === 0 && filteredAvailable.length === 0 && (
        <div style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '40px 0', fontSize: '13px' }}>
          No achievements found in this category.
        </div>
      )}
    </div>
  );
}
