/**
 * Tests for components/AchievementCard.tsx
 *
 * Covers: earned vs locked rendering, secret achievement masking,
 * compact mode, progress bar, click handler.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import AchievementCard from '@/components/AchievementCard';
import type { Achievement } from '@/lib/types';

const baseAchievement: Achievement = {
  id: 'a1',
  name: 'First Login',
  slug: 'first_login',
  description: 'Log in for the first time',
  icon: null,
  category: 'activity',
  rarity: 'common',
  is_secret: false,
};

afterEach(() => jest.clearAllMocks());

describe('AchievementCard', () => {
  it('renders earned achievement name', () => {
    render(<AchievementCard achievement={baseAchievement} earned={true} />);
    expect(screen.getByText('First Login')).toBeInTheDocument();
  });

  it('renders description when not compact', () => {
    render(<AchievementCard achievement={baseAchievement} earned={true} />);
    expect(screen.getByText('Log in for the first time')).toBeInTheDocument();
  });

  it('hides description in compact mode', () => {
    render(<AchievementCard achievement={baseAchievement} earned={true} compact />);
    expect(screen.queryByText('Log in for the first time')).not.toBeInTheDocument();
  });

  it('shows rarity label', () => {
    render(<AchievementCard achievement={baseAchievement} earned={true} />);
    expect(screen.getByText('common')).toBeInTheDocument();
  });

  it('masks secret unearned achievement', () => {
    render(<AchievementCard achievement={baseAchievement} earned={false} isSecret />);
    expect(screen.getByText('Secret Achievement')).toBeInTheDocument();
    expect(screen.queryByText('First Login')).not.toBeInTheDocument();
  });

  it('shows secret description placeholder when locked', () => {
    render(<AchievementCard achievement={baseAchievement} earned={false} isSecret />);
    expect(screen.getByText(/keep exploring/i)).toBeInTheDocument();
  });

  it('does not mask secret achievement when earned', () => {
    render(<AchievementCard achievement={baseAchievement} earned={true} isSecret />);
    expect(screen.getByText('First Login')).toBeInTheDocument();
    expect(screen.queryByText('Secret Achievement')).not.toBeInTheDocument();
  });

  it('renders earned date when provided and not compact', () => {
    render(<AchievementCard achievement={baseAchievement} earned={true} earnedAt="2025-06-15T00:00:00Z" />);
    expect(screen.getByText(/earned/i)).toBeInTheDocument();
  });

  it('fires onPress callback', () => {
    const onPress = jest.fn();
    render(<AchievementCard achievement={baseAchievement} earned={true} onPress={onPress} />);
    fireEvent.click(screen.getByText('First Login').closest('div')!);
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('renders different rarity tiers', () => {
    const legendary: Achievement = { ...baseAchievement, rarity: 'legendary' };
    render(<AchievementCard achievement={legendary} earned={true} />);
    expect(screen.getByText('legendary')).toBeInTheDocument();
  });
});
