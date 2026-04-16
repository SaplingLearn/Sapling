'use client';

import { useState, useEffect } from 'react';
import { fetchCosmetics, equipCosmetic } from '@/lib/api';
import { useUser } from '@/context/UserContext';
import type { CosmeticType, UserCosmetic } from '@/lib/types';
import AvatarFrame from '@/components/AvatarFrame';
import NameColorRenderer from '@/components/NameColorRenderer';
import TitleFlair from '@/components/TitleFlair';

interface Props {
  userId: string;
}

const TABS: { key: CosmeticType; label: string }[] = [
  { key: 'avatar_frame', label: 'Avatar Frames' },
  { key: 'banner', label: 'Banners' },
  { key: 'name_color', label: 'Name Colors' },
  { key: 'title', label: 'Titles' },
];

export default function CosmeticsManager({ userId }: Props) {
  const { userName, avatarUrl, equippedCosmetics, refreshProfile } = useUser();
  const [activeTab, setActiveTab] = useState<CosmeticType>('avatar_frame');
  const [cosmetics, setCosmetics] = useState<Record<CosmeticType, UserCosmetic[]>>({
    avatar_frame: [], banner: [], name_color: [], title: [],
  });
  const [equipped, setEquipped] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [equipping, setEquipping] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchCosmetics(userId)
      .then(data => {
        setCosmetics(data.cosmetics as Record<CosmeticType, UserCosmetic[]>);
        setEquipped(data.equipped);
        setLoading(false);
      })
      .catch(e => {
        setError(e.message);
        setLoading(false);
      });
  }, [userId]);

  const handleEquip = async (slot: CosmeticType, cosmeticId: string | null) => {
    setEquipping(true);
    try {
      await equipCosmetic(userId, slot, cosmeticId);
      await refreshProfile();
      // Refresh cosmetics data
      const data = await fetchCosmetics(userId);
      setCosmetics(data.cosmetics as Record<CosmeticType, UserCosmetic[]>);
      setEquipped(data.equipped);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setEquipping(false);
    }
  };

  const isEquipped = (slot: CosmeticType, cosmeticId: string) => {
    const eq = equipped[slot];
    return eq?.id === cosmeticId;
  };

  if (loading) {
    return <div style={{ color: 'var(--text-dim)', fontSize: '13px', padding: '20px 0' }}>Loading cosmetics...</div>;
  }

  if (error) {
    return <div style={{ color: 'var(--brand-struggle)', fontSize: '13px', padding: '20px 0' }}>{error}</div>;
  }

  const currentItems = cosmetics[activeTab] || [];

  return (
    <div>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: '0', borderBottom: '1px solid var(--border)', marginBottom: '16px' }}>
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={activeTab === tab.key ? 'tab tab-active' : 'tab tab-inactive'}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
        gap: '10px',
        marginBottom: '20px',
      }}>
        {currentItems.map(uc => {
          const c = uc.cosmetic;
          const active = isEquipped(activeTab, c.id);
          return (
            <button
              key={c.id}
              disabled={equipping}
              onClick={() => handleEquip(activeTab, active ? null : c.id)}
              className="cosmetic-equipped"
              style={{
                background: 'var(--bg-panel)',
                border: active ? '2px solid var(--accent)' : '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                padding: '10px',
                cursor: equipping ? 'not-allowed' : 'pointer',
                textAlign: 'center',
                fontSize: '12px',
                fontFamily: 'inherit',
                color: 'var(--text)',
                opacity: equipping ? 0.6 : 1,
              }}
            >
              {c.asset_url && (
                <img src={c.asset_url} alt={c.name} style={{ width: '40px', height: '40px', objectFit: 'contain', marginBottom: '6px' }} />
              )}
              <div style={{ fontWeight: 500 }}>{c.name}</div>
              <div style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>{c.rarity}</div>
              {active && <div style={{ fontSize: '10px', color: 'var(--accent)', fontWeight: 600, marginTop: '4px' }}>Equipped</div>}
            </button>
          );
        })}
        {currentItems.length === 0 && (
          <div style={{ gridColumn: '1 / -1', color: 'var(--text-dim)', fontSize: '13px', padding: '20px 0', textAlign: 'center' }}>
            No {TABS.find(t => t.key === activeTab)?.label.toLowerCase()} unlocked yet
          </div>
        )}
      </div>

      {/* Preview */}
      <div style={{
        background: 'var(--bg-subtle)',
        borderRadius: 'var(--radius-md)',
        padding: '16px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
      }}>
        <AvatarFrame
          userId={userId}
          name={userName}
          size={48}
          avatarUrl={avatarUrl}
          frameUrl={equippedCosmetics?.avatar_frame?.asset_url}
        />
        <div>
          <NameColorRenderer
            name={userName || 'Your Name'}
            cssValue={equippedCosmetics?.name_color?.css_value}
          />
          {equippedCosmetics?.title && (
            <div style={{ marginTop: '2px' }}>
              <TitleFlair
                title={equippedCosmetics.title.name}
                rarity={equippedCosmetics.title.rarity}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
