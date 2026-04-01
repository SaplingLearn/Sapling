'use client';

import React, { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px 24px',
          textAlign: 'center',
          minHeight: '300px',
          fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
        }}>
          <p style={{ fontSize: '15px', fontWeight: 600, color: '#111827', marginBottom: '8px' }}>
            Something went wrong
          </p>
          <p style={{ fontSize: '13px', color: '#6b7280', marginBottom: '20px', maxWidth: '400px', lineHeight: 1.6 }}>
            {this.state.error?.message || 'An unexpected error occurred.'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              padding: '8px 20px',
              background: 'rgba(26,92,42,0.08)',
              color: '#1a5c2a',
              border: '1px solid rgba(26,92,42,0.3)',
              borderRadius: '7px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Try Again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
