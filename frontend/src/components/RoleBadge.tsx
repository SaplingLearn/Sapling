'use client';

import type { Role } from '@/lib/types';

interface Props {
  role: Role;
  size?: 'sm' | 'md';
}

export default function RoleBadge({ role, size = 'md' }: Props) {
  const isSm = size === 'sm';

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: isSm ? '1px 6px' : '2px 8px',
        borderRadius: 'var(--radius-full)',
        fontSize: isSm ? '10px' : '11px',
        fontWeight: 600,
        fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
        letterSpacing: '0.02em',
        background: `color-mix(in srgb, ${role.color} 10%, transparent)`,
        color: role.color,
        border: `1px solid color-mix(in srgb, ${role.color} 25%, transparent)`,
        position: 'relative',
        cursor: role.description ? 'default' : undefined,
        // @ts-ignore
        '--role-color': role.color,
      } as React.CSSProperties}
      title={role.description || undefined}
    >
      {role.icon && (
        <img
          src={role.icon}
          alt=""
          style={{ width: isSm ? '10px' : '12px', height: isSm ? '10px' : '12px' }}
        />
      )}
      {role.name}
    </span>
  );
}
