/**
 * Tests for app/profile/page.tsx
 *
 * Covers: loading state, error state, profile data rendering,
 * own-profile edit button, role badges.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useSearchParams: () => ({ get: (key: string) => key === 'id' ? 'user_1' : null }),
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/profile',
}));

// Mock UserContext
jest.mock('@/context/UserContext', () => ({
  useUser: () => ({
    userId: 'user_1',
    userName: 'Test User',
    avatarUrl: '',
    equippedCosmetics: {},
    isAdmin: false,
    roles: [],
    refreshProfile: jest.fn(),
  }),
}));

// Mock api module
const mockFetchPublicProfile = jest.fn();
const mockFetchAchievements = jest.fn().mockResolvedValue({ earned: [], available: [] });
jest.mock('@/lib/api', () => ({
  ...jest.requireActual('@/lib/api'),
  fetchPublicProfile: (...args: any[]) => mockFetchPublicProfile(...args),
  fetchAchievements: (...args: any[]) => mockFetchAchievements(...args),
}));

// Mock child components
jest.mock('@/components/AvatarFrame', () => (props: any) => <div data-testid="avatar-frame" />);
jest.mock('@/components/NameColorRenderer', () => ({ name }: { name: string }) => <span data-testid="name-renderer">{name}</span>);
jest.mock('@/components/TitleFlair', () => () => null);
jest.mock('@/components/RoleBadge', () => ({ role }: any) => <span data-testid="role-badge">{role.name}</span>);
jest.mock('@/components/AchievementShowcase', () => () => <div data-testid="achievement-showcase" />);
jest.mock('next/link', () => ({ children, ...props }: any) => <a {...props}>{children}</a>);

import ProfilePage from '@/app/profile/page';

afterEach(() => {
  jest.clearAllMocks();
});

const validProfile = {
  id: 'user_1',
  name: 'Alice',
  username: 'alice',
  avatar_url: null,
  created_at: '2025-01-01',
  bio: 'Hello',
  location: 'NYC',
  website: null,
  year: 'junior',
  majors: ['Computer Science'],
  minors: [],
  school: 'Boston University',
  roles: [],
  equipped_cosmetics: {},
  featured_achievements: [],
  stats: { streak_count: 5, session_count: 10, documents_count: 3, achievements_count: 2 },
};

describe('ProfilePage', () => {
  it('shows loading state initially', () => {
    mockFetchPublicProfile.mockImplementation(() => new Promise(() => {}));
    render(<ProfilePage />);
    expect(screen.getByText(/loading profile/i)).toBeInTheDocument();
  });

  it('shows error when fetch fails', async () => {
    mockFetchPublicProfile.mockRejectedValue(new Error('Not found'));
    render(<ProfilePage />);
    await waitFor(() => {
      expect(screen.getByText(/not found/i)).toBeInTheDocument();
    });
  });

  it('renders profile data on success', async () => {
    mockFetchPublicProfile.mockResolvedValue(validProfile);
    render(<ProfilePage />);
    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument();
    });
    expect(screen.getByText('@alice')).toBeInTheDocument();
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('shows edit button for own profile', async () => {
    mockFetchPublicProfile.mockResolvedValue({
      ...validProfile,
      name: 'Test User',
      username: null,
      bio: null,
    });
    render(<ProfilePage />);
    await waitFor(() => {
      expect(screen.getByText(/edit profile/i)).toBeInTheDocument();
    });
  });

  it('renders role badges', async () => {
    mockFetchPublicProfile.mockResolvedValue({
      ...validProfile,
      roles: [{ role: { id: 'r1', name: 'Admin', slug: 'admin', color: '#f00' }, granted_at: '2025-01-01' }],
    });
    render(<ProfilePage />);
    await waitFor(() => {
      expect(screen.getByTestId('role-badge')).toBeInTheDocument();
    });
  });
});
