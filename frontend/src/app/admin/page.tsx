'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/context/UserContext';
import { useToast } from '@/components/ToastProvider';
import {
  adminFetchUsers, adminApproveUser, adminAssignRole, adminRevokeRole,
  adminCreateRole, adminCreateAchievement, adminGrantAchievement, adminCreateCosmetic,
} from '@/lib/api';
import RoleBadge from '@/components/RoleBadge';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const TABS = ['Users', 'Roles', 'Achievements', 'Cosmetics'];

export default function AdminPage() {
  const { isAdmin, userId } = useUser();
  const router = useRouter();
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState('Users');
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Role creation form
  const [roleName, setRoleName] = useState('');
  const [roleSlug, setRoleSlug] = useState('');
  const [roleColor, setRoleColor] = useState('#3b82f6');

  // Achievement creation form
  const [achName, setAchName] = useState('');
  const [achSlug, setAchSlug] = useState('');
  const [achCategory, setAchCategory] = useState('milestone');
  const [achRarity, setAchRarity] = useState('common');

  // Cosmetic creation form
  const [cosName, setCosName] = useState('');
  const [cosSlug, setCosSlug] = useState('');
  const [cosType, setCosType] = useState('avatar_frame');
  const [cosRarity, setCosRarity] = useState('common');

  // Grant form
  const [grantUserId, setGrantUserId] = useState('');
  const [grantAchId, setGrantAchId] = useState('');

  useEffect(() => {
    if (!isAdmin) {
      router.push('/dashboard');
      return;
    }
    setLoading(true);
    adminFetchUsers()
      .then(data => {
        setUsers(data.users || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [isAdmin, router]);

  if (!isAdmin) return null;

  const handleApprove = async (uid: string) => {
    try {
      await adminApproveUser(uid);
      setUsers(prev => prev.map(u => u.id === uid ? { ...u, is_approved: true } : u));
      showToast('User approved');
    } catch (e: any) {
      showToast(e.message);
    }
  };

  const handleCreateRole = async () => {
    if (!roleName || !roleSlug) return;
    try {
      await adminCreateRole({ name: roleName, slug: roleSlug, color: roleColor });
      showToast('Role created');
      setRoleName(''); setRoleSlug('');
    } catch (e: any) {
      showToast(e.message);
    }
  };

  const handleCreateAchievement = async () => {
    if (!achName || !achSlug) return;
    try {
      await adminCreateAchievement({ name: achName, slug: achSlug, category: achCategory, rarity: achRarity });
      showToast('Achievement created');
      setAchName(''); setAchSlug('');
    } catch (e: any) {
      showToast(e.message);
    }
  };

  const handleGrantAchievement = async () => {
    if (!grantUserId || !grantAchId) return;
    try {
      await adminGrantAchievement(grantUserId, grantAchId);
      showToast('Achievement granted');
      setGrantUserId(''); setGrantAchId('');
    } catch (e: any) {
      showToast(e.message);
    }
  };

  const handleCreateCosmetic = async () => {
    if (!cosName || !cosSlug) return;
    try {
      await adminCreateCosmetic({ type: cosType, name: cosName, slug: cosSlug, rarity: cosRarity });
      showToast('Cosmetic created');
      setCosName(''); setCosSlug('');
    } catch (e: any) {
      showToast(e.message);
    }
  };

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-input)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    padding: '6px 10px',
    fontSize: '13px',
    fontFamily: 'inherit',
    outline: 'none',
  };

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', padding: '24px 20px', fontFamily: UI_FONT }}>
      <h1 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '20px', color: 'var(--text)' }}>Admin</h1>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: '0', borderBottom: '1px solid var(--border)', marginBottom: '20px' }}>
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={activeTab === tab ? 'tab tab-active' : 'tab tab-inactive'}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Users tab */}
      {activeTab === 'Users' && (
        <div>
          {loading ? (
            <div style={{ color: 'var(--text-dim)', fontSize: '13px' }}>Loading users...</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  <th style={{ textAlign: 'left', padding: '8px 4px', fontWeight: 500, color: 'var(--text-dim)' }}>Name</th>
                  <th style={{ textAlign: 'left', padding: '8px 4px', fontWeight: 500, color: 'var(--text-dim)' }}>Email</th>
                  <th style={{ textAlign: 'left', padding: '8px 4px', fontWeight: 500, color: 'var(--text-dim)' }}>Status</th>
                  <th style={{ textAlign: 'left', padding: '8px 4px', fontWeight: 500, color: 'var(--text-dim)' }}>Roles</th>
                  <th style={{ textAlign: 'right', padding: '8px 4px', fontWeight: 500, color: 'var(--text-dim)' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map(user => (
                  <tr key={user.id} style={{ borderBottom: '1px solid var(--border-light)' }}>
                    <td style={{ padding: '8px 4px' }}>{user.name}</td>
                    <td style={{ padding: '8px 4px', color: 'var(--text-dim)' }}>{user.email}</td>
                    <td style={{ padding: '8px 4px' }}>
                      {user.is_approved ? (
                        <span style={{ color: 'var(--brand-success)', fontWeight: 500 }}>Approved</span>
                      ) : (
                        <span style={{ color: 'var(--brand-progress)', fontWeight: 500 }}>Pending</span>
                      )}
                    </td>
                    <td style={{ padding: '8px 4px' }}>
                      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        {(user.roles || []).map((r: any) => (
                          <RoleBadge key={r.id} role={r} size="sm" />
                        ))}
                      </div>
                    </td>
                    <td style={{ padding: '8px 4px', textAlign: 'right' }}>
                      {!user.is_approved && (
                        <button className="btn-accent" style={{ padding: '4px 10px', fontSize: '11px' }} onClick={() => handleApprove(user.id)}>
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Roles tab */}
      {activeTab === 'Roles' && (
        <div>
          <div style={{ marginBottom: '20px', fontSize: '14px', fontWeight: 600, color: 'var(--text)' }}>Create Role</div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '20px' }}>
            <input style={inputStyle} placeholder="Name" value={roleName} onChange={e => setRoleName(e.target.value)} />
            <input style={inputStyle} placeholder="Slug" value={roleSlug} onChange={e => setRoleSlug(e.target.value)} />
            <input type="color" value={roleColor} onChange={e => setRoleColor(e.target.value)} style={{ width: '36px', height: '32px', border: 'none', cursor: 'pointer' }} />
            <button className="btn-accent" onClick={handleCreateRole}>Create</button>
          </div>
        </div>
      )}

      {/* Achievements tab */}
      {activeTab === 'Achievements' && (
        <div>
          <div style={{ marginBottom: '20px' }}>
            <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', marginBottom: '10px' }}>Create Achievement</div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '12px' }}>
              <input style={inputStyle} placeholder="Name" value={achName} onChange={e => setAchName(e.target.value)} />
              <input style={inputStyle} placeholder="Slug" value={achSlug} onChange={e => setAchSlug(e.target.value)} />
              <select style={inputStyle} value={achCategory} onChange={e => setAchCategory(e.target.value)}>
                <option value="activity">Activity</option>
                <option value="social">Social</option>
                <option value="milestone">Milestone</option>
                <option value="special">Special</option>
              </select>
              <select style={inputStyle} value={achRarity} onChange={e => setAchRarity(e.target.value)}>
                <option value="common">Common</option>
                <option value="uncommon">Uncommon</option>
                <option value="rare">Rare</option>
                <option value="epic">Epic</option>
                <option value="legendary">Legendary</option>
              </select>
              <button className="btn-accent" onClick={handleCreateAchievement}>Create</button>
            </div>
          </div>
          <div>
            <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', marginBottom: '10px' }}>Grant Achievement</div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <input style={inputStyle} placeholder="User ID" value={grantUserId} onChange={e => setGrantUserId(e.target.value)} />
              <input style={inputStyle} placeholder="Achievement ID" value={grantAchId} onChange={e => setGrantAchId(e.target.value)} />
              <button className="btn-accent" onClick={handleGrantAchievement}>Grant</button>
            </div>
          </div>
        </div>
      )}

      {/* Cosmetics tab */}
      {activeTab === 'Cosmetics' && (
        <div>
          <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', marginBottom: '10px' }}>Create Cosmetic</div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <input style={inputStyle} placeholder="Name" value={cosName} onChange={e => setCosName(e.target.value)} />
            <input style={inputStyle} placeholder="Slug" value={cosSlug} onChange={e => setCosSlug(e.target.value)} />
            <select style={inputStyle} value={cosType} onChange={e => setCosType(e.target.value)}>
              <option value="avatar_frame">Avatar Frame</option>
              <option value="banner">Banner</option>
              <option value="name_color">Name Color</option>
              <option value="title">Title</option>
            </select>
            <select style={inputStyle} value={cosRarity} onChange={e => setCosRarity(e.target.value)}>
              <option value="common">Common</option>
              <option value="uncommon">Uncommon</option>
              <option value="rare">Rare</option>
              <option value="epic">Epic</option>
              <option value="legendary">Legendary</option>
            </select>
            <button className="btn-accent" onClick={handleCreateCosmetic}>Create</button>
          </div>
        </div>
      )}
    </div>
  );
}
