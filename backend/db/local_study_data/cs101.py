"""CS101, Introduction to Computer Science: the local study dataset's first
class. Plain content; ``spec.py`` says what each field is."""
from __future__ import annotations

from db.local_study_data.cs101_concepts import (
    CONCEPTS,
    FOUNDATIONS,
    MEMORY,
    PROBLEM_SOLVING,
    STRUCTURES,
)
from db.local_study_data.cs101_guides import GUIDES, SECTIONS
from db.local_study_data.spec import (
    Assessment,
    CardSet,
    ClassData,
    Digest,
    Material,
    Quiz,
    Tutoring,
)

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
