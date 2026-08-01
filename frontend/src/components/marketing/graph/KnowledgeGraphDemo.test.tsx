// @vitest-environment jsdom
/**
 * The parked frame is the contract. Reduced-motion visitors and the E2E lane
 * both get this render, so "parked" has to mean laid out and readable — not
 * blank and not mid-assembly.
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import KnowledgeGraphDemo from './KnowledgeGraphDemo';
import { COURSE_GRAPHS } from './courseGraphs';

afterEach(cleanup);

describe('KnowledgeGraphDemo', () => {
  it('renders a chip per course, with the first selected', () => {
    render(<KnowledgeGraphDemo />);
    for (const g of COURSE_GRAPHS) {
      expect(screen.getByTestId(`landing-graph-chip-${g.id}`)).toBeInTheDocument();
    }
    expect(
      screen.getByTestId(`landing-graph-chip-${COURSE_GRAPHS[0].id}`),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('renders the selected course graph fully laid out', () => {
    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];
    for (const n of g.nodes) {
      expect(screen.getByTestId(`landing-graph-node-${n.id}`)).toBeInTheDocument();
    }
  });

  it('swaps the graph when another chip is picked', () => {
    render(<KnowledgeGraphDemo />);
    const target = COURSE_GRAPHS[1];
    fireEvent.click(screen.getByTestId(`landing-graph-chip-${target.id}`));

    expect(screen.getByTestId(`landing-graph-node-${target.nodes[0].id}`)).toBeInTheDocument();
    expect(
      screen.queryByTestId(`landing-graph-node-${COURSE_GRAPHS[0].nodes[0].id}`),
    ).not.toBeInTheDocument();
  });

  it('labels the section for assistive tech', () => {
    render(<KnowledgeGraphDemo />);
    expect(screen.getByTestId('landing-graph')).toHaveAttribute('aria-label');
  });
});
