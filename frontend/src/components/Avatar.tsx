import { getInitials, getAvatarColor } from '@/lib/avatarUtils';

interface Props {
  userId: string;
  name: string;
  size?: number;
  avatarUrl?: string;
  className?: string;
}

export default function Avatar({ userId, name, size = 32, avatarUrl, className }: Props) {
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={name}
        referrerPolicy="no-referrer"
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          objectFit: 'cover',
          flexShrink: 0,
        }}
      />
    );
  }
  return (
    <div style={{
      width: size,
      height: size,
      borderRadius: '50%',
      background: getAvatarColor(userId),
      color: '#fff',
      fontSize: Math.max(10, Math.floor(size * 0.33)),
      fontWeight: 600,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
    }}>
      {getInitials(name)}
    </div>
  );
}
