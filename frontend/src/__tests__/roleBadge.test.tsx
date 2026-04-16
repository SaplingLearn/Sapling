/**
 * Tests for components/RoleBadge.tsx
 *
 * Covers: name rendering, size variants, icon rendering,
 * description tooltip, color styling.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import RoleBadge from '@/components/RoleBadge';
import type { Role } from '@/lib/types';

const baseRole: Role = {
  id: 'r1',
  name: 'Admin',
  slug: 'admin',
  color: '#ff0000',
  icon: null,
  description: 'Administrator role',
  is_staff_assigned: true,
  is_earnable: false,
  display_priority: 100,
};

afterEach(() => jest.clearAllMocks());

describe('RoleBadge', () => {
  it('renders role name', () => {
    render(<RoleBadge role={baseRole} />);
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });

  it('sets title attribute from description', () => {
    render(<RoleBadge role={baseRole} />);
    expect(screen.getByText('Admin').closest('span')).toHaveAttribute('title', 'Administrator role');
  });

  it('does not set title when no description', () => {
    const role = { ...baseRole, description: '' };
    render(<RoleBadge role={role} />);
    const span = screen.getByText('Admin').closest('span');
    expect(span?.getAttribute('title')).toBeFalsy();
  });

  it('renders icon when present', () => {
    const role = { ...baseRole, icon: 'https://example.com/icon.png' };
    render(<RoleBadge role={role} />);
    const img = screen.getByRole('presentation');
    expect(img).toHaveAttribute('src', 'https://example.com/icon.png');
  });

  it('does not render img when no icon', () => {
    render(<RoleBadge role={baseRole} />);
    expect(screen.queryByRole('presentation')).not.toBeInTheDocument();
  });

  it('uses smaller font for sm size', () => {
    const { container } = render(<RoleBadge role={baseRole} size="sm" />);
    const span = container.querySelector('span')!;
    expect(span.style.fontSize).toBe('10px');
  });

  it('uses default md size font', () => {
    const { container } = render(<RoleBadge role={baseRole} />);
    const span = container.querySelector('span')!;
    expect(span.style.fontSize).toBe('11px');
  });

  it('applies role color to text', () => {
    const { container } = render(<RoleBadge role={baseRole} />);
    const span = container.querySelector('span')!;
    expect(span.style.color).toBe('rgb(255, 0, 0)');
  });
});
