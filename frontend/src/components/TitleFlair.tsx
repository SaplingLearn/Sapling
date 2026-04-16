'use client';

import type { RarityTier } from '@/lib/types';

interface Props {
  title: string;
  rarity: RarityTier;
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

export default function TitleFlair({ title, rarity }: Props) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '1px 6px',
      borderRadius: 'var(--radius-full)',
      fontSize: '10px',
      fontWeight: 600,
      letterSpacing: '0.02em',
      color: RARITY_BORDER[rarity],
      background: RARITY_BG[rarity],
      border: `1px solid ${RARITY_BORDER[rarity]}`,
    }}>
      {title}
    </span>
  );
}
