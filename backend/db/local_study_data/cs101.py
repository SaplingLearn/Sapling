"""CS101, Introduction to Computer Science: the local study dataset's first
class. Plain content; ``spec.py`` says what each field is."""
from __future__ import annotations

from db.local_study_data import blocks as b
from db.local_study_data.spec import (
    Assessment,
    CardSet,
    ClassData,
    Concept,
    Digest,
    GuideSpec,
    Material,
    Quiz,
    SectionDraft,
    Tutoring,
)

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
_C = {c.key: c for c in CONCEPTS}

MATERIALS = (
    Material("syllabus", "CS101 Syllabus.pdf", "syllabus", 75,
             "Course plan: weekly homework, two midterms, a project and a final exam.",
             ("variables", "algorithms"), (
                 "CS101 introduces programming in C. The first half covers variables, control flow, "
                 "functions and memory. The second half covers algorithms and data structures.",
                 "Grading: homework 25 percent, two midterms 20 percent each, one project 10 percent, "
                 "final exam 25 percent. Homework is due on Fridays.",
                 "Midterm 1 covers the programming foundations. Midterm 2 covers memory and algorithmic "
                 "problem solving. The final exam covers the whole course.",
             )),
    Material("lec03", "Lecture 03 - Control Flow.pdf", "lecture_notes", 66,
             "If statements, while loops and for loops, and how to count the passes of a loop.",
             ("controlflow", "variables"), (
                 "Control flow is the order in which statements run. An if statement runs its block only "
                 "when its condition is true. An else block runs when it is false.",
                 "A while loop checks its condition before every pass. A for loop packs the start, the "
                 "condition and the step into one line. Both stop the first time the condition is false.",
                 "To count the passes of a loop, list the values the loop variable takes while the "
                 "condition holds. A loop that starts at 0 and adds 3 while below 10 takes 0, 3, 6 and 9.",
             )),
    Material("lec05", "Lecture 05 - Functions and Scope.pptx", "slides", 54,
             "Declaring and calling functions, parameters and return values, and local scope.",
             ("functions", "scope"), (
                 "A function has a name, parameters and a return type. Calling it copies each argument "
                 "into its parameter, runs the body, and hands back the return value.",
                 "C passes arguments by value. A function that changes its parameter changes its own "
                 "copy, not the caller's variable.",
                 "A variable declared inside a function is local. It is created when the function is "
                 "called and is gone when the function returns. A global variable lives for the whole run.",
             )),
    Material("lec07", "Lecture 07 - Recursion.pdf", "lecture_notes", 40,
             "Base cases, recursive cases and how the call stack grows and unwinds.",
             ("recursion", "functions"), (
                 "A recursive function calls itself on a smaller input. The base case is the input it "
                 "answers directly. The recursive case reduces the problem toward the base case.",
                 "Each call gets its own frame on the call stack with its own copy of the parameters. "
                 "factorial(3) calls factorial(2), which calls factorial(1), which calls factorial(0).",
                 "The answers come back in reverse order. factorial(0) returns 1, then 1, then 2, then 6. "
                 "A function with no reachable base case never stops and overflows the stack.",
             )),
    Material("lec09", "Lecture 09 - Pointers and Memory.pptx", "slides", 31,
             "Addresses, the & and * operators, and how the stack and the heap differ.",
             ("pointers", "dynamic"), (
                 "Every variable lives at an address. The & operator gives the address of a variable. A "
                 "pointer is a variable that stores such an address.",
                 "The * operator follows a pointer to the value it points at. Writing through *p changes "
                 "the variable p points to. A pointer that holds NULL points at nothing.",
                 "Local variables live on the stack and vanish when their function returns. Memory from "
                 "malloc lives on the heap until the program calls free on it.",
             )),
    Material("lec11", "Lecture 11 - Arrays and Strings.pdf", "lecture_notes", 26,
             "Array indexing, the link between arrays and pointers, and null-terminated strings.",
             ("arrays", "pointers"), (
                 "An array stores values of one type side by side. Indexes start at 0, so an array of 5 "
                 "items has indexes 0 to 4. C does not check that an index is in range.",
                 "The name of an array acts as a pointer to its first element. a[i] means the same as "
                 "*(a + i): move i elements along, then follow the pointer.",
                 "A C string is a char array that ends with the zero byte. The string cat needs 4 bytes: "
                 "three letters and the terminator. strlen counts the letters and not the terminator.",
             )),
    Material("lec13", "Lecture 13 - Big-O Analysis.pdf", "lecture_notes", 19,
             "Counting steps, growth rates, and why constants and small terms are dropped.",
             ("complexity", "algorithms"), (
                 "Big-O describes how the number of steps grows with the input size n. It ignores "
                 "constant factors and keeps only the fastest growing term.",
                 "One loop over n items is O(n). A loop inside a loop is O(n^2). Halving the problem at "
                 "each step, as binary search does, is O(log n).",
                 "Big-O is about growth and not about speed on one input. An O(n^2) program can beat an "
                 "O(n) program on a small list and still lose badly on a large one.",
             )),
    Material("reading", "Reading - Structs and Dynamic Memory.pdf", "reading", 15,
             "Textbook chapter on struct types, malloc and free, and common memory errors.",
             ("structs", "dynamic"), (
                 "A struct groups values of different types under one name. Fields are reached with a "
                 "dot, or with an arrow through a pointer to the struct.",
                 "malloc asks the heap for a number of bytes and returns a pointer to them, or NULL when "
                 "none are left. Every malloc needs exactly one matching free.",
                 "Three errors account for most crashes: using memory after it is freed, freeing the "
                 "same block twice, and never freeing a block at all, which is a leak.",
             )),
    Material("lec15", "Lecture 15 - Sorting and Searching.pptx", "slides", 12,
             "Insertion sort, merge sort and binary search, with running times measured in lab.",
             ("sorting", "complexity"), (
                 "Insertion sort grows a sorted region one item at a time and is O(n^2). Merge sort "
                 "splits the list in half, sorts each half and merges them, and is O(n log n).",
                 "Timing on the lab machine, in milliseconds. Insertion sort: 1000 items took 12, 2000 "
                 "took 47, 4000 took 190 and 8000 took 760. Merge sort: 1000 items took 2, 2000 took 4, "
                 "4000 took 9 and 8000 took 19.",
                 "Binary search looks at the middle of a sorted list and throws away the half that "
                 "cannot hold the target. It needs the list to be sorted first.",
             )),
    Material("hw6", "Homework 6 - Recursion Problems.pdf", "assignment", 8,
             "Six problems: trace recursive calls, find missing base cases, and write two recursive functions.",
             ("recursion",), (
                 "Problem 1: trace sum_to(4), where sum_to(n) returns 0 when n is 0 and n plus "
                 "sum_to(n - 1) otherwise. Write one line per call.",
                 "Problem 3: the function count_down(n) prints n and calls count_down(n - 1). Explain "
                 "why it never stops and add the missing base case.",
                 "Problem 5: write a recursive function that returns the number of digits in a positive "
                 "integer. State its base case and its recursive case before you write code.",
             )),
    Material("lec17", "Lecture 17 - Linked Lists.pdf", "lecture_notes", 5,
             "Nodes, the head pointer, and inserting and deleting without shifting elements.",
             ("linkedlists", "structs"), (
                 "A linked list is made of nodes. Each node is a struct with a value and a pointer to "
                 "the next node. The list is known by a pointer to its first node, the head.",
                 "To insert at the front, point the new node at the old head, then move the head to the "
                 "new node. No element moves, so the cost is O(1).",
                 "Reaching item i means following i pointers from the head, so indexing is O(n). The "
                 "last node points to NULL, which is how a loop over the list knows to stop.",
             )),
    Material("lec18", "Lecture 18 - Stacks and Queues.pdf", "lecture_notes", 2,
             "Last-in first-out and first-in first-out, each built on a linked list.",
             ("stacks", "linkedlists"), (
                 "A stack adds and removes at the same end. The last item pushed is the first popped. "
                 "The call stack that holds function frames works this way.",
                 "A queue adds at the back and removes from the front. The first item in is the first "
                 "out, like a line at a counter.",
                 "Both are easy to build on a linked list. A stack pushes and pops at the head. A queue "
                 "keeps a second pointer to the tail so that adding at the back is also O(1).",
             )),
)

ASSESSMENTS = (
    Assessment("mid1", "Midterm 1", "exam", -24, 100, 84, (FOUNDATIONS,)),
    Assessment("mid2", "Midterm 2", "exam", 9, covers=(MEMORY, PROBLEM_SOLVING)),
    Assessment("final", "Final Exam", "exam", 27,
               covers=(FOUNDATIONS, MEMORY, PROBLEM_SOLVING, STRUCTURES)),
    Assessment("quiz1", "Quiz 1: Control Flow", "quiz", -62, 20, 17, concepts=("variables", "controlflow")),
    Assessment("quiz2", "Quiz 2: Linked Lists", "quiz", 12, 20, concepts=("structs", "linkedlists", "stacks")),
    Assessment("hw5", "Homework 5: Pointers", "homework", -10, 50, 41),
    Assessment("hw6", "Homework 6: Recursion", "homework", 1, 50),
    Assessment("hw7", "Homework 7: Linked Lists", "homework", 13, 50),
    Assessment("project", "Project 2: Text Adventure", "project", 16, 100),
)

CARDS = {
    "variables": (
        ("What does a variable's type decide?", "Which values it can hold and which operations are allowed on it."),
        ("What is the difference between = and ==?", "= assigns a value to a name; == tests whether two values are equal."),
        ("What does the expression 7 / 2 give with int operands in C?", "3, because integer division drops the fraction."),
        ("What is a constant?", "A named value that cannot be changed after it is set."),
        ("What happens when you read an uninitialised local variable?", "You get whatever bytes were already in that memory."),
    ),
    "controlflow": (
        ("When does a while loop stop?", "The first time its condition is false when checked before a pass."),
        ("What does break do inside a loop?", "It leaves the nearest enclosing loop at once."),
        ("What does continue do inside a loop?", "It skips the rest of this pass and starts the next one."),
        ("What is an off-by-one error?", "A loop that runs one pass too many or one too few."),
        ("What is short-circuit evaluation?", "Stopping a boolean expression as soon as its result is known."),
        ("How many passes does a loop make from i = 0 while i < 10, adding 3?", "Four passes, for i = 0, 3, 6 and 9."),
    ),
    "functions": (
        ("What is a parameter?", "A variable in a function's definition that receives an argument."),
        ("What is an argument?", "The value a caller passes to a function."),
        ("What does pass by value mean?", "The function gets a copy, so changing it does not change the caller's variable."),
        ("What does a void function return?", "Nothing; it is called for its effect."),
        ("Why declare a function before calling it?", "So the compiler knows its parameter types and return type."),
    ),
    "scope": (
        ("What is a local variable?", "A variable declared inside a function, usable only there."),
        ("When is a local variable destroyed?", "When the function it was declared in returns."),
        ("What is a global variable?", "A variable declared outside every function, alive for the whole run."),
        ("What is shadowing?", "An inner variable hiding an outer one that has the same name."),
    ),
    "pointers": (
        ("What does a pointer hold?", "The memory address of another value."),
        ("What does the & operator give you?", "The address of the variable it is applied to."),
        ("What does *p mean when p is a pointer?", "The value stored at the address p holds."),
        ("What is a NULL pointer?", "A pointer that points at nothing."),
        ("What is a dangling pointer?", "A pointer to memory that has already been freed or has gone out of scope."),
        ("What happens when you dereference NULL?", "The program crashes, usually with a segmentation fault."),
        ("What does p++ do to an int pointer?", "It moves p forward by the size of one int."),
    ),
    "arrays": (
        ("What is the index of the first element of an array?", "0."),
        ("What does a[i] mean in terms of pointers?", "*(a + i): move i elements from the start, then follow the pointer."),
        ("How does a C string mark its end?", "With a zero byte after the last character."),
        ("How many bytes does the string \"cat\" need?", "Four: three letters and the terminator."),
        ("What does strlen count?", "The characters before the terminator, not the terminator itself."),
        ("What happens when you index past the end of an array?", "C does not check, so you read or overwrite other memory."),
    ),
    "structs": (
        ("What is a struct?", "A type that groups related values of different types under one name."),
        ("How do you reach a field through a pointer to a struct?", "With the arrow operator, as in p->field."),
        ("How do you reach a field of a struct variable?", "With the dot operator, as in s.field."),
        ("Why pass a pointer to a struct instead of the struct?", "It avoids copying the whole struct and lets the function change it."),
    ),
    "dynamic": (
        ("What does malloc return?", "A pointer to a block of heap memory, or NULL when none is available."),
        ("What is a memory leak?", "Heap memory that is never freed and can no longer be reached."),
        ("What is a double free?", "Calling free twice on the same block, which corrupts the heap."),
        ("Where does memory from malloc live?", "On the heap, until the program frees it."),
        ("What is use after free?", "Reading or writing a block after free has been called on it."),
    ),
    "recursion": (
        ("What must every recursive function have?", "A base case that it is certain to reach."),
        ("What is the recursive case?", "The branch that calls the function again on a smaller input."),
        ("What is a stack frame?", "The record of one active call: its parameters and local variables."),
        ("What causes a stack overflow in recursion?", "Calls that never reach a base case."),
        ("In what order do recursive calls return?", "In reverse: the last call made returns first."),
        ("What does factorial(3) return?", "6, from 3 times 2 times 1 times 1."),
        ("What is tail recursion?", "A recursive call that is the last thing the function does."),
    ),
    "algorithms": (
        ("What is an algorithm?", "A finite list of exact steps that solves a problem."),
        ("What is pseudocode?", "A description of an algorithm in plain structured language, not a real one."),
        ("What does it mean for an algorithm to be correct?", "It gives the right output for every valid input."),
        ("What is a loop invariant?", "A statement that is true before and after every pass of a loop."),
    ),
    "complexity": (
        ("What does Big-O describe?", "How the number of steps grows as the input grows."),
        ("What is the Big-O of one loop over n items?", "O(n)."),
        ("What is the Big-O of a loop inside a loop over n items?", "O(n^2)."),
        ("What is the Big-O of binary search?", "O(log n)."),
        ("Why are constant factors dropped in Big-O?", "They do not change how the growth scales with n."),
        ("What does O(1) mean?", "The work does not depend on the input size."),
    ),
    "sorting": (
        ("What does binary search require of the list?", "That it is already sorted."),
        ("What is the running time of insertion sort?", "O(n^2) in the worst case."),
        ("What is the running time of merge sort?", "O(n log n) in every case."),
        ("How does merge sort work?", "It splits the list in half, sorts each half, and merges them."),
        ("What is linear search?", "Checking each item in turn until the target is found."),
        ("When is insertion sort a good choice?", "For short lists or lists that are almost sorted."),
    ),
    "linkedlists": (
        ("What does a linked list node hold?", "A value and a pointer to the next node."),
        ("What is the head of a linked list?", "The pointer to its first node."),
        ("What does the last node of a linked list point to?", "NULL."),
        ("What is the cost of inserting at the front of a linked list?", "O(1), because nothing has to move."),
        ("What is the cost of reaching item i in a linked list?", "O(n), because you follow i pointers from the head."),
    ),
    "stacks": (
        ("What order does a stack remove items in?", "Last in, first out."),
        ("What order does a queue remove items in?", "First in, first out."),
        ("What are the two stack operations called?", "Push to add an item and pop to remove one."),
        ("Which structure holds function calls while a program runs?", "A stack, called the call stack."),
        ("Why does a linked queue keep a tail pointer?", "So adding at the back takes O(1) instead of a walk down the list."),
    ),
}

QUIZZES = (
    Quiz("variables", 24, 17, 5),
    Quiz("controlflow", 21, 19, 3),
    Quiz("controlflow", 3, 18, 4),
    Quiz("recursion", 27, 20, 1),
    Quiz("recursion", 13, 16, 2),
    Quiz("recursion", 6, 21, 2, difficulty="hard"),
    Quiz("recursion", 0, 0, 3, minutes_ago=95),
    Quiz("pointers", 16, 18, 1),
    Quiz("pointers", 9, 20, 2),
    Quiz("pointers", 2, 19, 3),
    Quiz("complexity", 11, 17, 2),
    Quiz("complexity", 1, 21, 3),
    Quiz("arrays", 8, 16, 3, difficulty="easy"),
    Quiz("arrays", 4, 20, 4),
    Quiz("sorting", 5, 18, 3),
    Quiz("linkedlists", 0, 0, 2, state="open"),
    Quiz("structs", 12, 15, 0, total=4, state="abandoned"),
)

DIGESTS = (
    Digest("recursion",
           ("Leaves out the base case, or writes one the input never reaches",
            "Returns the recursive call's value without combining it with n"),
           ("Tracing return values back up the call stack",),
           "Factorial and sum traces, missing base cases, counting calls."),
    Digest("pointers",
           ("Uses a pointer before it points at anything",
            "Confuses the address stored in p with the value at *p"),
           ("Reading declarations that mix * and &",),
           "Dereferencing, address-of, NULL checks, pointer arithmetic.", "easy"),
    Digest("complexity",
           ("Counts a nested loop as O(n) because each loop is O(n)",),
           ("Telling O(log n) from O(n)",),
           "Growth rates of single and nested loops, dropping constants."),
    Digest("controlflow",
           ("Runs a loop one pass too many when the condition uses <=",),
           (), "Counting loop passes, break and continue.", "hard"),
    Digest("arrays",
           ("Forgets the terminator when sizing a string buffer",),
           ("Index arithmetic with pointers",),
           "Indexing, string length, out-of-range access."),
    Digest("sorting",
           ("Runs binary search on a list that is not sorted",),
           (), "Which sort to pick, binary search steps."),
)

TUTORING = (
    Tutoring("structs", "structs", "Why Use Structs", 33, 16, (0, 7, 15), ended=True),
    Tutoring("loops", "controlflow", "Loops and Conditions", 17, 19, (0, 5, 12, 17, 22), ended=True),
    Tutoring("bigo", "complexity", "Counting Steps with Big-O", 4, 20, (0, 6, 13, 21), "expository"),
    Tutoring("recursion", "recursion", "Tracing Recursive Calls", 2, 18, (0, 4, 11, 19, 24), ended=True),
    Tutoring("pointers", "pointers", "Getting Started with Pointers", 0, 0, (0, 3, 8, 12)),
)

CARD_SETS = (
    CardSet("basics", "Foundations warm-up", ("variables", "controlflow", "functions", "scope"), 20,
            exam="mid1", shuffle=False),
    CardSet("mid2", "Midterm 2 review", ("pointers", "arrays", "recursion", "complexity", "sorting"), 3,
            exam="mid2"),
    CardSet("weak", "What I keep missing", ("recursion", "pointers", "dynamic"), 1, only_due=True),
)

SECTIONS = {
    "variables": SectionDraft(
        "Variables and types",
        "A variable is a name bound to a value, and the value's type decides what you can do with it.",
        (
            b.prose(
                ("A **variable** is a named place in memory that holds a value. Declaring one tells the "
                 "compiler its **type**, and the type fixes how many bytes it takes and which operations "
                 "make sense on it.", "lec03"),
                "Assignment copies a value into the variable. It does not link two variables together: "
                "after `b = a`, changing `a` leaves `b` alone.",
                summary="A variable is a typed, named place for a value. Assignment copies; it does not link.",
            ),
            b.terms(_C["variables"],
                    ("Assignment", "The statement that copies a value into a variable."),
                    ("Integer division", "Division of two ints, which drops the fraction.")),
            b.compare(
                "Assignment and comparison", ("=", "=="),
                ("What it does", "Copies the right side into the left", "Tests whether two values are equal"),
                ("What it gives back", "The value that was assigned", "1 for true or 0 for false"),
                ("Classic bug", "if (x = 5) is always true", "x == 5; on its own line does nothing"),
                emphasis=2,
            ),
            b.check(
                "With int a = 7 and int b = 2, what is a / b?",
                ("3.5", "3", "4"), 1,
                "Both operands are ints, so the division drops the fraction and gives 3.",
                "Look at the types of both operands before you divide.",
            ),
        ),
    ),
    "controlflow": SectionDraft(
        "Control flow",
        "Branches choose which code runs, and loops repeat it until a condition turns false.",
        (
            b.prose(
                ("**Control flow** is the order statements run in. An `if` picks a branch. A loop "
                 "repeats its body, checking its condition before every pass.", "lec03"),
                "Exam questions rarely ask what a loop is. They ask how many times its body runs and "
                "what it prints, so the skill to practise is tracing.",
                summary="Branches choose and loops repeat. Trace a loop by listing the values its variable takes.",
            ),
            b.formula(
                "Passes of a counting loop",
                r"\text{passes} = \left\lceil \frac{\text{stop} - \text{start}}{\text{step}} \right\rceil",
                "Passes equal stop minus start, divided by step, rounded up.",
                "lec03",
            ),
            b.example(
                "Count the passes",
                "A loop starts i at 1 and adds 4 while i is below 14. How many times does the body run?",
                ("List the values", "1, 5, 9, 13", "Keep adding the step while the condition still holds."),
                ("Check the next one", "17 < 14 is false", "The loop stops before the body runs for 17."),
                ("Count them", "4 passes", "One pass for each value listed."),
                source="lec03",
            ),
            b.check(
                "A loop starts i at 0 and adds 3 while i is below 10. How many times does the body run?",
                ("3", "4", "10"), 1,
                "The variable i takes the values 0, 3, 6 and 9, so the body runs four times.",
                "List every value i takes while the condition holds, then count them.",
            ),
        ),
    ),
    "functions": SectionDraft(
        "Functions",
        "A function names a block of code, takes arguments by value and hands back one result.",
        (
            b.prose(
                ("A **function** packages steps under a name. A call copies each **argument** into the "
                 "matching **parameter**, runs the body and returns one value.", "lec05"),
                ("C passes by value. The function works on copies, so nothing it does to a parameter "
                 "reaches the caller's variable unless it is given a pointer.", "lec05"),
                summary="A call copies arguments into parameters. Changes to a parameter stay inside the function.",
            ),
            b.terms(("Parameter", "A variable in the function's definition that receives an argument."),
                    ("Argument", "The value the caller passes in."),
                    ("Return value", "The one value a call evaluates to.")),
            b.example(
                "What does the caller see?",
                "void bump(int n) { n = n + 1; } is called as bump(x) with x equal to 5. What is x afterwards?",
                ("Copy the argument", "n = 5", "The call copies the value of x into the parameter n."),
                ("Run the body", "n = 6", "Only the copy changes."),
                ("Return", "x = 5", "n is destroyed and x was never touched."),
            ),
            b.check(
                "A function changes one of its int parameters. What happens to the caller's variable?",
                ("It changes too", "Nothing: the function changed its own copy", "The program does not compile"), 1,
                "C passes by value, so the function only ever had a copy.",
                "Think about what a call does with each argument before the body runs.",
            ),
        ),
    ),
    "scope": SectionDraft(
        "Scope and lifetime",
        "A local variable exists only while its function runs, and only that function can name it.",
        (
            b.prose(
                ("**Scope** is where a name can be used. **Lifetime** is how long the value exists. A "
                 "local variable has both tied to one call of its function.", "lec05"),
                "That is why returning the address of a local variable is a bug: the address is still a "
                "number, but the variable it named is gone.",
                summary="Locals live for one call and are visible only inside it. Globals live for the whole run.",
            ),
            b.compare(
                "Local and global variables", ("Local", "Global"),
                ("Declared", "Inside a function", "Outside every function"),
                ("Lifetime", "One call of the function", "The whole run of the program"),
                ("Visible from", "That function only", "Every function below the declaration"),
                emphasis=1,
            ),
            b.check(
                "A function returns the address of one of its local variables. Why is that a bug?",
                ("Addresses cannot be returned", "The variable is destroyed when the function returns",
                 "Local variables have no address"), 1,
                "The local's lifetime ends at the return, so the address points at memory that is no longer its own.",
                "Ask how long the variable lives, not where it can be named.",
            ),
        ),
    ),
    "pointers": SectionDraft(
        "Pointers and memory",
        "A pointer holds an address: & takes one, * follows one, and following a bad one crashes.",
        (
            b.prose(
                ("A **pointer** is a variable whose value is an address. `&x` gives the address of x. "
                 "`*p` follows the address in p to the value stored there.", "lec09"),
                ("Writing through `*p` changes the variable that p points at. This is how a function "
                 "changes its caller's data even though C passes by value.", "lec09"),
                "A pointer that was never set points somewhere arbitrary. Set every pointer when you "
                "declare it, to a real address or to **NULL**.",
                summary="& takes an address and * follows one. Never follow a pointer you have not set.",
            ),
            b.mistakes(
                (0, "Following a pointer before it is set",
                 "Initialise every pointer where you declare it, and check for NULL before the first *."),
                (1, "Mixing up p and *p",
                 "Say it out loud: p is where, *p is what. Draw the box and the arrow before you answer."),
            ),
            b.compare(
                "The two pointer operators", ("&x", "*p"),
                ("Read as", "The address of x", "The value p points at"),
                ("Applied to", "A variable", "A pointer"),
                ("In a declaration", "Not used", "int *p declares p as a pointer to int"),
                emphasis=0,
            ),
            b.example(
                "Follow the pointer",
                "int x = 4; int *p = &x; *p = *p + 3; What is x?",
                ("Point p at x", "p = &x", "p now holds the address of x."),
                ("Read through p", "*p is 4", "Following p reaches x, which holds 4."),
                ("Write through p", "*p = 7", "The assignment stores 7 where p points."),
                ("Read x", "x = 7", "x and *p are the same place in memory."),
                source="lec09",
            ),
            b.concept_map(
                "Where pointers lead",
                (_C["variables"], "Foundations"), (_C["pointers"], "This section"),
                (_C["dynamic"], "Up next"), (_C["linkedlists"], "Later"),
            ),
            b.check(
                "After int x = 10; int *p = &x; *p = 20; what is the value of x?",
                ("10", "20", "The address of x"), 1,
                "*p and x name the same memory, so writing 20 through p changes x.",
                "Draw x as a box and p as an arrow to it, then apply the assignment to the box.",
            ),
        ),
    ),
    "arrays": SectionDraft(
        "Arrays and strings",
        "An array is a row of values reached by index, and a string is a char array with a zero at the end.",
        (
            b.prose(
                ("An **array** stores values of one type side by side. The index counts from 0, and C "
                 "never checks that it is in range.", "lec11"),
                ("An array's name behaves like a pointer to its first element, which is why `a[i]` and "
                 "`*(a + i)` mean the same thing. A **string** is a char array ended by a zero byte.", "lec11"),
                summary="Indexes start at 0 and are not checked. A string needs one extra byte for its terminator.",
            ),
            b.formula(
                "Where element i lives",
                r"\text{address}(a[i]) = \text{address}(a[0]) + i \times \text{size of one element}",
                "The address of element i is the address of element zero plus i times the element size.",
                "lec11",
            ),
            b.example(
                "Size a string buffer",
                "How many bytes does a buffer need to hold the string \"hello\"?",
                ("Count the letters", "5 letters", "strlen would report 5."),
                ("Add the terminator", "5 + 1", "Every C string ends with one zero byte."),
                ("Answer", "6 bytes", "A buffer of 5 would overflow by one byte."),
                source="lec11",
            ),
            b.check(
                "char word[4] = \"cat\"; What does word[3] hold?",
                ("The letter t", "The zero byte that ends the string", "Nothing: the index is out of range"), 1,
                "Indexes 0 to 2 hold c, a and t, and index 3 holds the terminator.",
                "Write out the index of every byte, starting from 0.",
            ),
        ),
    ),
    "recursion": SectionDraft(
        "Recursion",
        "A recursive function calls itself on a smaller input and stops at a base case.",
        (
            b.prose(
                ("A **recursive** function calls itself on a smaller input. The **base case** is the "
                 "input it answers without another call. Every other input must move toward it.", "lec07"),
                ("Each call gets its own frame on the call stack. The calls stack up until the base "
                 "case returns, and then the answers come back in reverse order.", "lec07"),
                ("Homework 6 is mostly tracing. Write one line per call going down, then fill in the "
                 "return values from the bottom up.", "hw6"),
                summary="Calls go down to the base case, then answers come back up. Trace one line per call.",
            ),
            b.mistakes(
                (0, "A base case the input never reaches",
                 "Check that every call moves toward the base case. Stepping by 2 can jump straight over n == 0."),
                (1, "Dropping the work on the way back up",
                 "The recursive case must combine the returned value with n. Returning the call alone loses it."),
            ),
            b.formula(
                "Factorial, defined recursively",
                r"n! = n \times (n-1)!, \qquad 0! = 1",
                "n factorial is n times the factorial of n minus one, and zero factorial is one.",
                "lec07",
            ),
            b.example(
                "Trace factorial(3)",
                "factorial(n) returns 1 when n is 0 and n * factorial(n - 1) otherwise. What does factorial(3) return?",
                ("Go down", "f(3) -> f(2) -> f(1) -> f(0)", "Each call waits for the one below it."),
                ("Hit the base case", "f(0) = 1", "No further call is made."),
                ("Come back up", "f(1) = 1 * 1 = 1", "The waiting call finishes its multiplication."),
                ("Keep going", "f(2) = 2 * 1 = 2", "Each frame uses the value returned to it."),
                ("Answer", "f(3) = 3 * 2 = 6", "The first call is the last to return."),
                source="lec07",
            ),
            b.concept_map(
                "What recursion builds on",
                (_C["controlflow"], "Foundations"), (_C["functions"], "Before this"),
                (_C["recursion"], "This section"), (_C["trees"], "Up next"),
            ),
            b.check(
                "sum_to(n) returns 0 when n is 0 and n + sum_to(n - 1) otherwise. What does sum_to(4) return?",
                ("4", "10", "24"), 1,
                "4 + 3 + 2 + 1 + 0 is 10: each call adds its own n to the sum below it.",
                "Write the five calls from sum_to(4) down to sum_to(0), then add on the way back up.",
            ),
        ),
    ),
    "complexity": SectionDraft(
        "Big-O analysis",
        "Big-O keeps the fastest growing term and drops the constants, so it compares growth and not speed.",
        (
            b.prose(
                ("**Big-O** says how the number of steps grows with the input size n. One loop over the "
                 "input is O(n). A loop inside a loop is O(n^2). Halving the input each step is O(log n).",
                 "lec13"),
                ("Constants and smaller terms are dropped because they do not change the shape of the "
                 "growth. That also means Big-O cannot tell you which program is faster on a short list.",
                 "lec13"),
                summary="Count how the steps grow with n, keep the largest term and drop the constants.",
            ),
            b.chart(
                "Steps to find one value", "Items in the list", "Steps",
                b.line("Linear search", (0, 0), (250, 250), (500, 500), (1000, 1000)),
                b.line("Binary search", (1, 1), (250, 8), (500, 9), (1000, 10), after=True),
                alt="Linear search rises in a straight line. Binary search on the sorted list stays nearly flat.",
                source="lec13",
                markers=(b.marker(1000, 1000, "n", "n steps"),
                         b.marker(1000, 10, "n", "log n steps", after=True)),
                readouts=(b.readout("Steps for 1,000 items", "1,000", "10", "Falls"),
                          b.readout("Growth", "O(n)", "O(log n)", "Slower growth")),
                after_label="After sorting",
            ),
            b.compare(
                "Common growth rates", ("Typical code", "Steps for 1,000 items"),
                ("O(1)", "Index into an array", "1"),
                ("O(log n)", "Binary search", "About 10"),
                ("O(n)", "One loop over the input", "1,000"),
                ("O(n^2)", "A loop inside a loop", "1,000,000"),
                emphasis=3,
            ),
            b.formula(
                "Keep the largest term",
                r"3n^2 + 5n + 2 = O(n^2)",
                "Three n squared plus five n plus two is big O of n squared.",
            ),
            b.check(
                "A function loops over n items, and inside that loop it loops over the same n items again. "
                "What is its Big-O?",
                ("O(n)", "O(2n)", "O(n^2)"), 2,
                "The inner loop runs n times for each of the n outer passes, which is n times n steps.",
                "Count how many times the innermost line runs in total.",
            ),
        ),
    ),
    "sorting": SectionDraft(
        "Sorting and searching",
        "Merge sort beats insertion sort as lists grow, and a sorted list can be searched in O(log n).",
        (
            b.prose(
                ("**Insertion sort** grows a sorted region one item at a time and is O(n^2). **Merge "
                 "sort** splits the list, sorts the halves and merges them, and is O(n log n).", "lec15"),
                ("The lab timings show the gap. Doubling the list roughly quadruples insertion sort's "
                 "time and only a little more than doubles merge sort's.", "lec15"),
                summary="Insertion sort is O(n^2), merge sort is O(n log n), and binary search needs sorted input.",
            ),
            b.chart(
                "Measured sorting time", "Items", "Milliseconds",
                b.line("Insertion sort", (1000, 12), (2000, 47), (4000, 190), (8000, 760)),
                b.line("Merge sort", (1000, 2), (2000, 4), (4000, 9), (8000, 19)),
                alt="Insertion sort's time climbs steeply as the list grows while merge sort's stays close to flat.",
                source="lec15",
            ),
            b.compare(
                "Two sorts", ("Insertion sort", "Merge sort"),
                ("Worst case", "O(n^2)", "O(n log n)"),
                ("Extra memory", "None", "A second array of n items"),
                ("Good for", "Short or nearly sorted lists", "Long lists"),
                emphasis=0,
            ),
            b.example(
                "Binary search for 23",
                "Find 23 in the sorted list 3, 8, 12, 17, 23, 31, 40.",
                ("Look at the middle", "17", "17 is less than 23, so discard the left half."),
                ("Middle of what is left", "31", "31 is greater than 23, so discard the right part."),
                ("One item remains", "23", "Found in 3 looks instead of 5."),
                source="lec15",
            ),
            b.check(
                "Which of these must be true before you can use binary search on a list?",
                ("The list has an even length", "The list is sorted", "The list holds no duplicates"), 1,
                "Binary search discards half the list by comparing with the middle, which only works in sorted order.",
                "Ask what lets the search throw away half of the items after one comparison.",
            ),
        ),
    ),
    "linkedlists": SectionDraft(
        "Linked lists",
        "A linked list trades fast indexing for fast insertion: nodes are chained by pointers.",
        (
            b.prose(
                ("A **linked list** is a chain of **nodes**. Each node is a struct holding a value and a "
                 "pointer to the next node, and the list is known by its **head** pointer.", "lec17"),
                ("Inserting at the front never moves an element, so it is O(1). Reaching item i means "
                 "following i pointers, so indexing is O(n), the reverse of an array.", "lec17"),
                summary="Nodes chained by pointers. Insert at the front in O(1), but index in O(n).",
            ),
            b.terms(_C["linkedlists"],
                    ("Node", "One element of the list: a value and a pointer to the next node."),
                    ("Head", "The pointer to the first node. An empty list has a NULL head.")),
            b.example(
                "Insert at the front",
                "The list is 5 -> 9 and head points at the node holding 5. Insert 2 at the front.",
                ("Make the node", "new->value = 2", "malloc one node and store the value."),
                ("Link it in", "new->next = head", "The new node now points at the old first node."),
                ("Move the head", "head = new", "The list is 2 -> 5 -> 9. Doing this before the link would lose the list."),
                source="lec17",
            ),
            b.concept_map(
                "What a linked list is built from",
                (_C["pointers"], "Foundations"), (_C["structs"], "Before this"),
                (_C["dynamic"], "Before this"), (_C["linkedlists"], "This section"),
                (_C["stacks"], "Up next"),
            ),
            b.check(
                "Why is inserting at the front of a linked list O(1)?",
                ("The list is kept sorted", "Only two pointers change and no element moves",
                 "Nodes are stored side by side"), 1,
                "The new node points at the old head and the head moves to it, whatever the list's length.",
                "Count what has to change in memory when a node goes in front.",
            ),
        ),
    ),
}

GUIDES = (
    GuideSpec(
        "mid1", "Midterm 1: the programming foundations",
        "Four even sections on what Midterm 1 covers, written without your quiz history.",
        ("= assigns and == compares.",
         "Trace a loop by listing the values its variable takes.",
         "C passes by value: a function changes its own copy."),
        "mid1", "exam_prep", "standard", ("variables", "controlflow", "functions", "scope"),
        made_hours_ago=28 * 24, saved_hours_ago=27 * 24, use_history=False,
        read=("variables", "controlflow", "functions", "scope"),
        answers={"controlflow": "b", "functions": "b"}, feedback="yes",
    ),
    GuideSpec(
        "mid2", "Pointers, recursion and Big-O",
        "What Midterm 2 covers, with the most room for pointers, recursion and Big-O, your weakest topics here.",
        ("p is where and *p is what.",
         "Every recursive call must move toward a base case.",
         "Keep the fastest growing term and drop the constants."),
        "mid2", "exam_prep", "standard", ("pointers", "arrays", "recursion", "complexity", "sorting"),
        made_hours_ago=6 * 24, saved_hours_ago=6 * 24 - 1,
        read=("pointers",), answers={"pointers": "a"},
    ),
    GuideSpec(
        "course", "CS101 so far",
        "The whole course in eight sections, from variables to linked lists, sized by how well you know each.",
        ("Most bugs in this course are about memory: who owns it and how long it lives.",
         "Tracing by hand is the skill both exams test.",
         "Arrays index fast and insert slowly; linked lists do the opposite."),
        None, "review", "deep",
        ("variables", "controlflow", "functions", "pointers", "arrays", "recursion", "complexity", "linkedlists"),
        made_hours_ago=3 * 24, saved_hours_ago=2 * 24,
        read=("variables", "controlflow", "functions"), answers={"controlflow": "b"}, feedback="yes",
    ),
    GuideSpec(
        "hw6", "Recursion, one call at a time",
        "A short practice guide for Homework 6: how calls work, then how to trace a recursive one.",
        ("Each call has its own frame and its own copy of n.",
         "Find the base case first.",
         "Fill in return values from the bottom up."),
        "hw6", "practice", "cram", ("functions", "scope", "recursion"),
        made_hours_ago=26,
    ),
    GuideSpec(
        "final", "Data structures for the final",
        "Linked lists, stacks, hash tables and trees: the last unit before the final exam.",
        ("Pick a structure by the operation you need to be fast.",
         "A stack and a queue differ only in which end you remove from.",
         "Trees are where recursion pays off."),
        "final", "exam_prep", "standard", ("linkedlists", "stacks", "hashtables", "trees", "sorting"),
        made_hours_ago=0, generating=True,
    ),
)

CLASS = ClassData(
    key="cs101",
    course_id="rich-course-cs101",
    concepts=CONCEPTS,
    materials=MATERIALS,
    assessments=ASSESSMENTS,
    cards=CARDS,
    quizzes=QUIZZES,
    digests=DIGESTS,
    tutoring=TUTORING,
    card_sets=CARD_SETS,
    sections=SECTIONS,
    guides=GUIDES,
    earlier_exams={"Pop Quiz: Recursion": ("functions", "recursion")},
)
