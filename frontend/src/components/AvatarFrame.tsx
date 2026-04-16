'use client';

import Avatar from '@/components/Avatar';

interface Props {
  frameUrl?: string;
  frameSlug?: string;
  userId: string;
  name: string;
  size?: number;
  avatarUrl?: string;
  className?: string;
}

export default function AvatarFrame({ frameUrl, frameSlug, userId, name, size = 32, avatarUrl, className }: Props) {
  if (!frameUrl) {
    return <Avatar userId={userId} name={name} size={size} avatarUrl={avatarUrl} className={className} />;
  }

  return (
    <div
      className={className}
      style={{
        position: 'relative',
        width: size,
        height: size,
        flexShrink: 0,
      }}
    >
      <Avatar userId={userId} name={name} size={size} avatarUrl={avatarUrl} />
      <img
        src={frameUrl}
        alt=""
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          pointerEvents: 'none',
          objectFit: 'contain',
        }}
      />
    </div>
  );
}
