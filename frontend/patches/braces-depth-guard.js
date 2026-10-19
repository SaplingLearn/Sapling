'use strict';

// Local mitigation for GHSA-vfj7-8cjw-p6xm. Upstream braces 3.0.3 has no
// released fix. Keep its version and audit visibility; do not label this an
// upstream patch. The installer pins the exact files this guard protects.
const MAX_AST_DEPTH = 128;
const MAX_AST_NODES = 40000;
const MESSAGE = 'Brace pattern exceeds the local structural depth limit';

const checkStackDepth = depth => {
  if (depth >= MAX_AST_DEPTH) throw new RangeError(MESSAGE);
};

const assertDepth = ast => {
  const stack = [{ node: ast, depth: 0, leave: false }];
  const active = new WeakSet();
  let visited = 0;

  while (stack.length) {
    const { node, depth, leave } = stack.pop();
    if (!node || typeof node !== 'object' || Array.isArray(node)) {
      throw new TypeError('Invalid brace AST node');
    }
    if (leave) {
      active.delete(node);
      continue;
    }
    if (depth > MAX_AST_DEPTH || ++visited > MAX_AST_NODES || active.has(node)) {
      throw new RangeError(MESSAGE);
    }

    // expand() also walks parent pointers. Validate them iteratively, including
    // direct caller-supplied ASTs, without following the normal child->parent
    // backreferences as children or recursing through the JS call stack.
    const parents = new WeakSet();
    let parent = node;
    let parentDepth = 0;
    while (parent) {
      if (typeof parent !== 'object' || Array.isArray(parent)) {
        throw new TypeError('Invalid brace AST parent');
      }
      if (parents.has(parent) || parentDepth++ > MAX_AST_DEPTH) {
        throw new RangeError(MESSAGE);
      }
      parents.add(parent);
      parent = parent.parent;
    }

    active.add(node);
    stack.push({ node, depth, leave: true });
    if (node.nodes !== undefined) {
      if (!Array.isArray(node.nodes)) throw new TypeError('Invalid brace AST children');
      if (stack.length + node.nodes.length > MAX_AST_NODES) throw new RangeError(MESSAGE);
      for (let i = node.nodes.length - 1; i >= 0; i--) {
        stack.push({ node: node.nodes[i], depth: depth + 1, leave: false });
      }
    }
  }
};

module.exports = { assertDepth, checkStackDepth, MAX_AST_DEPTH };
