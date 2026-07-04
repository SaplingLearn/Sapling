# Binary Search Trees

A binary search tree, often abbreviated BST, is a binary tree where every node's left subtree contains only keys smaller than the node's key, and every node's right subtree contains only keys larger. This ordering property lets a binary search tree support search, insertion, and deletion in logarithmic time on average, though a degenerate binary search tree can degrade to linear time if it becomes a straight chain.

An in-order traversal of a binary search tree visits nodes in ascending sorted order: left subtree, then the node itself, then right subtree. Pre-order traversal visits the node before its subtrees, and post-order traversal visits the node after both subtrees, but only in-order traversal yields sorted output for a binary search tree.

When a binary search tree becomes unbalanced, self-balancing variants such as AVL trees and red-black trees automatically rotate nodes during insertion and deletion to keep the tree's height logarithmic in the number of nodes.

Note on terminology: this course's use of the word "tree" refers strictly to the computer-science data structure described above. It does not cover phylogenetic trees in evolutionary biology, family trees in genealogy, or decision trees as a machine-learning classification model — those are unrelated concepts that happen to share the word "tree."
