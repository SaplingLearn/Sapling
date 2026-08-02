import { describe, expect, it } from 'vitest';
import { applyGraphDeltaAssembly } from './Learn';
import type { GraphDelta } from '@/lib/api';
import type { GraphEdge, GraphNode } from '@/lib/data';

/**
 * Fix pass 3 (task-9): covers `applyGraphDelta`'s CALL SITE, not just its
 * already-extracted helpers.
 *
 * Learn.graph.test.ts (fix pass 2) proved `mergeGraphDelta`,
 * `deltaPlaceholderEdges`, and `mergeGraphEdges` are individually correct,
 * but two of its tests drove a hand-written `applyDelta` helper that
 * *mirrored* the real `applyGraphDelta` assembly rather than calling it —
 * its own comment admitted as much. A reviewer proved this was a real gap:
 * you could revert `applyGraphDelta` to the old broken "thread a value out
 * of a functional updater, then read it synchronously right after" shape
 * and all of fix pass 2's tests would still pass, because none of them
 * called the real assembly. Those two tests (and the mirror) were removed;
 * see the NOTE at the top of Learn.graph.test.ts.
 *
 * This file exercises `applyGraphDeltaAssembly` — the actual body of
 * `applyGraphDelta`'s useCallback, extracted to a standalone exported
 * function that takes `setGraphNodes`/`setGraphEdges` as parameters so it
 * is callable outside React (see Learn.tsx). `LearnInner` calls this exact
 * function with its real `setGraphNodes`/`setGraphEdges` state setters — no
 * second copy of the assembly logic exists anywhere.
 *
 * The fake setters below never invoke the updater function they are given
 * — they only *capture* it, then `flush` applies it later against a chosen
 * `prev`. This matches real React precisely: a functional `setState`
 * updater is never guaranteed to run synchronously at the call site (per
 * the comment on `applyGraphDeltaAssembly` in Learn.tsx, streaming
 * guarantees deferral by keeping the fiber's lanes non-empty via the
 * per-token `setStreamingText` calls). Modeling "always deferred" is the
 * correct worst case to test against, since that's what actually happens
 * during a real stream.
 *
 * Revert-proof (see task-9-report.md, "Fix pass 3" section, for the actual
 * command output): temporarily replacing `applyGraphDeltaAssembly`'s body
 * in Learn.tsx with the broken shape —
 *
 *   let newEdges: GraphEdge[] = [];
 *   setGraphNodes(prev => {
 *     newEdges = deltaPlaceholderEdges(prev, delta, courseId);
 *     return mergeGraphDelta(prev, delta, courseId);
 *   });
 *   if (newEdges.length) setGraphEdges(prev => mergeGraphEdges(prev, newEdges));
 *
 * — makes every test below fail: our fakes never run the nodes updater
 * inline, so `newEdges` is still `[]` at the `if` check, `setGraphEdges` is
 * never called at all, and `edges.flush` (never captured) returns `prev`
 * unchanged.
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

// A fake React-style functional-updater setter: `set` only *records* the
// updater it's given — it never invokes it — exactly matching real React's
// contract (the updater runs later, during render, not synchronously at the
// call site). `flush` applies the captured updater to `prev` to simulate
// that eventual render; if `set` was never called, `flush` returns `prev`
// unchanged — the observable behavior when a buggy call site skips the
// setState call entirely (the broken shape's actual failure mode).
function fakeSetter<T>() {
  let captured: ((prev: T) => T) | null = null;
  const set = (updater: (prev: T) => T) => { captured = updater; };
  const flush = (prev: T): T => (captured ? captured(prev) : prev);
  return { set, flush };
}

describe('applyGraphDeltaAssembly — the real applyGraphDelta call site (task-9 fix pass 3)', () => {
  it('a new streamed concept yields both the placeholder node and its root edge', () => {
    const nodes = fakeSetter<GraphNode[]>();
    const edges = fakeSetter<GraphEdge[]>();
    const snapshot = [root('math')];

    applyGraphDeltaAssembly(newNodeDelta('Eigenvalues'), 'math', snapshot, nodes.set, edges.set);

    const nextNodes = nodes.flush(snapshot);
    const nextEdges = edges.flush([]);

    const placeholder = nextNodes.find(n => n.id === 'stream-eigenvalues');
    expect(placeholder).toBeDefined();
    expect(placeholder?.course_id).toBe('math');

    expect(nextEdges).toContainEqual({ source: 'root-math', target: 'stream-eigenvalues', strength: 0.4 });
    expect(nextEdges).toHaveLength(1);
  });

  it('applying the same delta twice (two full call+flush cycles) yields exactly one edge', () => {
    const delta = newNodeDelta('Eigenvalues');
    const snapshot0 = [root('math')];

    const nodes1 = fakeSetter<GraphNode[]>();
    const edges1 = fakeSetter<GraphEdge[]>();
    applyGraphDeltaAssembly(delta, 'math', snapshot0, nodes1.set, edges1.set);
    const nodesAfter1 = nodes1.flush(snapshot0);
    const edgesAfter1 = edges1.flush([]);

    // Second cycle: the render-scope `graphNodes` closure is now
    // `nodesAfter1`, exactly like the real component's next call to
    // `applyGraphDelta` after the first delta's render has committed.
    const nodes2 = fakeSetter<GraphNode[]>();
    const edges2 = fakeSetter<GraphEdge[]>();
    applyGraphDeltaAssembly(delta, 'math', nodesAfter1, nodes2.set, edges2.set);
    const nodesAfter2 = nodes2.flush(nodesAfter1);
    const edgesAfter2 = edges2.flush(edgesAfter1);

    expect(edgesAfter2.filter(e => e.target === 'stream-eigenvalues')).toHaveLength(1);
    expect(nodesAfter2.filter(n => n.id === 'stream-eigenvalues')).toHaveLength(1);
  });

  it('the edge is computed eagerly, not threaded out of the nodes updater: it lands even when the nodes updater is never flushed', () => {
    const nodes = fakeSetter<GraphNode[]>();
    const edges = fakeSetter<GraphEdge[]>();
    const snapshot = [root('math')];

    applyGraphDeltaAssembly(newNodeDelta('Eigenvalues'), 'math', snapshot, nodes.set, edges.set);

    // Deliberately never flush `nodes` — proves the edge computation does
    // not depend on the nodes updater having run. The broken shape can
    // never pass this: it computes edges *inside* the nodes updater and
    // only calls setGraphEdges if that (unflushed) value already looks
    // non-empty at the synchronous call site, so it never calls setGraphEdges
    // at all here, and `edges.flush` is a no-op returning `[]` unchanged.
    const nextEdges = edges.flush([]);
    expect(nextEdges).toContainEqual({ source: 'root-math', target: 'stream-eigenvalues', strength: 0.4 });
  });
});
