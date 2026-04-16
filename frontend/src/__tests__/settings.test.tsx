/**
 * Tests for app/settings/page.tsx
 *
 * Covers: section navigation, loading state, profile form rendering,
 * section switching.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/settings',
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

// Mock ToastProvider
jest.mock('@/components/ToastProvider', () => ({
  useToast: () => ({ showToast: jest.fn() }),
}));

// Mock api module
const mockFetchSettings = jest.fn();
const mockUpdateSettings = jest.fn();
const mockUpdateProfile = jest.fn();
const mockUploadAvatar = jest.fn();
const mockExportData = jest.fn();
const mockDeleteAccount = jest.fn();
jest.mock('@/lib/api', () => ({
  fetchSettings: (...args: any[]) => mockFetchSettings(...args),
  updateSettings: (...args: any[]) => mockUpdateSettings(...args),
  updateProfile: (...args: any[]) => mockUpdateProfile(...args),
  uploadAvatar: (...args: any[]) => mockUploadAvatar(...args),
  exportData: (...args: any[]) => mockExportData(...args),
  deleteAccount: (...args: any[]) => mockDeleteAccount(...args),
}));

// Mock components
jest.mock('@/components/CosmeticsManager', () => () => <div data-testid="cosmetics-manager" />);
jest.mock('@/components/AvatarFrame', () => (props: any) => <div data-testid="avatar-frame" />);

import SettingsPage from '@/app/settings/page';

afterEach(() => jest.clearAllMocks());

const mockSettings = {
  user_id: 'user_1',
  profile_visibility: 'public',
  activity_status_visible: true,
  notification_email: true,
  notification_push: false,
  notification_in_app: true,
  theme: 'light',
  font_size: 'md',
  accent_color: null,
};

describe('SettingsPage', () => {
  beforeEach(() => {
    mockFetchSettings.mockResolvedValue(mockSettings);
  });

  it('renders section navigation', async () => {
    render(<SettingsPage />);
    await waitFor(() => {
      expect(screen.getAllByText('Profile').length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText('Account')).toBeInTheDocument();
    expect(screen.getByText('Notifications')).toBeInTheDocument();
    expect(screen.getByText('Appearance')).toBeInTheDocument();
    expect(screen.getByText('Privacy')).toBeInTheDocument();
    expect(screen.getByText('Cosmetics')).toBeInTheDocument();
    expect(screen.getByText('Danger Zone')).toBeInTheDocument();
  });

  it('shows profile section by default', async () => {
    render(<SettingsPage />);
    await waitFor(() => {
      expect(screen.getByText(/display name/i)).toBeInTheDocument();
    });
  });

  it('switches to danger zone section on click', async () => {
    render(<SettingsPage />);
    await waitFor(() => {
      expect(screen.getByText('Danger Zone')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Danger Zone'));
    await waitFor(() => {
      expect(screen.getByText(/delete account/i)).toBeInTheDocument();
    });
  });

  it('switches to notifications section', async () => {
    render(<SettingsPage />);
    await waitFor(() => {
      expect(screen.getByText('Notifications')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Notifications'));
    await waitFor(() => {
      expect(screen.getByText(/email notifications/i)).toBeInTheDocument();
    });
  });
});
