'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useUser } from '@/context/UserContext';
import { useToast } from '@/components/ToastProvider';
import {
  fetchSettings, updateSettings, updateProfile, uploadAvatar,
  exportData, deleteAccount, fetchPublicProfile, fetchAchievements,
} from '@/lib/api';
import type { UserSettings, UserProfile, UserAchievement, Achievement } from '@/lib/types';
import AvatarFrame from '@/components/AvatarFrame';
import CosmeticsManager from '@/components/CosmeticsManager';
import NameColorRenderer from '@/components/NameColorRenderer';
import TitleFlair from '@/components/TitleFlair';
import RoleBadge from '@/components/RoleBadge';
import AchievementShowcase from '@/components/AchievementShowcase';
import {
  User, ShieldCheck, Bell, Palette, Lock, Sparkles, AlertTriangle,
  Check, X, Eye, Camera, Download,
} from 'lucide-react';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

type SectionKey = 'profile' | 'account' | 'notifications' | 'appearance' | 'privacy' | 'cosmetics' | 'danger';

const SECTION_GROUPS: {
  group: string;
  items: { key: SectionKey; label: string; icon: typeof User; hint: string }[];
}[] = [
  {
    group: 'Identity',
    items: [
      { key: 'profile', label: 'Profile', icon: User, hint: 'Your public details' },
      { key: 'account', label: 'Account', icon: ShieldCheck, hint: 'Sign-in & security' },
    ],
  },
  {
    group: 'Preferences',
    items: [
      { key: 'notifications', label: 'Notifications', icon: Bell, hint: 'Pings & emails' },
      { key: 'appearance', label: 'Appearance', icon: Palette, hint: 'Theme & feel' },
      { key: 'privacy', label: 'Privacy', icon: Lock, hint: 'Who sees what' },
    ],
  },
  {
    group: 'Personalization',
    items: [
      { key: 'cosmetics', label: 'Cosmetics', icon: Sparkles, hint: 'Frames, colors, titles' },
    ],
  },
  {
    group: 'Manage',
    items: [
      { key: 'danger', label: 'Danger Zone', icon: AlertTriangle, hint: 'Export or delete' },
    ],
  },
];

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      onClick={() => !disabled && onChange(!checked)}
      style={{
        width: '42px',
        height: '24px',
        borderRadius: 'var(--radius-full)',
        background: checked ? 'var(--accent)' : 'var(--bg-subtle)',
        border: `1px solid ${checked ? 'var(--accent)' : 'var(--border-mid)'}`,
        position: 'relative',
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'background var(--dur-fast), border-color var(--dur-fast)',
        padding: 0,
        opacity: disabled ? 0.4 : 1,
        flexShrink: 0,
      }}
    >
      <div style={{
        width: '18px',
        height: '18px',
        borderRadius: '50%',
        background: '#fff',
        position: 'absolute',
        top: '2px',
        left: checked ? '21px' : '2px',
        transition: 'left var(--dur-fast)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      }} />
    </button>
  );
}

export default function SettingsPage() {
  const { userId, userName, avatarUrl, equippedCosmetics, refreshProfile } = useUser();
  const { showToast } = useToast();
  const [activeSection, setActiveSection] = useState<SectionKey>('profile');
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);

  // Profile form state
  const [displayName, setDisplayName] = useState('');
  const [username, setUsername] = useState('');
  const [bio, setBio] = useState('');
  const [location, setLocation] = useState('');
  const [website, setWebsite] = useState('');
  const [usernameAvailable, setUsernameAvailable] = useState<boolean | null>(null);
  const [checkingUsername, setCheckingUsername] = useState(false);
  const usernameTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Profile preview modal
  const [profileModalMounted, setProfileModalMounted] = useState(false);
  const [profileModalVisible, setProfileModalVisible] = useState(false);
  const [previewProfile, setPreviewProfile] = useState<UserProfile | null>(null);
  const [previewAchievements, setPreviewAchievements] = useState<{ earned: UserAchievement[]; available: Achievement[] } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Delete account
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [showDeleteForm, setShowDeleteForm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!userId) return;
    setLoading(true);
    fetchSettings(userId)
      .then(data => {
        setSettings(data);
        setDisplayName(data.display_name || '');
        setUsername(data.username || '');
        setBio(data.bio || '');
        setLocation(data.location || '');
        setWebsite(data.website || '');
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [userId]);

  const checkUsername = useCallback((val: string) => {
    if (usernameTimerRef.current) clearTimeout(usernameTimerRef.current);
    if (!val || val === settings?.username) {
      setUsernameAvailable(null);
      return;
    }
    setCheckingUsername(true);
    usernameTimerRef.current = setTimeout(async () => {
      try {
        await updateProfile(userId, { username: val } as any);
        setUsernameAvailable(true);
      } catch {
        setUsernameAvailable(false);
      } finally {
        setCheckingUsername(false);
      }
    }, 500);
  }, [userId, settings?.username]);

  const saveProfile = async () => {
    try {
      await updateProfile(userId, { display_name: displayName, username, bio, location, website } as any);
      showToast('Profile saved');
      refreshProfile();
    } catch (e: any) {
      showToast(e.message || 'Failed to save profile');
    }
  };

  const saveSettings = async (updates: Partial<UserSettings>) => {
    try {
      const updated = await updateSettings(userId, updates);
      setSettings(prev => prev ? { ...prev, ...updated } : updated);
      showToast('Settings saved');
      refreshProfile();
    } catch (e: any) {
      showToast(e.message || 'Failed to save settings');
    }
  };

  const openProfilePreview = async () => {
    setProfileModalMounted(true);
    requestAnimationFrame(() => requestAnimationFrame(() => setProfileModalVisible(true)));
    setPreviewLoading(true);
    try {
      const [prof, ach] = await Promise.all([
        fetchPublicProfile(userId),
        fetchAchievements(userId).catch(() => null),
      ]);
      setPreviewProfile(prof);
      setPreviewAchievements(ach);
    } catch {
      setPreviewProfile(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const closeProfilePreview = () => {
    setProfileModalVisible(false);
    setTimeout(() => setProfileModalMounted(false), 250);
  };

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadAvatar(userId, file);
      showToast('Avatar updated');
      refreshProfile();
    } catch (e: any) {
      showToast(e.message || 'Failed to upload avatar');
    }
  };

  const handleExport = async () => {
    try {
      const data = await exportData(userId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sapling-data-${userId}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast('Data exported');
    } catch (e: any) {
      showToast(e.message || 'Failed to export data');
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirm !== 'DELETE') return;
    setDeleting(true);
    try {
      await deleteAccount(userId, deleteConfirm);
      showToast('Account scheduled for deletion');
    } catch (e: any) {
      showToast(e.message || 'Failed to delete account');
    } finally {
      setDeleting(false);
    }
  };

  const handleThemeToggle = (theme: string) => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    saveSettings({ theme });
  };

  if (loading) {
    return (
      <div style={{ width: '80.5vw', margin: '40px auto', padding: '0 clamp(16px, 3vw, 48px)', fontFamily: UI_FONT }}>
        <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>Loading settings...</div>
      </div>
    );
  }

  // ── Shared style tokens ────────────────────────────────────────────────
  const inputStyle: React.CSSProperties = {
    width: '100%',
    background: 'var(--bg-input)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    padding: '11px 14px',
    fontSize: '14px',
    fontFamily: 'inherit',
    outline: 'none',
    transition: 'border-color var(--dur-fast), box-shadow var(--dur-fast)',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: '11px',
    fontWeight: 600,
    color: 'var(--text-dim)',
    marginBottom: '8px',
    display: 'block',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  };

  const cardStyle: React.CSSProperties = {
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: '32px',
    boxShadow: 'var(--shadow-sm)',
  };

  const settingRowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '18px 0',
    borderBottom: '1px solid var(--border-light)',
    gap: '24px',
  };

  // ── Section header (lean: title + dim description, action on right) ──────
  const SectionHeader = ({ title, description, action, danger }: {
    title: string; description: string; action?: React.ReactNode; danger?: boolean;
  }) => (
    <div style={{ marginBottom: '1.25rem' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px',
        marginBottom: '4px',
      }}>
        <h1 style={{
          fontFamily: UI_FONT,
          fontSize: '20px',
          fontWeight: 500,
          letterSpacing: '-0.01em',
          color: danger ? '#b91c1c' : 'var(--text)',
          margin: 0,
          lineHeight: 1.2,
        }}>
          {title}
        </h1>
        {action}
      </div>
      <p style={{
        fontFamily: UI_FONT,
        fontSize: '13px',
        color: 'var(--text-secondary)',
        margin: 0,
        lineHeight: 1.5,
      }}>
        {description}
      </p>
    </div>
  );

  return (
    <div style={{ position: 'relative', minHeight: 'calc(100vh - 64px)', fontFamily: UI_FONT, paddingBottom: '80px' }}>
      {/* Solid background */}
      <div aria-hidden style={{ position: 'fixed', inset: 0, zIndex: 0, background: 'var(--bg)' }} />

      <div style={{ position: 'relative', zIndex: 1, width: '80.5vw', margin: '0 auto', padding: 'clamp(28px, 4vw, 56px) 0 0' }}>

        {/* ── Layout: nav + content ────────────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: '220px minmax(0, 1fr)', gap: '2.5rem', alignItems: 'flex-start' }}>

          {/* Sidebar */}
          <nav style={{ position: 'sticky', top: '24px', alignSelf: 'flex-start' }}>
            <h2 style={{
              fontFamily: UI_FONT,
              fontSize: '32px',
              fontWeight: 700,
              letterSpacing: '-0.02em',
              color: 'var(--text)',
              margin: 0,
              marginBottom: '1.75rem',
              padding: '0 12px',
              lineHeight: 1.1,
            }}>
              Settings
            </h2>

            {SECTION_GROUPS.map((group, gi) => (
              <div key={group.group} style={{ marginBottom: gi === SECTION_GROUPS.length - 1 ? 0 : '1.25rem' }}>
                <div style={{
                  fontFamily: UI_FONT,
                  fontSize: '12px',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  padding: '0 12px 10px',
                }}>
                  {group.group}
                </div>
                <div style={{ paddingLeft: '20px', borderLeft: '1px solid var(--border-light)', marginLeft: '12px' }}>
                  {group.items.map(item => {
                    const Icon = item.icon;
                    const active = activeSection === item.key;
                    return (
                      <button
                        key={item.key}
                        onClick={() => setActiveSection(item.key)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '12px',
                          width: '100%',
                          textAlign: 'left',
                          padding: '8px 4px',
                          borderRadius: 0,
                          fontSize: '16px',
                          fontFamily: 'inherit',
                          fontWeight: active ? 700 : 400,
                          color: active ? 'var(--text)' : 'var(--text-secondary)',
                          background: 'transparent',
                          border: 'none',
                          cursor: 'pointer',
                          transition: 'color var(--dur-fast), font-weight var(--dur-fast)',
                        }}
                        onMouseEnter={e => {
                          if (!active) e.currentTarget.style.color = 'var(--text)';
                        }}
                        onMouseLeave={e => {
                          if (!active) e.currentTarget.style.color = 'var(--text-secondary)';
                        }}
                      >
                        <Icon size={17} strokeWidth={active ? 2.2 : 1.8} />
                        <span style={{ flex: 1, minWidth: 0 }}>{item.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>

          {/* Content column */}
          <div style={{ minWidth: 0 }}>

            {/* ── Profile ─────────────────────────────────────────────────── */}
            {activeSection === 'profile' && (
              <div className="fade-up">
                <SectionHeader
                  title="Profile"
                  description="Your public face on Sapling. What classmates and study partners see."
                  action={
                    <button
                      onClick={openProfilePreview}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontSize: '13px',
                        fontWeight: 500,
                        color: 'var(--accent)',
                        padding: '8px 16px',
                        border: '1px solid var(--accent-border)',
                        borderRadius: 'var(--radius-full)',
                        background: 'var(--accent-dim)',
                        fontFamily: 'inherit',
                        whiteSpace: 'nowrap',
                        cursor: 'pointer',
                      }}
                    >
                      <Eye size={13} /> View profile
                    </button>
                  }
                />

                {/* Avatar block */}
                <div style={{ ...cardStyle, marginBottom: '20px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '24px', flexWrap: 'wrap' }}>
                    <div style={{ position: 'relative' }}>
                      <AvatarFrame
                        userId={userId}
                        name={userName}
                        size={88}
                        avatarUrl={avatarUrl}
                        frameUrl={equippedCosmetics?.avatar_frame?.asset_url}
                      />
                    </div>
                    <div style={{ flex: 1, minWidth: '200px' }}>
                      <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text)', marginBottom: '4px' }}>
                        Avatar
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginBottom: '14px', lineHeight: 1.5 }}>
                        Square images work best. JPG, PNG, or GIF up to 2MB.
                      </div>
                      <label style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '8px',
                        cursor: 'pointer',
                        padding: '9px 16px',
                        fontSize: '13px',
                        fontWeight: 500,
                        fontFamily: 'inherit',
                        color: 'var(--accent)',
                        border: '1px solid var(--accent-border)',
                        background: 'var(--accent-dim)',
                        borderRadius: 'var(--radius-md)',
                        transition: 'background var(--dur-fast)',
                      }}>
                        <Camera size={14} />
                        Change avatar
                        <input type="file" accept="image/*" onChange={handleAvatarUpload} style={{ display: 'none' }} />
                      </label>
                    </div>
                  </div>
                </div>

                {/* Identity fields */}
                <div style={cardStyle}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '20px 24px' }}>
                    <div>
                      <label style={labelStyle}>Display name</label>
                      <input style={inputStyle} value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Your name" />
                    </div>
                    <div>
                      <label style={labelStyle}>Username</label>
                      <div style={{ position: 'relative' }}>
                        <input
                          style={{
                            ...inputStyle,
                            paddingLeft: '26px',
                            paddingRight: checkingUsername || usernameAvailable !== null ? '36px' : '14px',
                          }}
                          value={username}
                          onChange={e => { setUsername(e.target.value); checkUsername(e.target.value); }}
                          placeholder="your-handle"
                        />
                        <span style={{
                          position: 'absolute',
                          left: '12px',
                          top: '50%',
                          transform: 'translateY(-50%)',
                          color: 'var(--text-dim)',
                          fontSize: '14px',
                          pointerEvents: 'none',
                        }}>@</span>
                        {checkingUsername && (
                          <span style={{
                            position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)',
                            width: '14px', height: '14px', border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
                            borderRadius: '50%', animation: 'sapling-spin 0.7s linear infinite',
                          }} />
                        )}
                        {!checkingUsername && usernameAvailable === true && (
                          <Check size={16} style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--brand-success)' }} />
                        )}
                        {!checkingUsername && usernameAvailable === false && (
                          <X size={16} style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--brand-struggle)' }} />
                        )}
                      </div>
                      <div style={{ minHeight: '16px', marginTop: '6px' }}>
                        {usernameAvailable === false && (
                          <span style={{ fontSize: '11px', color: 'var(--brand-struggle)' }}>That handle is already taken</span>
                        )}
                        {usernameAvailable === true && (
                          <span style={{ fontSize: '11px', color: 'var(--brand-success)' }}>Available</span>
                        )}
                      </div>
                    </div>
                    <div style={{ gridColumn: '1 / -1' }}>
                      <label style={labelStyle}>Bio</label>
                      <textarea
                        style={{ ...inputStyle, minHeight: '96px', resize: 'vertical', lineHeight: 1.55 }}
                        value={bio}
                        onChange={e => setBio(e.target.value)}
                        placeholder="A line or two about how you study, what you're working on, or what you're interested in."
                        maxLength={280}
                      />
                      <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px', textAlign: 'right' }}>
                        {bio.length} / 280
                      </div>
                    </div>
                    <div>
                      <label style={labelStyle}>Location</label>
                      <input style={inputStyle} value={location} onChange={e => setLocation(e.target.value)} placeholder="Boston, MA" />
                    </div>
                    <div>
                      <label style={labelStyle}>Website</label>
                      <input style={inputStyle} value={website} onChange={e => setWebsite(e.target.value)} placeholder="https://yoursite.com" />
                    </div>
                  </div>

                  <div style={{
                    marginTop: '28px',
                    paddingTop: '20px',
                    borderTop: '1px solid var(--border-light)',
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: '10px',
                  }}>
                    <button
                      onClick={saveProfile}
                      style={{
                        background: 'var(--accent)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 'var(--radius-md)',
                        padding: '10px 22px',
                        fontSize: '13.5px',
                        fontWeight: 600,
                        fontFamily: 'inherit',
                        cursor: 'pointer',
                        transition: 'background var(--dur-fast), transform var(--dur-fast)',
                        boxShadow: '0 2px 6px rgba(26,92,42,0.18)',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-hover)'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'var(--accent)'; }}
                    >
                      Save profile
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* ── Account ─────────────────────────────────────────────────── */}
            {activeSection === 'account' && (
              <div className="fade-up">
                <SectionHeader
                  title="Account"
                  description="Sign-in is handled by Google. Sapling never sees your password."
                />

                <div style={cardStyle}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '16px',
                    padding: '20px',
                    background: 'var(--bg-subtle)',
                    border: '1px solid var(--border-light)',
                    borderRadius: 'var(--radius-md)',
                  }}>
                    <div style={{
                      width: '44px', height: '44px', borderRadius: 'var(--radius-md)',
                      background: '#fff', border: '1px solid var(--border)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: '20px', fontWeight: 700, color: '#4285F4', fontFamily: 'Arial, sans-serif',
                    }}>
                      G
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)' }}>Google</div>
                      <div style={{ fontSize: '12.5px', color: 'var(--text-dim)', marginTop: '2px' }}>
                        Email, password, and 2-step verification are managed in your Google account.
                      </div>
                    </div>
                    <span className="badge" style={{ fontSize: '10px' }}>Connected</span>
                  </div>

                  <div style={{
                    marginTop: '18px',
                    fontSize: '12.5px',
                    color: 'var(--text-dim)',
                    lineHeight: 1.55,
                    padding: '0 4px',
                  }}>
                    To change the email tied to your account, switch the Google account you sign in with.
                  </div>
                </div>
              </div>
            )}

            {/* ── Notifications ───────────────────────────────────────────── */}
            {activeSection === 'notifications' && (
              <div className="fade-up">
                <SectionHeader
                  title="Notifications"
                  description="Pick which channels Sapling can use to reach you."
                />

                <div style={cardStyle}>
                  <div style={{ ...settingRowStyle, paddingTop: 0 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>Email notifications</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px', lineHeight: 1.4 }}>
                        Weekly progress digests, assignment reminders, and important account updates.
                      </div>
                    </div>
                    <Toggle checked={settings?.notification_email ?? true} onChange={v => saveSettings({ notification_email: v })} />
                  </div>
                  <div style={settingRowStyle}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>In-app notifications</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px', lineHeight: 1.4 }}>
                        Toasts and badges shown while you're using Sapling.
                      </div>
                    </div>
                    <Toggle checked={settings?.notification_in_app ?? true} onChange={v => saveSettings({ notification_in_app: v })} />
                  </div>
                  <div style={{ ...settingRowStyle, borderBottom: 'none', paddingBottom: 0 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>Push notifications</span>
                        <span className="badge" style={{ fontSize: '9.5px', padding: '1px 8px' }}>Coming soon</span>
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px', lineHeight: 1.4 }}>
                        Browser-level notifications even when Sapling isn't open.
                      </div>
                    </div>
                    <Toggle checked={false} onChange={() => {}} disabled />
                  </div>
                </div>
              </div>
            )}

            {/* ── Appearance ──────────────────────────────────────────────── */}
            {activeSection === 'appearance' && (
              <div className="fade-up">
                <SectionHeader
                  title="Appearance"
                  description="Set the mood. Light or dark, dense or roomy, in the green of your choice."
                />

                <div style={cardStyle}>
                  {/* Theme */}
                  <div style={{ ...settingRowStyle, paddingTop: 0, alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>Theme</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px' }}>Switch between light and dark.</div>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      {(['light', 'dark'] as const).map(t => {
                        const active = settings?.theme === t;
                        return (
                          <button
                            key={t}
                            onClick={() => handleThemeToggle(t)}
                            style={{
                              padding: '12px 18px',
                              borderRadius: 'var(--radius-md)',
                              border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                              background: active ? 'var(--accent-dim)' : 'var(--bg-input)',
                              color: active ? 'var(--accent)' : 'var(--text-muted)',
                              fontWeight: active ? 600 : 500,
                              fontSize: '13px',
                              fontFamily: 'inherit',
                              cursor: 'pointer',
                              minWidth: '92px',
                              display: 'flex',
                              flexDirection: 'column',
                              alignItems: 'center',
                              gap: '6px',
                              transition: 'all var(--dur-fast)',
                            }}
                          >
                            <div style={{
                              width: '44px', height: '28px', borderRadius: '6px',
                              background: t === 'light' ? '#f8fbf8' : '#1a1d1b',
                              border: `1px solid ${t === 'light' ? 'var(--border-mid)' : '#2a2d2b'}`,
                            }} />
                            {t.charAt(0).toUpperCase() + t.slice(1)}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Font size */}
                  <div style={{ ...settingRowStyle, alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>Font size</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px' }}>Comfort vs. density across the app.</div>
                    </div>
                    <div style={{ display: 'flex', gap: '4px', background: 'var(--bg-subtle)', padding: '3px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-light)' }}>
                      {['small', 'medium', 'large'].map(s => {
                        const active = settings?.font_size === s;
                        return (
                          <button
                            key={s}
                            onClick={() => saveSettings({ font_size: s })}
                            style={{
                              padding: '7px 14px',
                              borderRadius: '6px',
                              border: 'none',
                              background: active ? 'var(--bg-panel)' : 'transparent',
                              color: active ? 'var(--text)' : 'var(--text-dim)',
                              fontSize: s === 'small' ? '11px' : s === 'medium' ? '13px' : '15px',
                              fontWeight: active ? 600 : 500,
                              fontFamily: 'inherit',
                              cursor: 'pointer',
                              boxShadow: active ? 'var(--shadow-sm)' : 'none',
                              transition: 'all var(--dur-fast)',
                            }}
                          >
                            Aa
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Accent color */}
                  <div style={{ ...settingRowStyle, borderBottom: 'none', paddingBottom: 0, alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>Accent color</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px' }}>The hue used for highlights and active states.</div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      {['#1a5c2a', '#2b8c96', '#e8a33a', '#8a63d2', '#dc2626'].map(c => {
                        const active = (settings?.accent_color || '#1a5c2a') === c;
                        return (
                          <button
                            key={c}
                            onClick={() => {
                              document.documentElement.style.setProperty('--accent', c);
                              saveSettings({ accent_color: c });
                            }}
                            aria-label={`Accent ${c}`}
                            style={{
                              width: '28px', height: '28px', borderRadius: '50%',
                              background: c,
                              border: active ? `2px solid var(--text)` : '2px solid transparent',
                              outline: active ? `2px solid ${c}` : 'none',
                              outlineOffset: '2px',
                              cursor: 'pointer',
                              padding: 0,
                              transition: 'transform var(--dur-fast)',
                            }}
                          />
                        );
                      })}
                      <label style={{
                        position: 'relative',
                        width: '28px', height: '28px', borderRadius: '50%',
                        background: 'conic-gradient(from 0deg, #ff6b6b, #f9d423, #6bcf7f, #4dabf7, #b197fc, #ff6b6b)',
                        cursor: 'pointer',
                        border: '2px solid transparent',
                      }}>
                        <input
                          type="color"
                          value={settings?.accent_color || '#1a5c2a'}
                          onChange={e => {
                            document.documentElement.style.setProperty('--accent', e.target.value);
                            saveSettings({ accent_color: e.target.value });
                          }}
                          style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
                        />
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── Privacy ─────────────────────────────────────────────────── */}
            {activeSection === 'privacy' && (
              <div className="fade-up">
                <SectionHeader
                  title="Privacy"
                  description="Decide what's visible to other students and what stays just for you."
                />

                <div style={cardStyle}>
                  <div style={{ ...settingRowStyle, paddingTop: 0, alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>Profile visibility</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px', lineHeight: 1.4 }}>
                        Public profiles can be discovered by classmates in study rooms.
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '4px', background: 'var(--bg-subtle)', padding: '3px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-light)' }}>
                      {['public', 'private'].map(v => {
                        const active = settings?.profile_visibility === v;
                        return (
                          <button
                            key={v}
                            onClick={() => saveSettings({ profile_visibility: v })}
                            style={{
                              padding: '7px 16px',
                              borderRadius: '6px',
                              border: 'none',
                              background: active ? 'var(--bg-panel)' : 'transparent',
                              color: active ? 'var(--text)' : 'var(--text-dim)',
                              fontSize: '12.5px',
                              fontWeight: active ? 600 : 500,
                              fontFamily: 'inherit',
                              cursor: 'pointer',
                              boxShadow: active ? 'var(--shadow-sm)' : 'none',
                              transition: 'all var(--dur-fast)',
                            }}
                          >
                            {v.charAt(0).toUpperCase() + v.slice(1)}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ ...settingRowStyle, borderBottom: 'none', paddingBottom: 0 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 500, color: 'var(--text)' }}>Activity status</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '3px', lineHeight: 1.4 }}>
                        Show a green dot to others when you're online.
                      </div>
                    </div>
                    <Toggle
                      checked={settings?.activity_status_visible ?? true}
                      onChange={v => saveSettings({ activity_status_visible: v })}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* ── Cosmetics ───────────────────────────────────────────────── */}
            {activeSection === 'cosmetics' && (
              <div className="fade-up">
                <SectionHeader
                  title="Cosmetics"
                  description="Equip frames, name colors, and titles you've earned through achievements."
                />
                <div style={cardStyle}>
                  <CosmeticsManager userId={userId} />
                </div>
              </div>
            )}

            {/* ── Danger Zone ─────────────────────────────────────────────── */}
            {activeSection === 'danger' && (
              <div className="fade-up">
                <SectionHeader
                  title="Danger Zone"
                  description="Irreversible actions. Handled with both hands."
                  danger
                />

                {/* Export */}
                <div style={{
                  background: 'var(--bg-panel)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-lg)',
                  padding: '24px 28px',
                  marginBottom: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '20px',
                  boxShadow: 'var(--shadow-sm)',
                }}>
                  <div style={{
                    width: '44px', height: '44px', borderRadius: 'var(--radius-md)',
                    background: 'var(--accent-dim)', color: 'var(--accent)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    <Download size={18} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '14.5px', fontWeight: 600, color: 'var(--text)', marginBottom: '4px' }}>Export your data</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-dim)', lineHeight: 1.5 }}>
                      Download every conversation, document, and graph node as a single JSON file.
                    </div>
                  </div>
                  <button className="btn-ghost" onClick={handleExport} style={{ flexShrink: 0 }}>Export</button>
                </div>

                {/* Delete */}
                <div style={{
                  background: 'var(--bg-panel)',
                  border: '1px solid rgba(220,38,38,0.25)',
                  borderRadius: 'var(--radius-lg)',
                  padding: '24px 28px',
                  boxShadow: '0 1px 3px rgba(220,38,38,0.05)',
                  position: 'relative',
                  overflow: 'hidden',
                }}>
                  <div style={{
                    position: 'absolute',
                    top: 0, left: 0, right: 0, height: '3px',
                    background: '#dc2626',
                  }} />
                  <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
                    <div style={{
                      width: '44px', height: '44px', borderRadius: 'var(--radius-md)',
                      background: 'rgba(220,38,38,0.08)', color: '#dc2626',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      <AlertTriangle size={18} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14.5px', fontWeight: 600, color: 'var(--text)', marginBottom: '4px' }}>Delete account</div>
                      <div style={{ fontSize: '13px', color: 'var(--text-dim)', lineHeight: 1.5 }}>
                        Schedules permanent deletion of your account and all associated data after a 30-day grace period.
                      </div>
                    </div>
                    <button
                      onClick={() => setShowDeleteForm(!showDeleteForm)}
                      style={{
                        background: showDeleteForm ? 'transparent' : 'rgba(220,38,38,0.08)',
                        color: '#dc2626',
                        border: '1px solid rgba(220,38,38,0.3)',
                        borderRadius: 'var(--radius-md)',
                        padding: '9px 18px',
                        fontSize: '13px',
                        fontWeight: 500,
                        fontFamily: 'inherit',
                        cursor: 'pointer',
                        flexShrink: 0,
                        transition: 'background var(--dur-fast)',
                      }}
                    >
                      {showDeleteForm ? 'Cancel' : 'Delete account'}
                    </button>
                  </div>

                  {showDeleteForm && (
                    <div style={{
                      marginTop: '20px',
                      padding: '20px',
                      background: 'rgba(220,38,38,0.04)',
                      border: '1px dashed rgba(220,38,38,0.25)',
                      borderRadius: 'var(--radius-md)',
                    }}>
                      <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: 0, marginBottom: '14px', lineHeight: 1.55 }}>
                        Type <strong style={{ color: '#dc2626', fontFamily: 'JetBrains Mono, monospace' }}>DELETE</strong> below to confirm. You'll have 30 days to change your mind by signing back in.
                      </p>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        <input
                          style={{ ...inputStyle, maxWidth: '280px', fontFamily: 'JetBrains Mono, monospace', letterSpacing: '0.1em' }}
                          value={deleteConfirm}
                          onChange={e => setDeleteConfirm(e.target.value)}
                          placeholder="DELETE"
                        />
                        <button
                          onClick={handleDeleteAccount}
                          disabled={deleteConfirm !== 'DELETE' || deleting}
                          style={{
                            background: deleteConfirm === 'DELETE' ? '#dc2626' : 'var(--bg-subtle)',
                            color: deleteConfirm === 'DELETE' ? '#fff' : 'var(--text-dim)',
                            border: 'none',
                            borderRadius: 'var(--radius-md)',
                            padding: '11px 20px',
                            fontSize: '13px',
                            fontWeight: 600,
                            fontFamily: 'inherit',
                            cursor: deleteConfirm === 'DELETE' && !deleting ? 'pointer' : 'not-allowed',
                            transition: 'background var(--dur-fast)',
                          }}
                        >
                          {deleting ? 'Deleting…' : 'Confirm deletion'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Profile Preview Modal ───────────────────────────────────────────── */}
      {profileModalMounted && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: profileModalVisible ? 'rgba(15,23,42,0.45)' : 'rgba(0,0,0,0)',
            backdropFilter: profileModalVisible ? 'blur(6px)' : 'blur(0px)',
            WebkitBackdropFilter: profileModalVisible ? 'blur(6px)' : 'blur(0px)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
            transition: 'background 0.25s ease, backdrop-filter 0.25s ease',
          }}
          onClick={e => { if (e.target === e.currentTarget) closeProfilePreview(); }}
        >
          <div style={{
            background: 'var(--bg-panel)',
            borderRadius: 'var(--radius-lg)',
            width: '760px',
            maxWidth: '95vw',
            maxHeight: '90vh',
            overflowY: 'auto',
            position: 'relative',
            border: '1px solid var(--border)',
            boxShadow: '0 32px 80px rgba(15,23,42,0.25)',
            fontFamily: UI_FONT,
            opacity: profileModalVisible ? 1 : 0,
            transform: profileModalVisible ? 'scale(1) translateY(0)' : 'scale(0.95) translateY(12px)',
            transition: 'opacity 0.25s ease, transform 0.25s ease',
          }}>
            <button
              onClick={closeProfilePreview}
              style={{
                position: 'sticky',
                top: '12px',
                float: 'right',
                marginRight: '12px',
                background: 'var(--bg-subtle)',
                border: '1px solid var(--border)',
                borderRadius: '50%',
                width: '32px',
                height: '32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                color: 'var(--text-muted)',
                zIndex: 10,
              }}
            >
              <X size={14} />
            </button>

            {previewLoading ? (
              <div style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--text-dim)', fontSize: '13px' }}>
                Loading profile…
              </div>
            ) : !previewProfile ? (
              <div style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--brand-struggle)', fontSize: '13px' }}>
                Failed to load profile
              </div>
            ) : (
              <ProfilePreviewContent profile={previewProfile} achievements={previewAchievements} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Profile Preview (rendered inside modal) ──────────────────────────────────

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
      style={{ width: '8px', height: '8px', borderRadius: '50%', background: RARITY_COLORS[rarity] || RARITY_COLORS.common, flexShrink: 0 }}
    />
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

function ProfilePreviewContent({ profile, achievements }: { profile: UserProfile; achievements: { earned: UserAchievement[]; available: Achievement[] } | null }) {
  const yearLabel = profile.year ? profile.year.charAt(0).toUpperCase() + profile.year.slice(1) : null;

  return (
    <div style={{ padding: '32px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '18px', marginBottom: '20px' }}>
        <AvatarFrame
          userId={profile.id}
          name={profile.name}
          size={72}
          avatarUrl={profile.avatar_url || undefined}
          frameUrl={profile.equipped_cosmetics?.avatar_frame?.asset_url}
        />
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '22px', fontWeight: 700 }}>
              <NameColorRenderer name={profile.name} cssValue={profile.equipped_cosmetics?.name_color?.css_value} />
            </span>
            {profile.equipped_cosmetics?.title && (
              <TitleFlair title={profile.equipped_cosmetics.title.name} rarity={profile.equipped_cosmetics.title.rarity} />
            )}
          </div>
          {profile.username && (
            <div style={{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '2px' }}>@{profile.username}</div>
          )}
          {profile.roles.length > 0 && (
            <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '6px' }}>
              {profile.roles.map(ur => <RoleBadge key={ur.role.id} role={ur.role} size="sm" />)}
            </div>
          )}
        </div>
      </div>

      {profile.bio && (
        <div style={{ fontSize: '14px', color: 'var(--text)', lineHeight: 1.6, marginBottom: '18px' }}>
          {profile.bio}
        </div>
      )}

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: '10px 20px',
        marginBottom: '20px',
        padding: '16px 18px',
        background: 'var(--bg-subtle)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
      }}>
        {profile.school && <InfoRow label="University" value={profile.school} />}
        {yearLabel && <InfoRow label="Year" value={yearLabel} />}
        {profile.majors?.length > 0 && <InfoRow label={profile.majors.length > 1 ? 'Majors' : 'Major'} value={profile.majors.join(', ')} />}
        {profile.minors?.length > 0 && <InfoRow label={profile.minors.length > 1 ? 'Minors' : 'Minor'} value={profile.minors.join(', ')} />}
        {profile.created_at && <InfoRow label="Joined" value={new Date(profile.created_at).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })} />}
        {profile.location && <InfoRow label="Location" value={profile.location} />}
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

      {profile.stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '20px' }}>
          {[
            { label: 'Streak', value: profile.stats.streak_count ?? 0 },
            { label: 'Sessions', value: profile.stats.session_count ?? 0 },
            { label: 'Documents', value: profile.stats.documents_count ?? 0 },
            { label: 'Achievements', value: profile.stats.achievements_count ?? 0 },
          ].map(stat => (
            <div key={stat.label} style={{
              background: 'var(--bg-subtle)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-md)',
              padding: '12px 10px',
              textAlign: 'center',
            }}>
              <div style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text)' }}>{stat.value}</div>
              <div style={{ fontSize: '10px', color: 'var(--text-dim)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: '2px' }}>{stat.label}</div>
            </div>
          ))}
        </div>
      )}

      {profile.featured_achievements?.length > 0 && (
        <div style={{ marginBottom: '20px' }}>
          <AchievementShowcase achievements={profile.featured_achievements} isOwnProfile />
        </div>
      )}

      {achievements && achievements.earned.length > 0 && (
        <div>
          <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', marginBottom: '10px' }}>
            Achievements ({achievements.earned.length})
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '8px' }}>
            {achievements.earned.map(ua => (
              <div key={ua.achievement.id} style={{
                padding: '10px 12px',
                background: 'var(--bg-subtle)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {ua.achievement.name}
                  </div>
                  {ua.achievement.description && (
                    <div style={{ fontSize: '10px', color: 'var(--text-dim)', marginTop: '1px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ua.achievement.description}
                    </div>
                  )}
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
