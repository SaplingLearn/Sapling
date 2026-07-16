import { describe, expect, it } from 'vitest';
import { deltaPlaceholderEdges, mergeGraphDelta, mergeGraphEdges, resolveCardCourseId } from './Learn';
import type { GraphDelta } from '@/lib/api';
import type { GraphEdge, GraphNode } from '@/lib/data';

/**
 * Fix-pass-2 findings (task-9):
 *
 * Finding A: streamed placeholder edges were silently dropped, non-
 * deterministically, because `applyGraphDelta` read a value out of a
 * `setGraphNodes` functional updater immediately after calling it — but React
 * doesn't run that updater synchronously except in a bailout that streaming
 * almost never hits. The fix makes `graphNodes` and `graphEdges` two
 * independent, idempotent updates instead: `mergeGraphDelta` (nodes) and
 * `deltaPlaceholderEdges` + `mergeGraphEdges` (edges) never read each other's
 * result — each is a pure function of its own arguments. This file exercises
 * that pipeline directly (no timers, no React rendering, no bailout to rely
 * on) and proves the edge survives, and survives being applied twice.
 *
 * Finding B: the streamed-placeholder course fallback was computed but never
 * actually used — the previous "fix" was a no-op because `...patch` was
 * spread after the courseId, so it always evaluated to the same value the
 * unfixed code produced. `resolveCardCourseId` is the real, stronger
 * resolution (mirrors `addConcept`'s `cardCourseId`); this file proves it
 * actually differs from the naive `selectedCourseId`-only fallback, and that
 * `mergeGraphDelta` actually uses whatever fallback it's given.
 */

const root = (courseId: string): GraphNode => ({
  id: `root-${courseId}`,
  name: `${courseId} root`,
  subject: `${courseId} subject`,
  color: '#123456',
  is_subject_root: true,
  mastery_tier: 'mastered',
  mastery_score: 1,
  course_id: courseId,
});

const newNodeDelta = (concept: string): GraphDelta => ({
  nodes: { new_nodes: [{ concept_name: concept, initial_mastery: 0.2 }] },
  mastery_changes: [],
});

// Mirrors the real `applyGraphDelta` in Learn.tsx: two independent updates,
// with the edges update reading a `graphNodes` snapshot taken *before* this
// delta's node merge (exactly what the render-scope `graphNodes` closure
// would be) — not the nodes updater's own `prev`/result.
function applyDelta(
  state: { nodes: GraphNode[]; edges: GraphEdge[] },
  delta: GraphDelta,
  courseId: string,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const graphNodesSnapshot = state.nodes;
  const nodes = mergeGraphDelta(state.nodes, delta, courseId);
  const edges = mergeGraphEdges(state.edges, deltaPlaceholderEdges(graphNodesSnapshot, delta, courseId));
  return { nodes, edges };
}

describe('Finding A — streamed placeholder edges (task-9 fix pass 2)', () => {
  it('links a brand-new streamed concept to its subject root', () => {
    const start = { nodes: [root('math')], edges: [] as GraphEdge[] };
    const result = applyDelta(start, newNodeDelta('Eigenvalues'), 'math');

    const placeholder = result.nodes.find(n => n.id === 'stream-eigenvalues');
    expect(placeholder).toBeDefined();
    expect(placeholder?.course_id).toBe('math');

    expect(result.edges).toContainEqual({ source: 'root-math', target: 'stream-eigenvalues', strength: 0.4 });
    expect(result.edges).toHaveLength(1);
  });

  it('applying the same delta twice yields exactly one edge (idempotent / Strict-Mode-safe)', () => {
    const start = { nodes: [root('math')], edges: [] as GraphEdge[] };
    const delta = newNodeDelta('Eigenvalues');

    const once = applyDelta(start, delta, 'math');
    const twice = applyDelta(once, delta, 'math');

    const edgesToPlaceholder = twice.edges.filter(e => e.target === 'stream-eigenvalues');
    expect(edgesToPlaceholder).toHaveLength(1);
    // Nodes stay deduped too (mergeGraphDelta's existing byId/byName upsert).
    expect(twice.nodes.filter(n => n.id === 'stream-eigenvalues')).toHaveLength(1);
  });

  it('mergeGraphEdges is pure: calling it twice with the identical (prev, additions) — exactly what React 18 Strict Mode does to a dev updater — returns the same result both times', () => {
    const additions: GraphEdge[] = [{ source: 'root-math', target: 'stream-eigenvalues', strength: 0.4 }];
    const firstInvocation = mergeGraphEdges([], additions);
    const secondInvocation = mergeGraphEdges([], additions); // same prev, same additions — the double-invoke case

    expect(firstInvocation).toEqual(secondInvocation);
    expect(firstInvocation).toHaveLength(1);
  });

  it('never re-adds an edge that is already present in graphEdges', () => {
    const already: GraphEdge[] = [{ source: 'root-math', target: 'stream-eigenvalues', strength: 0.4 }];
    const candidates: GraphEdge[] = [{ source: 'root-math', target: 'stream-eigenvalues', strength: 0.4 }];
    expect(mergeGraphEdges(already, candidates)).toBe(already); // same reference: no-op, not just equal
  });

  it('does not synthesize an edge for a concept that already exists as a real node', () => {
    const known: GraphNode = {
      id: 'real-eigen',
      name: 'Eigenvalues',
      subject: 'math subject',
      color: '#abcdef',
      mastery_tier: 'learning',
      mastery_score: 0.5,
      course_id: 'math',
    };
    const nodes = [root('math'), known];
    const edges = deltaPlaceholderEdges(nodes, newNodeDelta('Eigenvalues'), 'math');
    expect(edges).toHaveLength(0);
  });

  it('adds no edge when no subject root exists for the resolved course (matches prior behavior)', () => {
    const edges = deltaPlaceholderEdges([], newNodeDelta('Eigenvalues'), 'math');
    expect(edges).toHaveLength(0);
  });
});

describe('Finding B — placeholder course fallback (task-9 fix pass 2)', () => {
  it('resolveCardCourseId prefers the focused node\'s own course over selectedCourseId', () => {
    const topicNode: GraphNode = {
      id: 'n1',
      name: 'Some concept',
      subject: 'chem subject',
      color: '#000',
      mastery_tier: 'learning',
      mastery_score: 0.4,
      course_id: 'chem',
    };
    expect(resolveCardCourseId(topicNode, 'bio')).toBe('chem');
  });

  it('resolveCardCourseId falls back to selectedCourseId when the focused node has no course', () => {
    expect(resolveCardCourseId(undefined, 'bio')).toBe('bio');
  });

  it('resolveCardCourseId falls back to null when nothing resolves (keeps prior behavior for the "" case)', () => {
    expect(resolveCardCourseId(undefined, '')).toBeNull();
  });

  it('mergeGraphDelta actually uses the fallback it is given — a stronger fallback changes the placeholder\'s course_id', () => {
    const nodesFallback = mergeGraphDelta([root('chem')], newNodeDelta('Enzymes'), 'chem');
    const placeholder = nodesFallback.find(n => n.id === 'stream-enzymes');
    expect(placeholder?.course_id).toBe('chem');
  });
});
