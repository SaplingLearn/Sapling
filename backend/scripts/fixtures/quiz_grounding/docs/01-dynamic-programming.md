# Dynamic Programming

Dynamic programming is an algorithmic technique for solving problems by breaking them down into simpler subproblems and storing the results to avoid redundant computation. It applies when a problem exhibits two properties: overlapping subproblems and optimal substructure.

Overlapping subproblems means that the same subproblem is solved multiple times during a naive recursive solution. Dynamic programming avoids this waste by recording each subproblem's result in a memoization table the first time it is computed, then reusing the stored value on every subsequent request instead of recomputing it.

There are two common implementation styles. Top-down dynamic programming, also called memoization, adds a cache to a recursive function so each subproblem is computed once. Bottom-up dynamic programming, also called tabulation, fills the memoization table iteratively starting from the smallest subproblems and building up to the full problem, avoiding recursion overhead entirely.

Classic examples include computing Fibonacci numbers, the 0/1 knapsack problem, longest common subsequence, and edit distance. In each case a naive recursive approach runs in exponential time, but dynamic programming with a memoization table reduces the running time to polynomial time by ensuring every distinct subproblem is solved exactly once.
