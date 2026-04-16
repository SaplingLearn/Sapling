'use client';

interface Props {
  bannerUrl?: string;
}

export default function ProfileBanner({ bannerUrl }: Props) {
  if (bannerUrl) {
    return (
      <div style={{
        width: '100%',
        height: '160px',
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
      }}>
        <img
          src={bannerUrl}
          alt=""
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
          }}
        />
      </div>
    );
  }

  return (
    <div style={{
      width: '100%',
      height: '160px',
      borderRadius: 'var(--radius-md)',
      background: 'linear-gradient(135deg, var(--accent-dim) 0%, var(--bg-subtle) 100%)',
    }} />
  );
}
