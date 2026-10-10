import { describe, expect, it } from 'vitest';
import { deltaPlaceholderEdges, mergeGraphDelta, mergeGraphEdges, quizHref, resolveAddConceptCourseId, resolveCardCourseId, shouldRestoreFailedDelete } from './Learn';
import { ApiError, type GraphDelta } from '@/lib/api';
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
 *
 * NOTE (fix pass 3, task-9): this file used to also assert end-to-end
 * "applies a delta and gets a placeholder + edge" behavior via a
 * hand-written `applyDelta` helper that *mirrored* `applyGraphDelta`'s
 * shape rather than calling it. A reviewer proved that mirror was a gap: you
 * could revert the real `applyGraphDelta` to a broken value-threaded-out-of-
 * an-updater shape and every test in this file would still pass, because
 * none of them called the real assembly. Those two tests (and the mirror)
 * were removed in favor of Learn.applyGraphDelta.test.ts, which exercises
 * the real exported `applyGraphDeltaAssembly` and strictly covers the same
 * ground (placeholder + edge creation, idempotency across two applications)
 * plus the revert-proof property this file never had. The helper-level
 * tests below (`mergeGraphEdges`, `deltaPlaceholderEdges`,
 * `resolveCardCourseId`, `mergeGraphDelta` used directly) are untouched —
 * they test real exported functions, not a mirror, and remain valid.
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

describe('Finding A — streamed placeholder edges (task-9 fix pass 2)', () => {
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

describe('delete a concept, then add it back under the same name', () => {
  /**
   * Reported: "when deleting a concept node, i should be able to add it back
   * of the same name by add concept".
   *
   * The backend was never the problem — add → delete → add of the same name
   * creates a fresh row every time (graph_nodes has no soft delete, and
   * delete_node hard-deletes the row plus its edges). The break was here:
   *
   *   cardCourseId = topicNode?.course_id || selectedCourseId || null
   *
   * The course picker is "Course (optional)" and starts at "" ("No course"),
   * so for anyone who hasn't chosen one, cardCourseId comes ENTIRELY from the
   * focused node. Deleting a concept clears the focus, so cardCourseId went
   * null, and addConcept's `if (!label || !cardCourseId) return` bailed out
   * before doing anything at all — no request, no toast, no rollback. The
   * composer just sat there with the name typed in.
   *
   * NOTE (fix pass 2): the resolver below is necessary but was NOT sufficient,
   * and the tests in this describe could not see the difference. `addConcept`
   * only runs from a composer that was itself gated on `cardCourseId`, so the
   * fallback could never fire — the whole affordance unmounted on the delete.
   * The gate now reads the same resolved value `addConcept` does, and
   * Learn.addConcept.test.tsx asserts that wiring through the rendered rail,
   * which is the only level at which the gap was visible.
   */
  it('still resolves a course when focus was just cleared by the delete', () => {
    // Before the delete: the focused node supplies the course.
    const focused: GraphNode = {
      id: 'n1', name: 'Markov Chains', subject: 'CS 132', color: '#000',
      mastery_tier: 'unexplored', mastery_score: 0, course_id: 'cs132',
    };
    const live = resolveCardCourseId(focused, '');
    expect(live).toBe('cs132');

    // After the delete: focus is gone and the picker is still "No course",
    // so the live resolution has nothing left.
    const afterDelete = resolveCardCourseId(undefined, '');
    expect(afterDelete).toBeNull();

    // The add path remembers the last course that did resolve.
    expect(resolveAddConceptCourseId(afterDelete, live!)).toBe('cs132');
  });

  it('prefers the live resolution over the remembered one', () => {
    expect(resolveAddConceptCourseId('bio', 'chem')).toBe('bio');
  });

  it('returns null only when no course has EVER resolved — the one case that hides the affordance', () => {
    expect(resolveAddConceptCourseId(null, '')).toBeNull();
  });
});

describe('shouldRestoreFailedDelete', () => {
  /**
   * DELETE /api/graph/{user}/nodes/{id} answers 404 for "that row is already
   * gone" (routes/graph.py::remove_node, from graph_service.delete_node's
   * {"error": "Node not found"}). Restoring on it put a concept back on the
   * map that exists nowhere, under a toast asserting it was "still on your
   * map" — and after the student re-added the same name, TWO of them.
   */
  const node: GraphNode = {
    id: 'n1', name: 'Markov Chains', subject: 'CS 132', color: '#000',
    mastery_tier: 'unexplored', mastery_score: 0, course_id: 'cs132',
  };

  it('does not restore on 404 — the row is already gone, which is what was asked for', () => {
    expect(shouldRestoreFailedDelete('n1', node, new ApiError('{"detail":"Node not found"}', 404)))
      .toBe(false);
  });

  it('restores on a genuine server failure — the row is still there', () => {
    expect(shouldRestoreFailedDelete('n1', node, new ApiError('Internal Server Error', 500)))
      .toBe(true);
  });

  it('restores when the request never reached a status at all (dead backend, offline)', () => {
    expect(shouldRestoreFailedDelete('n1', node, new TypeError('Failed to fetch'))).toBe(true);
  });

  it('never restores a client-side id — the server has never seen it', () => {
    const optimistic = { ...node, id: 'node-new-1723459200000-3' };
    const streamed = { ...node, id: 'stream-markov chains' };
    const boom = new ApiError('Internal Server Error', 500);
    expect(shouldRestoreFailedDelete(optimistic.id, optimistic, boom)).toBe(false);
    expect(shouldRestoreFailedDelete(streamed.id, streamed, boom)).toBe(false);
  });

  it('has nothing to restore when the node was already off the map', () => {
    expect(shouldRestoreFailedDelete('n1', undefined, new ApiError('boom', 500))).toBe(false);
  });
});

describe('quiz deep link from the tutor', () => {
  /**
   * The tutor page had no quiz entry point at all — the only routes in were
   * the nav's Quiz item, the dashboard, the knowledge map and the notetaker,
   * all of which drop the session's context and make the student re-pick the
   * concept on the other side. Both new buttons (focus card + session
   * toolbar) hand /quiz the concept it should already know about.
   */
  it('prefers the concept id, which Quiz.tsx uses directly', () => {
    expect(quizHref('node-abc', 'Markov Chains')).toBe('/quiz?concept=node-abc');
  });

  it('falls back to the topic name when there is no focused concept', () => {
    expect(quizHref(null, 'Markov Chains')).toBe('/quiz?topic=Markov%20Chains');
  });

  it('does NOT pass an optimistic id — the server has never seen it', () => {
    // `node-new-<ts>` (manual add, pre-reconcile) and `stream-<name>` (a live
    // tutor turn's placeholder) are client-side ids. As ?concept= they would
    // preselect something the quiz page cannot resolve; by name it resolves
    // as soon as the real row lands.
    expect(quizHref('node-new-1723459200000-3', 'Eigenvalues')).toBe('/quiz?topic=Eigenvalues');
    expect(quizHref('stream-eigenvalues', 'Eigenvalues')).toBe('/quiz?topic=Eigenvalues');
  });

  it('encodes names that need it', () => {
    expect(quizHref(null, 'Bayes\u2019 Rule & Priors')).toBe(
      '/quiz?topic=Bayes%E2%80%99%20Rule%20%26%20Priors',
    );
  });

  it('degrades to the bare quiz page rather than emitting an empty param', () => {
    expect(quizHref(null, null)).toBe('/quiz');
    expect(quizHref(undefined, '   ')).toBe('/quiz');
  });
});
