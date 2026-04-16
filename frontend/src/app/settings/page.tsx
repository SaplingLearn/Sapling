'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useUser } from '@/context/UserContext';
import { useToast } from '@/components/ToastProvider';
import {
  fetchSettings, updateSettings, updateProfile, uploadAvatar,
  exportData, deleteAccount,
} from '@/lib/api';
import type { UserSettings } from '@/lib/types';
import AvatarFrame from '@/components/AvatarFrame';
import CosmeticsManager from '@/components/CosmeticsManager';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const SECTIONS = [
  { key: 'profile', label: 'Profile' },
  { key: 'account', label: 'Account' },
  { key: 'notifications', label: 'Notifications' },
  { key: 'appearance', label: 'Appearance' },
  { key: 'privacy', label: 'Privacy' },
  { key: 'cosmetics', label: 'Cosmetics' },
  { key: 'danger', label: 'Danger Zone' },
];

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      onClick={() => !disabled && onChange(!checked)}
      style={{
        width: '36px',
        height: '20px',
        borderRadius: 'var(--radius-full)',
        background: checked ? 'var(--accent)' : 'var(--bg-subtle)',
        border: `1px solid ${checked ? 'var(--accent)' : 'var(--border-mid)'}`,
        position: 'relative',
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'background var(--dur-fast)',
        padding: 0,
        opacity: disabled ? 0.4 : 1,
      }}
    >
      <div style={{
        width: '14px',
        height: '14px',
        borderRadius: '50%',
        background: '#fff',
        position: 'absolute',
        top: '2px',
        left: checked ? '18px' : '2px',
        transition: 'left var(--dur-fast)',
        boxShadow: '0 1px 2px rgba(0,0,0,0.15)',
      }} />
    </button>
  );
}

export default function SettingsPage() {
  const { userId, userName, avatarUrl, equippedCosmetics, refreshProfile } = useUser();
  const { showToast } = useToast();
  const [activeSection, setActiveSection] = useState('profile');
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

  // Username availability check with debounce
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
      <div style={{ maxWidth: '800px', margin: '40px auto', padding: '0 20px', fontFamily: UI_FONT }}>
        <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>Loading settings...</div>
      </div>
    );
  }

  const inputStyle: React.CSSProperties = {
    width: '100%',
    background: 'var(--bg-input)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    padding: '8px 10px',
    fontSize: '13px',
    fontFamily: 'inherit',
    outline: 'none',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: '12px',
    fontWeight: 500,
    color: 'var(--text-secondary)',
    marginBottom: '4px',
    display: 'block',
  };

  const sectionTitleStyle: React.CSSProperties = {
    fontSize: '15px',
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: '16px',
  };

  const settingRowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 0',
    borderBottom: '1px solid var(--border-light)',
  };

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto', padding: '24px 20px', fontFamily: UI_FONT }}>
      <h1 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '24px', color: 'var(--text)' }}>Settings</h1>

      <div style={{ display: 'flex', gap: '32px' }}>
        {/* Sidebar */}
        <nav style={{ minWidth: '140px', flexShrink: 0 }}>
          {SECTIONS.map(s => (
            <button
              key={s.key}
              onClick={() => setActiveSection(s.key)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '6px 10px',
                borderRadius: 'var(--radius-sm)',
                fontSize: '13px',
                fontFamily: 'inherit',
                fontWeight: activeSection === s.key ? 600 : 400,
                color: activeSection === s.key ? 'var(--accent)' : 'var(--text-muted)',
                background: activeSection === s.key ? 'var(--accent-dim)' : 'transparent',
                border: 'none',
                cursor: 'pointer',
                marginBottom: '2px',
                transition: 'background var(--dur-fast)',
              }}
            >
              {s.label}
            </button>
          ))}
        </nav>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Profile */}
          {activeSection === 'profile' && (
            <div>
              <div style={sectionTitleStyle}>Profile</div>
              <div style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                <AvatarFrame
                  userId={userId}
                  name={userName}
                  size={56}
                  avatarUrl={avatarUrl}
                  frameUrl={equippedCosmetics?.avatar_frame?.asset_url}
                />
                <label style={{
                  ...inputStyle,
                  width: 'auto',
                  cursor: 'pointer',
                  textAlign: 'center',
                  padding: '6px 14px',
                  color: 'var(--accent)',
                  border: '1px solid var(--accent-border)',
                  background: 'var(--accent-dim)',
                }}>
                  Change avatar
                  <input type="file" accept="image/*" onChange={handleAvatarUpload} style={{ display: 'none' }} />
                </label>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div>
                  <label style={labelStyle}>Display name</label>
                  <input style={inputStyle} value={displayName} onChange={e => setDisplayName(e.target.value)} />
                </div>
                <div>
                  <label style={labelStyle}>Username</label>
                  <input
                    style={inputStyle}
                    value={username}
                    onChange={e => { setUsername(e.target.value); checkUsername(e.target.value); }}
                    placeholder="your-username"
                  />
                  {checkingUsername && <span style={{ fontSize: '11px', color: 'var(--text-dim)' }}>Checking...</span>}
                  {usernameAvailable === true && <span style={{ fontSize: '11px', color: 'var(--brand-success)' }}>Available</span>}
                  {usernameAvailable === false && <span style={{ fontSize: '11px', color: 'var(--brand-struggle)' }}>Taken</span>}
                </div>
                <div>
                  <label style={labelStyle}>Bio</label>
                  <textarea
                    style={{ ...inputStyle, minHeight: '60px', resize: 'vertical' }}
                    value={bio}
                    onChange={e => setBio(e.target.value)}
                    placeholder="Tell us about yourself"
                  />
                </div>
                <div>
                  <label style={labelStyle}>Location</label>
                  <input style={inputStyle} value={location} onChange={e => setLocation(e.target.value)} placeholder="City, State" />
                </div>
                <div>
                  <label style={labelStyle}>Website</label>
                  <input style={inputStyle} value={website} onChange={e => setWebsite(e.target.value)} placeholder="https://yoursite.com" />
                </div>
              </div>
              <button className="btn-accent" onClick={saveProfile} style={{ marginTop: '16px' }}>Save profile</button>
            </div>
          )}

          {/* Account */}
          {activeSection === 'account' && (
            <div>
              <div style={sectionTitleStyle}>Account</div>
              <div style={{ ...settingRowStyle, borderBottom: 'none' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text)' }}>Email</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-dim)' }}>Managed by your Google account</div>
                </div>
              </div>
              <div style={{
                padding: '12px',
                background: 'var(--bg-subtle)',
                borderRadius: 'var(--radius-md)',
                fontSize: '13px',
                color: 'var(--text-muted)',
              }}>
                Signed in with Google — password management is handled by your Google account.
              </div>
            </div>
          )}

          {/* Notifications */}
          {activeSection === 'notifications' && (
            <div>
              <div style={sectionTitleStyle}>Notifications</div>
              <div style={settingRowStyle}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 500 }}>Email notifications</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-dim)' }}>Receive updates via email</div>
                </div>
                <Toggle checked={settings?.notification_email ?? true} onChange={v => saveSettings({ notification_email: v })} />
              </div>
              <div style={settingRowStyle}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 500 }}>In-app notifications</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-dim)' }}>Show notifications within the app</div>
                </div>
                <Toggle checked={settings?.notification_in_app ?? true} onChange={v => saveSettings({ notification_in_app: v })} />
              </div>
              <div style={settingRowStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 500 }}>Push notifications</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-dim)' }}>Browser push notifications</div>
                  </div>
                  <span className="badge" style={{ fontSize: '10px', padding: '1px 6px' }}>Coming soon</span>
                </div>
                <Toggle checked={false} onChange={() => {}} disabled />
              </div>
            </div>
          )}

          {/* Appearance */}
          {activeSection === 'appearance' && (
            <div>
              <div style={sectionTitleStyle}>Appearance</div>
              <div style={settingRowStyle}>
                <div style={{ fontSize: '13px', fontWeight: 500 }}>Theme</div>
                <div style={{ display: 'flex', gap: '4px' }}>
                  {['light', 'dark'].map(t => (
                    <button
                      key={t}
                      onClick={() => handleThemeToggle(t)}
                      className={settings?.theme === t ? 'pill pill-active' : 'pill pill-inactive'}
                    >
                      {t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div style={settingRowStyle}>
                <div style={{ fontSize: '13px', fontWeight: 500 }}>Font size</div>
                <div style={{ display: 'flex', gap: '4px' }}>
                  {['small', 'medium', 'large'].map(s => (
                    <button
                      key={s}
                      onClick={() => saveSettings({ font_size: s })}
                      className={settings?.font_size === s ? 'pill pill-active' : 'pill pill-inactive'}
                    >
                      {s.charAt(0).toUpperCase() + s.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div style={settingRowStyle}>
                <div style={{ fontSize: '13px', fontWeight: 500 }}>Accent color</div>
                <input
                  type="color"
                  value={settings?.accent_color || '#1a5c2a'}
                  onChange={e => {
                    document.documentElement.style.setProperty('--accent', e.target.value);
                    saveSettings({ accent_color: e.target.value });
                  }}
                  style={{ width: '32px', height: '32px', border: 'none', background: 'none', cursor: 'pointer' }}
                />
              </div>
            </div>
          )}

          {/* Privacy */}
          {activeSection === 'privacy' && (
            <div>
              <div style={sectionTitleStyle}>Privacy</div>
              <div style={settingRowStyle}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 500 }}>Profile visibility</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-dim)' }}>Control who can see your profile details</div>
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                  {['public', 'private'].map(v => (
                    <button
                      key={v}
                      onClick={() => saveSettings({ profile_visibility: v })}
                      className={settings?.profile_visibility === v ? 'pill pill-active' : 'pill pill-inactive'}
                    >
                      {v.charAt(0).toUpperCase() + v.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div style={settingRowStyle}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 500 }}>Activity status</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-dim)' }}>Show when you are active</div>
                </div>
                <Toggle
                  checked={settings?.activity_status_visible ?? true}
                  onChange={v => saveSettings({ activity_status_visible: v })}
                />
              </div>
            </div>
          )}

          {/* Cosmetics */}
          {activeSection === 'cosmetics' && (
            <div>
              <div style={sectionTitleStyle}>Cosmetics</div>
              <CosmeticsManager userId={userId} />
            </div>
          )}

          {/* Danger Zone */}
          {activeSection === 'danger' && (
            <div>
              <div style={{ ...sectionTitleStyle, color: 'var(--brand-struggle)' }}>Danger Zone</div>
              <div style={{
                border: '1px solid rgba(220,38,38,0.2)',
                borderRadius: 'var(--radius-md)',
                padding: '16px',
              }}>
                <div style={{ marginBottom: '16px' }}>
                  <button className="btn-ghost" onClick={handleExport}>Export my data</button>
                </div>
                <div>
                  <button
                    onClick={() => setShowDeleteForm(!showDeleteForm)}
                    style={{
                      background: 'rgba(220,38,38,0.08)',
                      color: '#dc2626',
                      border: '1px solid rgba(220,38,38,0.25)',
                      borderRadius: 'var(--radius-md)',
                      padding: '8px 16px',
                      fontSize: '13px',
                      fontWeight: 500,
                      fontFamily: 'inherit',
                      cursor: 'pointer',
                    }}
                  >
                    Delete account
                  </button>
                  {showDeleteForm && (
                    <div style={{ marginTop: '12px' }}>
                      <p style={{ fontSize: '12px', color: 'var(--text-dim)', marginBottom: '8px' }}>
                        This will schedule your account for deletion. You have 30 days to change your mind. Type DELETE to confirm.
                      </p>
                      <input
                        style={{ ...inputStyle, marginBottom: '8px' }}
                        value={deleteConfirm}
                        onChange={e => setDeleteConfirm(e.target.value)}
                        placeholder="Type DELETE to confirm"
                      />
                      <button
                        onClick={handleDeleteAccount}
                        disabled={deleteConfirm !== 'DELETE' || deleting}
                        style={{
                          background: deleteConfirm === 'DELETE' ? '#dc2626' : 'var(--bg-subtle)',
                          color: deleteConfirm === 'DELETE' ? '#fff' : 'var(--text-dim)',
                          border: 'none',
                          borderRadius: 'var(--radius-sm)',
                          padding: '8px 16px',
                          fontSize: '13px',
                          fontFamily: 'inherit',
                          cursor: deleteConfirm === 'DELETE' && !deleting ? 'pointer' : 'not-allowed',
                        }}
                      >
                        {deleting ? 'Deleting...' : 'Confirm deletion'}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
