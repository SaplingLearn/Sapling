'use client';

import type { UserAchievement } from '@/lib/types';
import AchievementCard from '@/components/AchievementCard';

interface Props {
  achievements: UserAchievement[];
  isOwnProfile: boolean;
  onEditShowcase?: () => void;
}

export default function AchievementShowcase({ achievements, isOwnProfile, onEditShowcase }: Props) {
  const slots = 5;
  const items = achievements.slice(0, slots);

  return (
    <div>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '10px',
      }}>
        <span style={{
          fontSize: '11px',
          fontWeight: 500,
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
        }}>
          Featured Achievements
        </span>
        {isOwnProfile && onEditShowcase && (
          <button
            onClick={onEditShowcase}
            className="btn-ghost"
            style={{ padding: '3px 8px', fontSize: '11px' }}
          >
            Edit showcase
          </button>
        )}
      </div>

      <div style={{
        display: 'flex',
        gap: '8px',
        flexWrap: 'wrap',
      }}>
        {items.map(ua => (
          <AchievementCard
            key={ua.achievement.id}
            achievement={ua.achievement}
            earned={true}
            earnedAt={ua.earned_at}
            compact
          />
        ))}
        {/* Empty placeholder slots */}
        {Array.from({ length: slots - items.length }).map((_, i) => (
          <div
            key={`empty-${i}`}
            style={{
              minWidth: '100px',
              height: '80px',
              border: '1px dashed var(--border)',
              borderRadius: 'var(--radius-md)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-placeholder)',
              fontSize: '11px',
            }}
          />
        ))}
      </div>
    </div>
  );
}
