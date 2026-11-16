"""CS101's concept tree: the units and the concepts under them. Its own
module because the class's documents and coursework (``cs101.py``) and its
study guides (``cs101_guides.py``) both read it."""
from __future__ import annotations

from db.local_study_data.spec import Concept

FOUNDATIONS = "Programming Foundations"
MEMORY = "Memory and Data"
PROBLEM_SOLVING = "Algorithmic Problem Solving"
STRUCTURES = "Data Structures"

CONCEPTS = (
    Concept("variables", "Variables and Types", FOUNDATIONS,
            "A variable is a named place that holds a value, and its type says what kind of value that is.",
            0.92, 9, 12),
    Concept("controlflow", "Control Flow", FOUNDATIONS,
            "Branches and loops decide which statements run and how many times.",
            0.60, 6, 3, ("variables",)),
    Concept("functions", "Functions", FOUNDATIONS,
            "A function names a block of code so it can be called with different arguments.",
            0.86, 7, 6, ("controlflow",)),
    Concept("scope", "Scope and Lifetime", FOUNDATIONS,
            "Scope is where a name can be used, and lifetime is how long its value exists.",
            0.78, 4, 15, ("functions",)),
    Concept("pointers", "Pointers and Memory", MEMORY,
            "A pointer is a variable that holds the address of another value.",
            0.30, 5, 2, ("variables",)),
    Concept("arrays", "Arrays and Strings", MEMORY,
            "An array is a row of same-typed values stored side by side, and a C string is a char array that ends in a zero byte.",
            0.64, 5, 4, ("variables",)),
    Concept("structs", "Structs", MEMORY,
            "A struct groups related values of different types under one name.",
            0.48, 3, 9, ("pointers",)),
    Concept("dynamic", "Dynamic Memory", MEMORY,
            "Dynamic memory is requested from the heap while the program runs and must be freed by the program.",
            0.18, 2, 8, ("pointers", "arrays")),
    Concept("files", "File Input and Output", MEMORY,
            "A program reads and writes a file through a stream that it opens and must close.",
            0.0, needs=("arrays",)),
    Concept("recursion", "Recursion", PROBLEM_SOLVING,
            "A recursive function solves a problem by calling itself on a smaller input until it reaches a base case.",
            0.25, 6, 0, ("functions",)),
    Concept("algorithms", "Algorithms", PROBLEM_SOLVING,
            "An algorithm is a finite list of exact steps that solves a problem.",
            0.80, 6, 10, ("controlflow",)),
    Concept("complexity", "Big-O Analysis", PROBLEM_SOLVING,
            "Big-O describes how the work an algorithm does grows as its input grows.",
            0.41, 4, 1, ("algorithms",)),
    Concept("sorting", "Sorting and Searching", PROBLEM_SOLVING,
            "Sorting puts values in order and searching finds one; sorted data can be searched much faster.",
            0.55, 4, 5, ("arrays", "complexity")),
    Concept("linkedlists", "Linked Lists", STRUCTURES,
            "A linked list is a chain of nodes where each node holds a value and a pointer to the next node.",
            0.52, 3, 6, ("structs", "dynamic")),
    Concept("stacks", "Stacks and Queues", STRUCTURES,
            "A stack removes the newest item first, and a queue removes the oldest first.",
            0.12, 1, 11, ("linkedlists",)),
    Concept("hashtables", "Hash Tables", STRUCTURES,
            "A hash table stores each key at an index computed from the key, so a lookup takes about constant time.",
            0.0, needs=("arrays",)),
    Concept("trees", "Trees", STRUCTURES,
            "A tree is a set of nodes where each node has one parent and any number of children.",
            0.0, needs=("linkedlists", "recursion")),
    Concept("graphs", "Graphs", STRUCTURES,
            "A graph is a set of nodes joined by edges, with no rule about parents.",
            0.0, needs=("trees",)),
)
