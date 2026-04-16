'use client';

interface Props {
  name: string;
  cssValue?: string;
}

export default function NameColorRenderer({ name, cssValue }: Props) {
  if (!cssValue) {
    return (
      <span style={{ color: 'var(--text)' }}>{name}</span>
    );
  }

  if (cssValue.includes('gradient')) {
    return (
      <span style={{
        background: cssValue,
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundClip: 'text',
        color: 'transparent',
      }}>
        {name}
      </span>
    );
  }

  return (
    <span style={{ color: cssValue }}>{name}</span>
  );
}
