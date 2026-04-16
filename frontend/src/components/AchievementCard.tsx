'use client';

import type { Achievement, RarityTier } from '@/lib/types';

interface Props {
  achievement: Achievement;
  earned: boolean;
  earnedAt?: string;
  progress?: number;
  isSecret?: boolean;
  compact?: boolean;
  onPress?: () => void;
}

const RARITY_BORDER: Record<RarityTier, string> = {
  common: 'var(--rarity-common)',
  uncommon: 'var(--rarity-uncommon)',
  rare: 'var(--rarity-rare)',
  epic: 'var(--rarity-epic)',
  legendary: 'var(--rarity-legendary)',
};

const RARITY_BG: Record<RarityTier, string> = {
  common: 'var(--rarity-common-bg)',
  uncommon: 'var(--rarity-uncommon-bg)',
  rare: 'var(--rarity-rare-bg)',
  epic: 'var(--rarity-epic-bg)',
  legendary: 'var(--rarity-legendary-bg)',
};

export default function AchievementCard({ achievement, earned, earnedAt, progress, isSecret, compact, onPress }: Props) {
  const isLocked = !earned;
  const showSecret = isSecret && isLocked;

  return (
    <div
      onClick={onPress}
      style={{
        background: 'var(--bg-panel)',
        border: `1px solid ${earned ? RARITY_BORDER[achievement.rarity] : 'var(--border)'}`,
        borderRadius: 'var(--radius-md)',
        padding: compact ? '10px' : '14px',
        cursor: onPress ? 'pointer' : 'default',
        opacity: isLocked ? 0.65 : 1,
        transition: 'border-color var(--dur-fast), box-shadow var(--dur-fast)',
        boxShadow: earned ? `0 0 0 1px ${RARITY_BG[achievement.rarity]}` : 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: compact ? '6px' : '8px',
        minWidth: compact ? '100px' : undefined,
      }}
    >
      {/* Icon */}
      <div style={{
        width: compact ? '28px' : '36px',
        height: compact ? '28px' : '36px',
        borderRadius: 'var(--radius-sm)',
        background: earned ? RARITY_BG[achievement.rarity] : 'var(--bg-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: isLocked ? 0.3 : 1,
      }}>
        {showSecret ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="var(--text-dim)" strokeWidth="1.5">
            <circle cx="8" cy="8" r="5" />
            <text x="8" y="11" textAnchor="middle" fontSize="10" fill="var(--text-dim)" stroke="none">?</text>
          </svg>
        ) : achievement.icon ? (
          <img src={achievement.icon} alt="" style={{ width: compact ? '18px' : '22px', height: compact ? '18px' : '22px' }} />
        ) : (
          <svg width={compact ? 16 : 20} height={compact ? 16 : 20} viewBox="0 0 16 16" fill="none" stroke={earned ? RARITY_BORDER[achievement.rarity] : 'var(--text-dim)'} strokeWidth="1.5">
            <circle cx="8" cy="6" r="4" />
            <path d="M4 14l4-4 4 4" />
          </svg>
        )}
      </div>

      {/* Name */}
      <div style={{
        fontSize: compact ? '11px' : '13px',
        fontWeight: 600,
        color: 'var(--text)',
      }}>
        {showSecret ? 'Secret Achievement' : achievement.name}
      </div>

      {/* Description (not in compact mode) */}
      {!compact && (
        <div style={{
          fontSize: '12px',
          color: 'var(--text-dim)',
          lineHeight: 1.4,
        }}>
          {showSecret ? 'Keep exploring to discover this achievement' : achievement.description}
        </div>
      )}

      {/* Rarity label */}
      <div style={{
        fontSize: '10px',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
        color: RARITY_BORDER[achievement.rarity],
      }}>
        {achievement.rarity}
      </div>

      {/* Progress bar (locked, non-compact only) */}
      {isLocked && !compact && progress !== undefined && progress > 0 && (
        <div style={{
          width: '100%',
          height: '3px',
          borderRadius: '2px',
          background: 'var(--bg-subtle)',
          overflow: 'hidden',
        }}>
          <div style={{
            width: `${Math.min(100, progress * 100)}%`,
            height: '100%',
            background: RARITY_BORDER[achievement.rarity],
            borderRadius: '2px',
            transition: 'width var(--dur-base)',
          }} />
        </div>
      )}

      {/* Earned date */}
      {earned && earnedAt && !compact && (
        <div style={{ fontSize: '10px', color: 'var(--text-placeholder)' }}>
          Earned {new Date(earnedAt).toLocaleDateString()}
        </div>
      )}
    </div>
  );
}
