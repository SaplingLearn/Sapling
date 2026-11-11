"""Computer Science seed pack: a sophomore's fall semester across the BU CS core.

Strength profile: confident in CS 111 (Python), solid in CS 112 (data
structures), shaky on proofs in CS 131, mid-pack in CS 210 (C + assembly).
"""
from __future__ import annotations

from textwrap import dedent

from services.account_seed.schema import (
    Assignment,
    Category,
    ChatMessage,
    Concept,
    ConceptNote,
    Course,
    Document,
    Edge,
    Flashcard,
    MajorPack,
    MasteryEvent,
    Note,
    QuizAttempt,
    QuizQuestion,
    StudyGuide,
    StudyGuideTopic,
    TutorSession,
)


def _t(text: str) -> str:
    return dedent(text).strip()


# ---------------------------------------------------------------------------
# CAS CS 111 — Introduction to Computer Science 1 (Python)
# ---------------------------------------------------------------------------

CS111 = Course(
    code="CAS CS 111",
    name="Introduction to Computer Science 1",
    department="Computer Science",
    nickname="CS 111 Python",
    color="#3B82F6",
    concepts=[
        Concept(name="Variables and Expressions", mastery=0.96,
                description="Binding names to values, operator precedence, integer vs float division (// vs /), and the % modulus operator."),
        Concept(name="Conditionals and Boolean Logic", mastery=0.88,
                description="if/elif/else chains, and/or/not, short-circuit evaluation, and writing boolean expressions that read like the spec."),
        Concept(name="Functions and Scope", mastery=0.82,
                description="Defining functions with parameters and return values; local vs global scope; why print is not the same as return."),
        Concept(name="Lists and String Slicing", mastery=0.78,
                description="Indexing and slicing sequences with s[start:stop:step], negative indices, and the fact that slicing makes a copy."),
        Concept(name="Recursion", mastery=0.63,
                description="Solving a problem by reducing it to a smaller instance of itself: a base case plus a recursive case that trusts the call."),
        Concept(name="List Comprehensions", mastery=0.56,
                description="Building lists declaratively with [expr for x in seq if cond]; LC-based alternatives to explicit loops and recursion."),
        Concept(name="Higher-Order Functions", mastery=0.37,
                description="Functions as values: lambda expressions, map, filter, and passing key= functions to max/min/sorted."),
        Concept(name="Memoization", mastery=0.21,
                description="Caching the results of recursive calls in a dictionary so overlapping subproblems (fib, LCS, change-making) are solved once."),
        Concept(name="Binary Representation", mastery=0.06,
                description="Representing integers in base 2, converting between decimal and binary, and binary addition as used in logic circuits."),
        Concept(name="Classes and Objects", mastery=0.0,
                description="Object-oriented Python: defining a class, __init__, self, methods, and __repr__ for printing objects."),
    ],
    edges=[
        Edge(source="Variables and Expressions", target="Functions and Scope", relationship="prerequisite", strength=0.8),
        Edge(source="Functions and Scope", target="Recursion", relationship="prerequisite", strength=0.9),
        Edge(source="Conditionals and Boolean Logic", target="Recursion", relationship="prerequisite", strength=0.7),
        Edge(source="Recursion", target="Memoization", relationship="builds_on", strength=0.9),
        Edge(source="Lists and String Slicing", target="List Comprehensions", relationship="builds_on", strength=0.8),
        Edge(source="Functions and Scope", target="Higher-Order Functions", relationship="prerequisite", strength=0.75),
        Edge(source="Higher-Order Functions", target="List Comprehensions", relationship="related", strength=0.6),
        Edge(source="Functions and Scope", target="Classes and Objects", relationship="prerequisite", strength=0.7),
        Edge(source="Recursion", target="Binary Representation", relationship="related", strength=0.4),
    ],
    mastery_events=[
        MasteryEvent(concept="Recursion", delta=0.12, reason="Finished PS3 use-it-or-lose-it problems"),
        MasteryEvent(concept="Higher-Order Functions", delta=-0.08, reason="Missed map/filter questions on quiz"),
        MasteryEvent(concept="List Comprehensions", delta=0.1, reason="Rewrote PS4 loops as comprehensions"),
        MasteryEvent(concept="Memoization", delta=0.06, reason="Tutor session on caching fib calls"),
        MasteryEvent(concept="Functions and Scope", delta=0.05, reason="Midterm 1 function-tracing section"),
    ],
    categories=[
        Category(name="Problem Sets", weight=0.4, drop_lowest=1),
        Category(name="Labs", weight=0.15),
        Category(name="Exams", weight=0.45),
    ],
    assignments=[
        Assignment(title="PS1: Python Basics and String Indexing", category="Problem Sets", type="homework",
                   due_offset_days=9, points_possible=50, points_earned=48),
        Assignment(title="Lab 3: Tracing Code in Python Tutor", category="Labs", type="homework",
                   due_offset_days=19, points_possible=20, points_earned=20),
        Assignment(title="PS3: Recursion and Use-It-or-Lose-It", category="Problem Sets", type="homework",
                   due_offset_days=31, points_possible=50, points_earned=42),
        Assignment(title="PS4: List Comprehensions and Lambda", category="Problem Sets", type="homework",
                   due_offset_days=44, points_possible=50, points_earned=39),
        Assignment(title="Midterm Exam 1", category="Exams", type="exam",
                   due_offset_days=52, points_possible=100, points_earned=86, is_midterm=True),
        Assignment(title="PS6: Memoization and Dynamic Programming", category="Problem Sets", type="homework",
                   due_offset_days=72, points_possible=50),
        Assignment(title="Lab 10: Writing a Board Class", category="Labs", type="homework",
                   due_offset_days=88, points_possible=20),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=108, points_possible=150),
    ],
    notes=[
        Note(
            title="Recursion checklist (from lecture 9)",
            tags=["recursion", "midterm"],
            concepts=["Recursion", "Functions and Scope", "Conditionals and Boolean Logic"],
            body=_t("""
                ## How to write a recursive function

                1. **Base case first.** What is the smallest input? Usually `[]`, `''`, or `0`. Return the answer directly.
                2. **Recursive case.** Peel off one piece (`s[0]` / `s[1:]`) and *trust* the recursive call on the rest.
                3. **Combine.** Use the result of the call: `return s[0] + rest` or `return 1 + rest`.

                ```python
                def num_vowels(s):
                    if s == '':
                        return 0
                    rest = num_vowels(s[1:])
                    if s[0] in 'aeiou':
                        return 1 + rest
                    return rest
                ```

                ### Use-it-or-lose-it
                For subset problems, make TWO calls: one that *uses* the first element and one that *loses* it, then pick the better result.
                Prof said: "if you're stuck, draw the call tree for a 3-element list." That actually helped on PS3 #4.

                **Common bug I keep making:** forgetting to `return` the recursive call, so the function returns `None`.
            """),
        ),
        Note(
            title="map / filter / lambda cheat sheet",
            tags=["higher-order", "review"],
            concepts=["Higher-Order Functions", "List Comprehensions"],
            body=_t("""
                ## Lambda
                `lambda x: x * 2` is an anonymous function with ONE expression and no `return` keyword.

                ## map and filter
                - `list(map(f, seq))` applies `f` to every element.
                - `list(filter(pred, seq))` keeps elements where `pred(x)` is truthy.
                - Both return iterators in Python 3, so wrap them in `list(...)` before printing.

                ## Same thing with comprehensions
                | map/filter | comprehension |
                |---|---|
                | `map(lambda x: x**2, nums)` | `[x**2 for x in nums]` |
                | `filter(lambda x: x > 0, nums)` | `[x for x in nums if x > 0]` |

                ## key= functions
                `max(words, key=len)` returns the longest *word*, not its length. On the quiz I picked the number. Remember: key only changes how things are **compared**.

                TODO: redo the "best word" problem from lecture with `max(scored, key=lambda pair: pair[0])`.
            """),
        ),
    ],
    documents=[
        Document(
            file_name="cs111-syllabus.pdf",
            category="syllabus",
            summary="CS 111 course syllabus: Python-based introduction covering functional problem solving, recursion, loops, binary data, and OOP, with weekly problem sets, labs, two midterms and a final.",
            concept_notes=[
                ConceptNote(name="Grading", description="Problem sets 40% (lowest dropped), labs 15%, exams 45%."),
                ConceptNote(name="Late policy", description="Problem sets accepted up to 24 hours late for 20% off; no late labs."),
                ConceptNote(name="Collaboration", description="Pair programming allowed on designated problems only; name your partner in the header."),
                ConceptNote(name="Recursion", description="Weeks 3-6 focus on recursive problem solving, including use-it-or-lose-it."),
            ],
            extracted_text=_t("""
                CAS CS 111: Introduction to Computer Science 1
                Boston University, Fall Semester

                Course Description
                This course introduces computational problem solving using the Python programming language. Topics include functional programming, recursion, list comprehensions, higher-order functions, the representation of data in binary, loops and the imperative style, and an introduction to object-oriented programming. No prior programming experience is assumed.

                Learning Objectives
                By the end of the course students should be able to decompose a problem into functions, write and trace recursive solutions, reason about the efficiency of simple algorithms, and design small classes.

                Course Components
                Problem Sets (40%): weekly, due Thursdays at 11:59 p.m. The lowest problem set score is dropped.
                Labs (15%): attendance and completion of the weekly lab exercise.
                Exams (45%): Midterm 1, Midterm 2, and a cumulative final exam.

                Tentative Schedule
                Weeks 1-2: Python basics, strings and lists, functions
                Weeks 3-6: Recursion, use-it-or-lose-it, list comprehensions, lambda
                Week 7: Midterm Exam 1
                Weeks 8-9: Memoization and dynamic programming; binary numbers and logic circuits
                Weeks 10-11: Loops, nested loops, 2-D lists
                Weeks 12-14: Classes, objects, and a Connect Four project

                Academic Conduct
                Collaboration is permitted only where an assignment explicitly allows it. Copying code from classmates or online sources is a violation of the BU Academic Conduct Code.
            """),
        ),
        Document(
            file_name="cs111-lecture09-recursion.pdf",
            category="lecture_notes",
            summary="Lecture 9 slides on recursive design: base cases, the recursive leap of faith, tracing call stacks, and the use-it-or-lose-it strategy for subset problems.",
            concept_notes=[
                ConceptNote(name="Base case", description="The input small enough to answer directly, without another call."),
                ConceptNote(name="Recursive leap of faith", description="Assume the call on the smaller input is correct and focus on combining its result."),
                ConceptNote(name="Use-it-or-lose-it", description="Explore both including and excluding the first element, then choose the better result."),
                ConceptNote(name="Call stack", description="Each recursive call gets its own frame with its own local variables."),
            ],
            extracted_text=_t("""
                Lecture 9: Designing Recursive Functions

                Recall: a recursive function calls itself on a smaller version of the same problem.
                Every recursive function needs (1) a base case and (2) a recursive case that makes progress toward the base case.

                Example: computing the length of a list
                def mylen(lst):
                    if lst == []:
                        return 0
                    else:
                        len_rest = mylen(lst[1:])
                        return 1 + len_rest

                Tracing mylen([7, 3, 5]):
                mylen([7,3,5]) -> 1 + mylen([3,5]) -> 1 + 1 + mylen([5]) -> 1 + 1 + 1 + mylen([]) -> 3
                Each call has its own stack frame. The frames are popped in reverse order as values are returned.

                The Recursive Leap of Faith
                Do not trace every call in your head. Assume the recursive call returns the right answer for the rest of the list, and ask: how do I use that answer to solve the whole problem?

                Use-It-or-Lose-It
                Problem: given a list of item weights and a capacity, find the largest total weight that fits.
                use_it = values[0] + best(values[1:], cap - values[0])
                lose_it = best(values[1:], cap)
                return max(use_it, lose_it)
                Remember to check that values[0] <= cap before using it.

                Next time: list comprehensions and lambda.
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="What two parts must every recursive function have?",
                  back="A base case that returns directly, and a recursive case that calls the function on a smaller input."),
        Flashcard(front="What does 'hello'[1:4] evaluate to?", back="'ell' — the stop index 4 is excluded."),
        Flashcard(front="What is the difference between 7 / 2 and 7 // 2 in Python 3?", back="7 / 2 is 3.5 (float division); 7 // 2 is 3 (floor division)."),
        Flashcard(front="Write a list comprehension for the squares of the odd numbers in range(10).",
                  back="[x**2 for x in range(10) if x % 2 == 1]  ->  [1, 9, 25, 49, 81]"),
        Flashcard(front="What does max(['pear', 'fig', 'banana'], key=len) return?", back="'banana' — key changes how items are compared, not what is returned."),
        Flashcard(front="Why does naive recursive fib(n) run in exponential time?",
                  back="It recomputes the same subproblems repeatedly; the call tree roughly doubles at every level, O(2^n)."),
        Flashcard(front="How does memoization fix fib?", back="Store each fib(k) in a dictionary the first time it is computed and look it up afterwards, making it O(n)."),
        Flashcard(front="What is the use-it-or-lose-it strategy?", back="Make one recursive call that includes the first element and one that excludes it, then combine (often with max)."),
    ],
    study_guide=StudyGuide(
        overview="Midterm 1 covers weeks 1-6: Python fundamentals, functions, string/list slicing, recursion (including use-it-or-lose-it), list comprehensions and lambda. Expect code tracing, short write-a-function problems, and one longer recursion problem.",
        topics=[
            StudyGuideTopic(name="Tracing functions and slices",
                            importance="About a third of the exam is predicting output; slicing off-by-one errors are the most common lost points.",
                            concepts=["Variables and Expressions", "Functions and Scope", "Lists and String Slicing"]),
            StudyGuideTopic(name="Writing recursive functions",
                            importance="The long-answer problem is always recursive; partial credit goes to a correct base case and a sensible recursive call.",
                            concepts=["Recursion", "Conditionals and Boolean Logic"]),
            StudyGuideTopic(name="Comprehensions and lambda",
                            importance="Short questions ask you to convert between a loop, map/filter, and a list comprehension.",
                            concepts=["List Comprehensions", "Higher-Order Functions"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Recursion", difficulty="medium", days_ago=24,
            questions=[
                QuizQuestion(
                    question="Given def mystery(n): return 0 if n == 0 else n + mystery(n - 1), what does mystery(4) return?",
                    options=["4", "10", "24", "It recurses forever"], correct_answer="10",
                    explanation="4 + 3 + 2 + 1 + 0 = 10; the base case n == 0 stops the recursion."),
                QuizQuestion(
                    question="Which is the correct base case for a recursive function rem_all(elem, values) that removes every occurrence of elem from a list?",
                    options=["if values == []: return []", "if values[0] == elem: return []", "if elem == []: return values", "if len(values) == 1: return values"],
                    correct_answer="if values == []: return []",
                    explanation="The smallest input is the empty list, from which there is nothing to remove."),
                QuizQuestion(
                    question="In a use-it-or-lose-it solution, what does the 'lose it' call do?",
                    options=["Recurses on the rest of the list without the first element",
                             "Removes the largest element and recurses",
                             "Returns the first element immediately",
                             "Recurses on the whole list again with a smaller capacity"],
                    correct_answer="Recurses on the rest of the list without the first element",
                    explanation="'Lose it' skips values[0] entirely and solves the subproblem on values[1:]."),
                QuizQuestion(
                    question="What happens if a recursive function computes its result but forgets the return keyword in the recursive case?",
                    options=["Python raises a SyntaxError", "The function returns None", "The function returns the base case value", "The recursion never terminates"],
                    correct_answer="The function returns None",
                    explanation="A Python function without a return statement on that path returns None, which then breaks the caller's arithmetic."),
            ],
            correct=[0, 1, 3],
        ),
        QuizAttempt(
            concept="Higher-Order Functions", difficulty="medium", days_ago=11,
            questions=[
                QuizQuestion(
                    question="What does list(map(lambda x: x * 2, [1, 2, 3])) evaluate to?",
                    options=["[2, 4, 6]", "[1, 2, 3, 1, 2, 3]", "6", "[1, 4, 9]"], correct_answer="[2, 4, 6]",
                    explanation="map applies the lambda to each element."),
                QuizQuestion(
                    question="What does list(filter(lambda s: len(s) > 3, ['cat', 'house', 'ox', 'tree'])) evaluate to?",
                    options=["['house', 'tree']", "['cat', 'ox']", "[False, True, False, True]", "['house']"],
                    correct_answer="['house', 'tree']",
                    explanation="filter keeps the elements for which the predicate is True; 'tree' has 4 letters."),
                QuizQuestion(
                    question="Which statement about lambda expressions in Python is true?",
                    options=["A lambda body can contain only a single expression", "A lambda must use the return keyword",
                             "A lambda cannot take more than one parameter", "A lambda is evaluated as soon as it is defined"],
                    correct_answer="A lambda body can contain only a single expression",
                    explanation="lambda x, y: x + y is legal; statements and return are not."),
                QuizQuestion(
                    question="What does max(['pear', 'fig', 'banana'], key=len) return?",
                    options=["6", "'banana'", "'pear'", "'fig'"], correct_answer="'banana'",
                    explanation="key=len compares by length but max still returns the element itself."),
            ],
            correct=[0, 2],
        ),
        QuizAttempt(
            concept="Memoization", difficulty="hard", days_ago=3,
            questions=[
                QuizQuestion(
                    question="What is the running time of the naive recursive Fibonacci function fib(n) = fib(n-1) + fib(n-2)?",
                    options=["O(n)", "O(n log n)", "O(n^2)", "O(2^n)"], correct_answer="O(2^n)",
                    explanation="Each call spawns two more and subproblems are recomputed, so the call tree is exponential."),
                QuizQuestion(
                    question="In a memoized function, what is stored in the memo dictionary?",
                    options=["The results of previous calls, keyed by their arguments", "Every line of code that has run",
                             "Only the base case values", "The call stack frames"],
                    correct_answer="The results of previous calls, keyed by their arguments",
                    explanation="Before computing, check whether the argument is already a key; if so, return the cached value."),
                QuizQuestion(
                    question="Where should the memo lookup happen in a memoized recursive function?",
                    options=["Before any recursive calls are made", "Only inside the base case",
                             "After both recursive calls return", "At the very end, just before returning"],
                    correct_answer="Before any recursive calls are made",
                    explanation="Checking first is what avoids repeating the expensive recursive work."),
            ],
            correct=[0],
        ),
    ],
    session=TutorSession(
        name="Why is my fib so slow?",
        topic="Memoization",
        mode="socratic",
        summary_bullets=[
            "Drew the call tree for fib(5) and found fib(3) is computed twice and fib(2) three times.",
            "Connected repeated subproblems to the exponential running time.",
            "Sketched a memo dictionary checked before recursing; next step is applying it to PS6 LCS.",
        ],
        messages=[
            ChatMessage(role="user", content="My recursive fib works but fib(35) takes forever. PS6 says to use memoization but I don't really get what it's fixing."),
            ChatMessage(role="assistant", content="Let's find out what's slow first. If you draw the call tree for fib(5), which calls does fib(5) make, and which calls do those make? Try listing them level by level."),
            ChatMessage(role="user", content="fib(5) calls fib(4) and fib(3). fib(4) calls fib(3) and fib(2). fib(3) calls fib(2) and fib(1)... oh, fib(3) shows up twice."),
            ChatMessage(role="assistant", content="Exactly. And fib(2) appears three times, fib(1) five times. Each repeat redoes an entire subtree. If you could remember an answer the first time you computed it, what would you need to store, and what would you use to look it up?"),
            ChatMessage(role="user", content="Store the answer for each n? So like a dictionary where the key is n and the value is fib(n)?"),
            ChatMessage(role="assistant", content="That's the whole idea. Pass a dict called memo along; at the top of the function check `if n in memo: return memo[n]`, otherwise compute the result, save it with `memo[n] = result`, and return it. Now each fib(k) is computed once, so the work drops from O(2^n) to O(n). For PS6's LCS problem, what would the key need to be, since that function takes two strings?"),
            ChatMessage(role="user", content="Both strings, so maybe a tuple (s1, s2) as the key?"),
            ChatMessage(role="assistant", content="Yes, a tuple works because it's hashable, and a list wouldn't be. Try it on the PS6 test cases and compare the timing with and without the memo."),
        ],
    ),
)


# ---------------------------------------------------------------------------
# CAS CS 112 — Introduction to Computer Science 2 (data structures)
# ---------------------------------------------------------------------------

CS112 = Course(
    code="CAS CS 112",
    name="Introduction to Computer Science 2",
    department="Computer Science",
    nickname="CS 112 Data Structures",
    color="#10B981",
    concepts=[
        Concept(name="Java Classes and Interfaces", mastery=0.84,
                description="Encapsulation with private fields, constructors, interfaces like Bag<T> and List<T>, and generics in Java."),
        Concept(name="Arrays and ArrayLists", mastery=0.96,
                description="Fixed-size arrays vs resizable array-backed lists; O(1) indexing and the cost of shifting on insert/remove."),
        Concept(name="Linked Lists", mastery=0.79,
                description="Nodes with a next reference; insertion and deletion by relinking, traversal with a trailing pointer, and dummy head nodes."),
        Concept(name="Stacks and Queues", mastery=0.71,
                description="LIFO and FIFO abstract data types; array and linked implementations; push/pop/peek and insert/remove in O(1)."),
        Concept(name="Big-O Analysis", mastery=0.66,
                description="Counting operations as a function of n and keeping the dominant term: O(1), O(log n), O(n), O(n log n), O(n^2)."),
        Concept(name="Recursion and Backtracking", mastery=0.52,
                description="Recursive search that builds a partial solution, tests constraints, and undoes choices: N-Queens and Sudoku."),
        Concept(name="Sorting Algorithms", mastery=0.58,
                description="Selection, insertion, Shell, bubble, quicksort and mergesort: how each works and its best/average/worst-case time."),
        Concept(name="Binary Search Trees", mastery=0.33,
                description="Ordered binary trees where left < root < right; search, insert, and the three cases of delete; O(h) operations."),
        Concept(name="Hash Tables", mastery=0.17,
                description="Mapping keys to array slots with a hash function; collisions via separate chaining or open addressing; load factor."),
        Concept(name="Heaps and Priority Queues", mastery=0.04,
                description="Complete binary trees stored in arrays with the heap property; sift-down/sift-up and heapsort."),
    ],
    edges=[
        Edge(source="Java Classes and Interfaces", target="Linked Lists", relationship="prerequisite", strength=0.7),
        Edge(source="Linked Lists", target="Stacks and Queues", relationship="builds_on", strength=0.8),
        Edge(source="Arrays and ArrayLists", target="Stacks and Queues", relationship="builds_on", strength=0.6),
        Edge(source="Big-O Analysis", target="Sorting Algorithms", relationship="related", strength=0.8),
        Edge(source="Recursion and Backtracking", target="Sorting Algorithms", relationship="prerequisite", strength=0.6),
        Edge(source="Recursion and Backtracking", target="Binary Search Trees", relationship="prerequisite", strength=0.8),
        Edge(source="Arrays and ArrayLists", target="Hash Tables", relationship="prerequisite", strength=0.7),
        Edge(source="Binary Search Trees", target="Heaps and Priority Queues", relationship="related", strength=0.5),
    ],
    mastery_events=[
        MasteryEvent(concept="Linked Lists", delta=0.14, reason="PS4 linked-list methods passed all tests"),
        MasteryEvent(concept="Big-O Analysis", delta=-0.05, reason="Confused best and worst case of quicksort"),
        MasteryEvent(concept="Binary Search Trees", delta=0.08, reason="Practiced BST delete with two children"),
        MasteryEvent(concept="Recursion and Backtracking", delta=0.1, reason="Got N-Queens backtracking working"),
    ],
    categories=[
        Category(name="Problem Sets", weight=0.5),
        Category(name="Exams", weight=0.5),
    ],
    assignments=[
        Assignment(title="PS1: Java Review and ArrayBag", category="Problem Sets", type="homework",
                   due_offset_days=12, points_possible=100, points_earned=94),
        Assignment(title="PS2: Recursive Backtracking (N-Queens)", category="Problem Sets", type="homework",
                   due_offset_days=25, points_possible=100, points_earned=85),
        Assignment(title="PS3: Sorting and Big-O", category="Problem Sets", type="homework",
                   due_offset_days=38, points_possible=100, points_earned=88),
        Assignment(title="PS4: Linked Lists and LLList", category="Problem Sets", type="homework",
                   due_offset_days=49, points_possible=100, points_earned=96),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=56, points_possible=100, points_earned=80, is_midterm=True),
        Assignment(title="PS5: Stacks, Queues and BSTs", category="Problem Sets", type="homework",
                   due_offset_days=76, points_possible=100),
        Assignment(title="PS6: Hash Tables and Heaps", category="Problem Sets", type="homework",
                   due_offset_days=95, points_possible=100),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=109, points_possible=150),
    ],
    notes=[
        Note(
            title="Sorting algorithms comparison",
            tags=["sorting", "big-o", "midterm"],
            concepts=["Sorting Algorithms", "Big-O Analysis"],
            body=_t("""
                ## Running times (n = array length)

                | Algorithm | Best | Average | Worst | Extra memory |
                |---|---|---|---|---|
                | Selection | O(n^2) | O(n^2) | O(n^2) | O(1) |
                | Insertion | O(n) | O(n^2) | O(n^2) | O(1) |
                | Shell | O(n log n) | ~O(n^1.5) | O(n^1.5) | O(1) |
                | Quicksort | O(n log n) | O(n log n) | O(n^2) | O(log n) stack |
                | Mergesort | O(n log n) | O(n log n) | O(n log n) | O(n) |

                ### Things to remember
                - Insertion sort is **O(n)** on an already-sorted array, since each element only gets compared once.
                - Quicksort's worst case happens when the pivot is always the smallest/largest element (e.g. sorted input with first-element pivot).
                - Mergesort is the only one here that is O(n log n) in every case, but it needs a temp array.
                - Selection sort always does n(n-1)/2 comparisons no matter what.

                I lost points on PS3 for saying quicksort is O(n log n) worst case. It is NOT.
            """),
        ),
        Note(
            title="Linked list traversal patterns",
            tags=["linked-lists", "java"],
            concepts=["Linked Lists", "Java Classes and Interfaces", "Stacks and Queues"],
            body=_t("""
                ## Basic traversal
                ```java
                Node trav = head;
                while (trav != null) {
                    // do something with trav.val
                    trav = trav.next;
                }
                ```

                ## Trailing pointer (for deletes)
                Keep `trail` one node behind `trav` so you can do `trail.next = trav.next` to unlink.

                ## Dummy head node
                LLList uses a dummy head so inserting at position 0 is not a special case. `getNode(-1)` returns the dummy.

                ## Costs
                - get(i): O(i) because you have to walk there, vs O(1) for ArrayList.
                - addFirst: O(1).
                - A linked stack pushes and pops at the head, both O(1). A linked queue keeps a `rear` reference too.

                Draw boxes and arrows before writing ANY code. Every NullPointerException I hit on PS4 was a case I didn't draw (empty list or last node).
            """),
        ),
    ],
    documents=[
        Document(
            file_name="cs112-syllabus.pdf",
            category="syllabus",
            summary="CS 112 syllabus: data structures and algorithms in Java, covering recursion, sorting, linked lists, stacks and queues, trees, heaps and hash tables, graded on problem sets and exams.",
            concept_notes=[
                ConceptNote(name="Language", description="All assignments are written in Java using VS Code."),
                ConceptNote(name="Grading", description="Problem sets 50%, midterm and final exam 50% combined."),
                ConceptNote(name="Exam rule", description="You must pass the exam portion of the course to pass CS 112."),
            ],
            extracted_text=_t("""
                CAS CS 112: Introduction to Computer Science II
                Boston University

                Overview
                This course covers the fundamental data structures and algorithms used in computer science and the techniques for analyzing their efficiency. Programming assignments are completed in Java.

                Prerequisite: CAS CS 111 or equivalent experience with Python.

                Topics
                Java fundamentals; classes, interfaces and generics
                Recursion and recursive backtracking
                Sorting algorithms and Big-O notation
                Linked lists; the List abstract data type
                Stacks and queues
                Binary trees and binary search trees; balanced search trees
                Heaps and priority queues
                Hash tables
                Graphs (time permitting)

                Grading
                Problem sets: 50%
                Midterm exam: 20%
                Final exam: 30%
                Note: you must earn a passing average on the exams to pass the course.

                Problem Sets
                Each problem set has a written part (Part I) and a programming part (Part II). Submit through Gradescope. Late submissions within 24 hours receive a 10% deduction; after that, no credit.

                Office Hours
                Held daily in the CS lab. Please bring a specific question and the code you have tried.

                Textbook
                Course notes are posted on the course website; no textbook purchase is required.
            """),
        ),
        Document(
            file_name="cs112-lecture14-binary-search-trees.pdf",
            category="lecture_notes",
            summary="Lecture notes on binary search trees: the BST ordering property, search and insert, the three deletion cases, and why performance depends on tree height.",
            concept_notes=[
                ConceptNote(name="BST property", description="Every key in the left subtree is less than the root and every key in the right subtree is greater."),
                ConceptNote(name="Delete with two children", description="Replace the node's key with its inorder successor (smallest in right subtree), then delete the successor."),
                ConceptNote(name="Tree height", description="Operations are O(h); h is O(log n) when balanced and O(n) in the worst case."),
                ConceptNote(name="Inorder traversal", description="Visits a BST's keys in sorted order."),
            ],
            extracted_text=_t("""
                Binary Search Trees

                A binary search tree is a binary tree in which, for every node k:
                - all keys in k's left subtree are less than k's key
                - all keys in k's right subtree are greater than or equal to k's key

                An inorder traversal of a BST visits the keys in sorted order.

                Searching
                Start at the root. If the key equals the root's key, we're done. If it is smaller, search the left subtree; otherwise search the right subtree. Each comparison moves one level down the tree, so search is O(h), where h is the height.

                Inserting
                Search for the key; when we fall off the tree (reach null), attach a new leaf there. We keep a trailing reference to the parent so we can link the new node in.

                Deleting: three cases
                Case 1: the node has no children. Set the parent's reference to null.
                Case 2: the node has one child. Replace the node with its child.
                Case 3: the node has two children. Find the node's inorder successor, the smallest key in its right subtree. Copy the successor's key and data into the node, then delete the successor, which has at most one child.

                Efficiency
                In a balanced tree with n nodes, h = O(log n). If keys are inserted in sorted order, the tree degenerates into a linked list and h = O(n).
                Next lecture: balanced trees (2-3 trees) keep h logarithmic.
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="Big-O of get(i) on a linked list vs an ArrayList?", back="Linked list O(i) / O(n) worst case; ArrayList O(1)."),
        Flashcard(front="When is quicksort O(n^2)?", back="When the pivot is repeatedly the smallest or largest element, e.g. already-sorted input with the first element as pivot."),
        Flashcard(front="Which sort is O(n) in the best case?", back="Insertion sort, on an already-sorted array."),
        Flashcard(front="What three steps does every backtracking method repeat?", back="Make a choice, recurse if the partial solution is valid, then undo the choice (backtrack)."),
        Flashcard(front="How do you delete a BST node with two children?", back="Replace its key with its inorder successor's key, then delete the successor node."),
        Flashcard(front="What traversal of a BST visits keys in sorted order?", back="Inorder: left subtree, root, right subtree."),
        Flashcard(front="What is a hash table's load factor?", back="Number of keys divided by table size; when it gets too high, collisions increase and the table should be resized."),
        Flashcard(front="Stack vs queue?", back="Stack is LIFO (push/pop at the top). Queue is FIFO (insert at rear, remove from front)."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers Java classes and interfaces, recursion and backtracking, the sorting algorithms and their Big-O, and linked lists. Expect written traces (show the array after each pass), Big-O questions, and two code-writing problems in Java.",
        topics=[
            StudyGuideTopic(name="Sorting traces and running times",
                            importance="Heavily weighted: tracing passes of selection/insertion/quicksort and stating best/worst cases.",
                            concepts=["Sorting Algorithms", "Big-O Analysis"]),
            StudyGuideTopic(name="Linked list methods",
                            importance="One long problem asks you to write a method on a linked list without using get().",
                            concepts=["Linked Lists", "Java Classes and Interfaces"]),
            StudyGuideTopic(name="Recursive backtracking",
                            importance="A template-completion problem similar to N-Queens; know where the undo step goes.",
                            concepts=["Recursion and Backtracking"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Sorting Algorithms", difficulty="medium", days_ago=30,
            questions=[
                QuizQuestion(
                    question="What is the worst-case running time of quicksort?",
                    options=["O(n)", "O(n log n)", "O(n^2)", "O(log n)"], correct_answer="O(n^2)",
                    explanation="Bad pivots split the array into sizes 0 and n-1 every time."),
                QuizQuestion(
                    question="Which algorithm runs in O(n log n) time in the best, average and worst case?",
                    options=["Quicksort", "Mergesort", "Insertion sort", "Selection sort"], correct_answer="Mergesort",
                    explanation="Mergesort always splits in half and merges in linear time."),
                QuizQuestion(
                    question="After the first pass of selection sort on [5, 2, 8, 1, 9], what is the array?",
                    options=["[1, 2, 8, 5, 9]", "[2, 5, 8, 1, 9]", "[1, 5, 2, 8, 9]", "[2, 5, 1, 8, 9]"],
                    correct_answer="[1, 2, 8, 5, 9]",
                    explanation="Selection sort swaps the smallest element (1) into position 0."),
                QuizQuestion(
                    question="Why is insertion sort fast on an almost-sorted array?",
                    options=["Each element moves only a short distance, so few comparisons are needed",
                             "It uses a pivot to split the array in half",
                             "It skips the inner loop entirely",
                             "It copies the array into a temporary buffer first"],
                    correct_answer="Each element moves only a short distance, so few comparisons are needed",
                    explanation="The inner loop stops as soon as it finds an element that is not larger."),
            ],
            correct=[1, 2, 3],
        ),
        QuizAttempt(
            concept="Binary Search Trees", difficulty="hard", days_ago=6,
            questions=[
                QuizQuestion(
                    question="In a BST, where is a node's inorder successor if the node has a right child?",
                    options=["The leftmost node of its right subtree", "Its parent", "The rightmost node of its left subtree", "The root"],
                    correct_answer="The leftmost node of its right subtree",
                    explanation="It is the smallest key larger than the node's key."),
                QuizQuestion(
                    question="Inserting 10, 20, 30, 40, 50 in that order into an empty BST gives a tree of what height?",
                    options=["2", "3", "4", "5"], correct_answer="4",
                    explanation="Sorted inserts form a chain of 5 nodes; with a single node at height 0, the height is 4."),
                QuizQuestion(
                    question="What is the worst-case time to search a BST with n nodes?",
                    options=["O(1)", "O(log n)", "O(n)", "O(n log n)"], correct_answer="O(n)",
                    explanation="A degenerate (linked-list-shaped) tree has height n - 1."),
            ],
            correct=[0],
        ),
    ],
    session=TutorSession(
        name="BST delete, case 3",
        topic="Binary Search Trees",
        mode="expository",
        summary_bullets=[
            "Reviewed the three BST deletion cases.",
            "Worked through deleting a node with two children using the inorder successor.",
            "Clarified why the successor has at most one child.",
        ],
        messages=[
            ChatMessage(role="user", content="I get deleting a leaf, but how do you delete a node in a BST that has two children? Lecture went fast."),
            ChatMessage(role="assistant", content="You can't just unlink it, because two subtrees would need one parent slot. Instead, you swap in a replacement key that keeps the BST property: the inorder successor, which is the smallest key in the node's right subtree. Go right once, then left as far as possible."),
            ChatMessage(role="user", content="So if I delete 26 from a tree where 26's right subtree is 35 with left child 30, the successor is 30?"),
            ChatMessage(role="assistant", content="Right, as long as 30 has no left child. Copy 30's key and data into the node holding 26. Now there are two 30s, so delete the original 30 from the right subtree. Every key on the left is still less than 30 and every key on the right is still greater, so the ordering holds."),
            ChatMessage(role="user", content="And deleting the second 30 is easy because...?"),
            ChatMessage(role="assistant", content="Because the successor is the leftmost node, it can't have a left child, so it has zero or one child. That means removing it is always case 1 or case 2, never another case 3. In code, you link the successor's parent to the successor's right child."),
        ],
    ),
)


# ---------------------------------------------------------------------------
# CAS CS 131 — Combinatoric Structures (discrete math)
# ---------------------------------------------------------------------------

CS131 = Course(
    code="CAS CS 131",
    name="Combinatoric Structures",
    department="Computer Science",
    nickname="CS 131 Discrete",
    color="#F59E0B",
    concepts=[
        Concept(name="Propositional Logic", mastery=0.96,
                description="Connectives, truth tables, implication and its contrapositive, logical equivalence, De Morgan's laws."),
        Concept(name="Sets and Set Operations", mastery=0.77,
                description="Union, intersection, difference, complement, power sets, Cartesian products and set-builder notation."),
        Concept(name="Predicate Logic and Quantifiers", mastery=0.6,
                description="Universal and existential quantifiers, nested quantifiers, and negating quantified statements."),
        Concept(name="Functions and Relations", mastery=0.48,
                description="Injective, surjective and bijective functions; relations that are reflexive, symmetric, transitive; equivalence relations."),
        Concept(name="Proof Techniques", mastery=0.42,
                description="Direct proof, proof by contrapositive, and proof by contradiction (e.g. the irrationality of sqrt(2))."),
        Concept(name="Mathematical Induction", mastery=0.29,
                description="Proving P(n) for all n >= n0 with a base case and an inductive step P(k) -> P(k+1); strong induction."),
        Concept(name="Counting Principles", mastery=0.36,
                description="The product rule, sum rule, and inclusion-exclusion |A u B| = |A| + |B| - |A n B|."),
        Concept(name="Permutations and Combinations", mastery=0.15,
                description="P(n, r) = n!/(n-r)! ordered selections; C(n, r) = n!/(r!(n-r)!) unordered; binomial coefficients."),
        Concept(name="Pigeonhole Principle", mastery=0.07,
                description="If n+1 objects go into n boxes, some box holds at least two; generalized form ceil(N/k)."),
        Concept(name="Discrete Probability", mastery=0.0,
                description="Sample spaces, events, P(E) = |E|/|S| for equally likely outcomes, and conditional probability."),
    ],
    edges=[
        Edge(source="Propositional Logic", target="Predicate Logic and Quantifiers", relationship="prerequisite", strength=0.9),
        Edge(source="Predicate Logic and Quantifiers", target="Proof Techniques", relationship="prerequisite", strength=0.7),
        Edge(source="Proof Techniques", target="Mathematical Induction", relationship="prerequisite", strength=0.8),
        Edge(source="Sets and Set Operations", target="Functions and Relations", relationship="prerequisite", strength=0.75),
        Edge(source="Counting Principles", target="Permutations and Combinations", relationship="builds_on", strength=0.85),
        Edge(source="Counting Principles", target="Pigeonhole Principle", relationship="related", strength=0.5),
        Edge(source="Permutations and Combinations", target="Discrete Probability", relationship="prerequisite", strength=0.8),
        Edge(source="Sets and Set Operations", target="Counting Principles", relationship="prerequisite", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="Mathematical Induction", delta=-0.1, reason="Inductive step on HW3 used P(k+1) to prove P(k+1)"),
        MasteryEvent(concept="Proof Techniques", delta=0.07, reason="Office hours on proof by contradiction"),
        MasteryEvent(concept="Propositional Logic", delta=0.12, reason="Perfect score on truth-table section of quiz"),
        MasteryEvent(concept="Permutations and Combinations", delta=0.05, reason="Started counting practice set"),
    ],
    categories=[
        Category(name="Homework", weight=0.35, drop_lowest=1),
        Category(name="Quizzes", weight=0.1),
        Category(name="Exams", weight=0.55),
    ],
    assignments=[
        Assignment(title="HW1: Propositional Logic and Truth Tables", category="Homework", type="homework",
                   due_offset_days=10, points_possible=40, points_earned=37),
        Assignment(title="HW2: Quantifiers and Set Identities", category="Homework", type="homework",
                   due_offset_days=22, points_possible=40, points_earned=33),
        Assignment(title="Quiz 1: Logic and Sets", category="Quizzes", type="quiz",
                   due_offset_days=27, points_possible=20, points_earned=17),
        Assignment(title="HW3: Direct Proof and Contradiction", category="Homework", type="homework",
                   due_offset_days=36, points_possible=40, points_earned=27),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=50, points_possible=100, points_earned=71, is_midterm=True),
        Assignment(title="HW5: Induction and Strong Induction", category="Homework", type="homework",
                   due_offset_days=68, points_possible=40),
        Assignment(title="HW6: Counting and the Pigeonhole Principle", category="Homework", type="homework",
                   due_offset_days=85, points_possible=40),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=107, points_possible=150),
    ],
    notes=[
        Note(
            title="Induction proof template",
            tags=["induction", "proofs"],
            concepts=["Mathematical Induction", "Proof Techniques"],
            body=_t("""
                ## Structure (write ALL of these, graders look for each)

                **Claim:** For all integers n >= 1, P(n): 1 + 2 + ... + n = n(n+1)/2.

                **Base case (n = 1):** LHS = 1, RHS = 1(2)/2 = 1. True.

                **Inductive hypothesis:** Assume P(k) holds for some arbitrary k >= 1, i.e. 1 + ... + k = k(k+1)/2.

                **Inductive step:** Show P(k+1).
                1 + ... + k + (k+1) = k(k+1)/2 + (k+1)   *(by IH)*
                = (k+1)(k/2 + 1) = (k+1)(k+2)/2. That's P(k+1).

                **Conclusion:** By induction, P(n) holds for all n >= 1.

                ### Mistakes I made on HW3
                - Started from P(k+1) and worked "backwards" until I got something true. That's circular! Start from the LHS of P(k+1) and *use* the IH.
                - Forgot to say where I used the IH. Label it.

                Strong induction: assume P(1)...P(k) all hold. Needed for things like "every n >= 2 is a product of primes."
            """),
        ),
        Note(
            title="Permutations vs combinations — when to use which",
            tags=["counting"],
            concepts=["Permutations and Combinations", "Counting Principles"],
            body=_t("""
                Ask: **does order matter?**

                - Yes -> permutation. P(n, r) = n! / (n - r)!
                  - e.g. picking a president, VP and treasurer from 10 people: P(10, 3) = 720.
                - No -> combination. C(n, r) = n! / (r! (n - r)!)
                  - e.g. picking a 3-person committee from 10: C(10, 3) = 120.
                  - 720 / 3! = 120, because each committee can be ordered 3! ways.

                **Product rule:** if a task is a sequence of steps with m and n ways, total = m * n. (License plates: 26^3 * 10^3.)

                **Sum rule:** if a task is done one way OR another (disjoint), add.

                **Inclusion-exclusion:** |A u B| = |A| + |B| - |A n B|. Example: bit strings of length 8 that start with 1 OR end with 00: 2^7 + 2^6 - 2^5 = 160.

                Still unsure about "at least one" problems. Prof says use the complement: total minus "none." Need more practice before HW6.
            """),
        ),
    ],
    documents=[
        Document(
            file_name="cs131-syllabus.pdf",
            category="syllabus",
            summary="CS 131 syllabus: discrete mathematics for computer science — logic, sets, functions, proof techniques, induction, counting and discrete probability — with weekly homework, in-class quizzes, a midterm and a final.",
            concept_notes=[
                ConceptNote(name="Grading", description="Homework 35% (lowest dropped), quizzes 10%, exams 55%."),
                ConceptNote(name="Homework format", description="Written solutions typeset in LaTeX or neatly handwritten and scanned to Gradescope."),
                ConceptNote(name="Textbook", description="Rosen, Discrete Mathematics and Its Applications."),
            ],
            extracted_text=_t("""
                CAS CS 131: Combinatoric Structures
                Boston University

                Course Description
                An introduction to the mathematical structures and reasoning used throughout computer science. Topics include propositional and predicate logic, sets, functions and relations, methods of proof, mathematical induction, recursion, counting, and discrete probability.

                Textbook
                Kenneth Rosen, Discrete Mathematics and Its Applications, 8th edition.

                Grading
                Homework (35%): weekly written problem sets, due Fridays on Gradescope. Your lowest homework score is dropped.
                Quizzes (10%): short in-class quizzes in discussion section.
                Midterm Exam (20%) and Final Exam (35%).

                Schedule
                Weeks 1-2: Propositional logic, truth tables, logical equivalence (Rosen 1.1-1.3)
                Weeks 3-4: Predicates and quantifiers; sets and set operations (1.4-1.5, 2.1-2.2)
                Weeks 5-6: Proof techniques: direct, contrapositive, contradiction (1.7-1.8)
                Week 7: Midterm exam
                Weeks 8-9: Mathematical and strong induction (5.1-5.2)
                Weeks 10-11: Counting, permutations, combinations, pigeonhole (6.1-6.4)
                Weeks 12-13: Discrete probability (7.1-7.2)

                Homework Policy
                You may discuss problems with classmates, but you must write up your own solutions and list your collaborators. A proof that states the correct conclusion without justification earns little credit.
            """),
        ),
        Document(
            file_name="cs131-lecture11-induction.pdf",
            category="lecture_notes",
            summary="Lecture notes introducing the principle of mathematical induction, with worked proofs for a summation formula and a divisibility claim, plus an introduction to strong induction.",
            concept_notes=[
                ConceptNote(name="Principle of induction", description="If P(1) holds and P(k) implies P(k+1) for all k >= 1, then P(n) holds for all n >= 1."),
                ConceptNote(name="Inductive hypothesis", description="The assumption that P(k) holds for an arbitrary k; it must be used in the inductive step."),
                ConceptNote(name="Strong induction", description="The inductive step may assume P(1) through P(k), not just P(k)."),
                ConceptNote(name="Domino analogy", description="The base case knocks the first domino; the inductive step ensures each domino knocks the next."),
            ],
            extracted_text=_t("""
                Lecture 11: Mathematical Induction

                Principle of Mathematical Induction
                To prove that P(n) is true for all positive integers n, we complete two steps:
                Basis step: verify that P(1) is true.
                Inductive step: show that for every positive integer k, if P(k) is true then P(k + 1) is true.

                Think of an infinite line of dominoes. The basis step knocks over the first domino; the inductive step guarantees that each falling domino knocks over the next one.

                Example 1. Show that 1 + 3 + 5 + ... + (2n - 1) = n^2 for all n >= 1.
                Basis: n = 1 gives 1 = 1^2.
                Inductive step: assume 1 + 3 + ... + (2k - 1) = k^2 (inductive hypothesis). Then
                1 + 3 + ... + (2k - 1) + (2k + 1) = k^2 + 2k + 1 = (k + 1)^2.
                Hence P(k + 1) holds.

                Example 2. Show that n^3 - n is divisible by 3 for every positive integer n.
                Basis: 1^3 - 1 = 0, which is divisible by 3.
                Inductive step: (k + 1)^3 - (k + 1) = (k^3 - k) + 3(k^2 + k). The first term is divisible by 3 by the inductive hypothesis, and the second is a multiple of 3.

                Common Errors
                Do not assume what you are trying to prove. Clearly state where the inductive hypothesis is used.

                Strong Induction
                In the inductive step we may assume P(1), P(2), ..., P(k) are all true. Useful when P(k + 1) depends on cases smaller than k.
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="What is the contrapositive of p -> q?", back="not q -> not p. It is logically equivalent to p -> q."),
        Flashcard(front="Negate: for all x, P(x).", back="There exists an x such that not P(x)."),
        Flashcard(front="De Morgan's laws?", back="not (p and q) == (not p) or (not q); not (p or q) == (not p) and (not q)."),
        Flashcard(front="What are the two steps of a proof by induction?", back="Basis step (prove P(n0)) and inductive step (prove P(k) -> P(k+1) for arbitrary k >= n0)."),
        Flashcard(front="C(n, r) formula?", back="n! / (r! (n - r)!) — the number of unordered r-element subsets of an n-element set."),
        Flashcard(front="How many subsets does a set with n elements have?", back="2^n — that's the size of its power set."),
        Flashcard(front="Generalized pigeonhole principle?", back="If N objects go into k boxes, some box contains at least ceil(N/k) objects."),
        Flashcard(front="What makes a function a bijection?", back="It is both injective (one-to-one) and surjective (onto)."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers logic, sets, functions and relations, and proof techniques (Rosen 1.1-1.8, 2.1-2.3). Half the exam is proofs; practice writing complete direct and contradiction proofs, not just computing answers.",
        topics=[
            StudyGuideTopic(name="Logic and equivalences",
                            importance="Truth tables and equivalence laws are the most reliable points on the exam.",
                            concepts=["Propositional Logic", "Predicate Logic and Quantifiers"]),
            StudyGuideTopic(name="Writing proofs",
                            importance="Two full proofs (one direct or contrapositive, one by contradiction) are worth about 40% of the exam.",
                            concepts=["Proof Techniques"]),
            StudyGuideTopic(name="Sets, functions and relations",
                            importance="Expect to prove a set identity and classify a function as injective/surjective.",
                            concepts=["Sets and Set Operations", "Functions and Relations"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Propositional Logic", difficulty="easy", days_ago=40,
            questions=[
                QuizQuestion(
                    question="Which statement is logically equivalent to p -> q?",
                    options=["not q -> not p", "q -> p", "not p -> not q", "p and not q"], correct_answer="not q -> not p",
                    explanation="The contrapositive is equivalent; the converse and inverse are not."),
                QuizQuestion(
                    question="When is p -> q false?",
                    options=["Only when p is true and q is false", "Whenever p is false", "Only when both are false", "Whenever q is true"],
                    correct_answer="Only when p is true and q is false",
                    explanation="An implication with a false hypothesis is vacuously true."),
                QuizQuestion(
                    question="By De Morgan's law, not (p or q) is equivalent to:",
                    options=["not p and not q", "not p or not q", "p and q", "not p or q"], correct_answer="not p and not q",
                    explanation="Negation flips 'or' to 'and' and negates each part."),
            ],
            correct=[0, 1, 2],
        ),
        QuizAttempt(
            concept="Mathematical Induction", difficulty="medium", days_ago=8,
            questions=[
                QuizQuestion(
                    question="In the inductive step of a proof that P(n) holds for all n >= 1, what do you assume?",
                    options=["P(k) for an arbitrary k >= 1", "P(n) for all n", "P(k + 1)", "P(1) only"],
                    correct_answer="P(k) for an arbitrary k >= 1",
                    explanation="You assume P(k) (the inductive hypothesis) and prove P(k + 1)."),
                QuizQuestion(
                    question="To prove 2^n > n^2 for all n >= 5, which base case should you check?",
                    options=["n = 5", "n = 0", "n = 1", "n = 4"], correct_answer="n = 5",
                    explanation="The base case must match the starting value in the claim; the statement is false for n = 4."),
                QuizQuestion(
                    question="When is strong induction typically needed?",
                    options=["When proving P(k + 1) requires P(j) for some j < k, not just P(k)",
                             "When the base case is n = 0",
                             "When the statement involves inequalities",
                             "Whenever the claim is about even numbers"],
                    correct_answer="When proving P(k + 1) requires P(j) for some j < k, not just P(k)",
                    explanation="E.g. prime factorization: k + 1 = a * b with a, b smaller than k + 1."),
                QuizQuestion(
                    question="A student proves P(k + 1) by manipulating it until reaching a true statement. What is wrong?",
                    options=["It assumes the conclusion; the argument is circular", "Nothing, this is a valid proof",
                             "It needs a second base case", "It should use the contrapositive instead"],
                    correct_answer="It assumes the conclusion; the argument is circular",
                    explanation="Deriving a true statement from P(k + 1) doesn't show P(k + 1) is true."),
            ],
            correct=[0, 3],
        ),
    ],
    session=TutorSession(
        name="Stuck on HW5 induction",
        topic="Mathematical Induction",
        mode="socratic",
        summary_bullets=[
            "Proved 3 | (4^n - 1) with guided steps.",
            "Learned to rewrite 4^(k+1) - 1 so the inductive hypothesis term appears.",
            "Practiced stating exactly where the IH is used.",
        ],
        messages=[
            ChatMessage(role="user", content="I need to prove 4^n - 1 is divisible by 3 for all n >= 1. I did the base case but I don't know how to start the inductive step."),
            ChatMessage(role="assistant", content="Good, base case done. What exactly does your inductive hypothesis let you assume about 4^k - 1? Write it as an equation using an integer m."),
            ChatMessage(role="user", content="4^k - 1 = 3m for some integer m."),
            ChatMessage(role="assistant", content="Now look at what you need to show: 4^(k+1) - 1. Can you rewrite 4^(k+1) in terms of 4^k, and then try to make 4^k - 1 appear inside the expression?"),
            ChatMessage(role="user", content="4^(k+1) = 4 * 4^k. So 4 * 4^k - 1... if I write 4^k as (4^k - 1) + 1 I get 4(4^k - 1) + 4 - 1 = 4(3m) + 3?"),
            ChatMessage(role="assistant", content="That's it. And 4(3m) + 3 = 3(4m + 1), which is 3 times an integer, so 3 divides 4^(k+1) - 1. In your write-up, put '(by the inductive hypothesis)' next to the step where you replaced 4^k - 1 with 3m. Graders on HW3 took points for leaving that out. Can you see why the trick of adding and subtracting 1 was the key move?"),
        ],
    ),
)


# ---------------------------------------------------------------------------
# CAS CS 210 — Computer Systems (C, memory, assembly)
# ---------------------------------------------------------------------------

CS210 = Course(
    code="CAS CS 210",
    name="Computer Systems",
    department="Computer Science",
    nickname="CS 210 Systems",
    color="#8B5CF6",
    concepts=[
        Concept(name="Binary and Two's Complement", mastery=0.96,
                description="Unsigned and signed integer encodings; negating with ~x + 1; ranges like -128..127 for 8 bits; overflow."),
        Concept(name="C Pointers and Arrays", mastery=0.76,
                description="Address-of (&) and dereference (*), pointer arithmetic scaled by type size, and arrays decaying to pointers."),
        Concept(name="Bitwise Operations", mastery=0.69,
                description="&, |, ^, ~, << and >> (logical vs arithmetic shift); masking and extracting bit fields."),
        Concept(name="Memory Layout", mastery=0.57,
                description="A process's address space: text, data, bss, heap growing up, and stack growing down."),
        Concept(name="Dynamic Memory Allocation", mastery=0.46,
                description="malloc, calloc, realloc and free; memory leaks, double frees, dangling pointers; checking with valgrind."),
        Concept(name="x86-64 Assembly Basics", mastery=0.31,
                description="Registers (%rax, %rdi, %rsp...), mov/add/lea/cmp/jmp, addressing modes like 8(%rbp,%rcx,4), and condition codes."),
        Concept(name="Calling Conventions and Stack Frames", mastery=0.18,
                description="System V ABI: arguments in %rdi, %rsi, %rdx..., return in %rax, call/ret, saving %rbp, callee- vs caller-saved registers."),
        Concept(name="IEEE 754 Floating Point", mastery=0.12,
                description="Sign, exponent and fraction fields; bias of 127 for float; normalized vs denormalized values; rounding error."),
        Concept(name="Caches and Locality", mastery=0.03,
                description="Temporal and spatial locality, cache lines, hits and misses, and why row-major traversal is faster."),
        Concept(name="Linking and Loading", mastery=0.0,
                description="Object files, symbol resolution, static vs dynamic linking, and how the loader maps an executable into memory."),
    ],
    edges=[
        Edge(source="Binary and Two's Complement", target="Bitwise Operations", relationship="prerequisite", strength=0.85),
        Edge(source="Binary and Two's Complement", target="IEEE 754 Floating Point", relationship="prerequisite", strength=0.7),
        Edge(source="C Pointers and Arrays", target="Dynamic Memory Allocation", relationship="prerequisite", strength=0.9),
        Edge(source="C Pointers and Arrays", target="Memory Layout", relationship="related", strength=0.6),
        Edge(source="Memory Layout", target="Calling Conventions and Stack Frames", relationship="prerequisite", strength=0.75),
        Edge(source="x86-64 Assembly Basics", target="Calling Conventions and Stack Frames", relationship="builds_on", strength=0.85),
        Edge(source="Memory Layout", target="Caches and Locality", relationship="related", strength=0.5),
        Edge(source="x86-64 Assembly Basics", target="Linking and Loading", relationship="related", strength=0.4),
    ],
    mastery_events=[
        MasteryEvent(concept="Bitwise Operations", delta=0.11, reason="Solved PA1 bit puzzles under the op limit"),
        MasteryEvent(concept="Dynamic Memory Allocation", delta=-0.06, reason="valgrind found leaks in PA2 dynamic array"),
        MasteryEvent(concept="x86-64 Assembly Basics", delta=0.09, reason="Traced bomb phase 1 in gdb"),
        MasteryEvent(concept="C Pointers and Arrays", delta=0.07, reason="Lab 4 pointer arithmetic all correct"),
    ],
    categories=[
        Category(name="Labs", weight=0.15, drop_lowest=1),
        Category(name="Programming Assignments", weight=0.4),
        Category(name="Exams", weight=0.45),
    ],
    assignments=[
        Assignment(title="Lab 1: Shell, Make and GDB Setup", category="Labs", type="other",
                   due_offset_days=8, points_possible=10, points_earned=10),
        Assignment(title="PA1: Bit Puzzles", category="Programming Assignments", type="project",
                   due_offset_days=20, points_possible=60, points_earned=55),
        Assignment(title="Lab 4: Pointer Arithmetic", category="Labs", type="other",
                   due_offset_days=31, points_possible=10, points_earned=9),
        Assignment(title="PA2: Dynamic Array in C", category="Programming Assignments", type="project",
                   due_offset_days=43, points_possible=60, points_earned=48),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=54, points_possible=100, points_earned=78, is_midterm=True),
        Assignment(title="PA3: Binary Bomb", category="Programming Assignments", type="project",
                   due_offset_days=74, points_possible=60),
        Assignment(title="PA4: Cache Simulator", category="Programming Assignments", type="project",
                   due_offset_days=96, points_possible=60),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=110, points_possible=150),
    ],
    notes=[
        Note(
            title="Two's complement + bit tricks",
            tags=["binary", "bitwise", "pa1"],
            concepts=["Binary and Two's Complement", "Bitwise Operations"],
            body=_t("""
                ## Two's complement (w bits)
                - Range: -2^(w-1) to 2^(w-1) - 1. For 8 bits: -128..127.
                - Negate: `-x == ~x + 1`. Ex: 5 = 0000 0101 -> ~5 = 1111 1010 -> +1 = 1111 1011 = -5.
                - TMin has no positive counterpart: -(-128) overflows back to -128 in 8 bits.

                ## Shifts
                - `x << k` multiplies by 2^k.
                - `>>` on a **signed** int is arithmetic (copies the sign bit); on unsigned it's logical (fills with 0).

                ## PA1 tricks that worked
                - Get bit k: `(x >> k) & 1`
                - Check if x is negative: `(x >> 31) & 1`
                - Make a mask of the low n bits: `(1 << n) + ~0`  (since ~0 == -1 and the minus operator isn't allowed)
                - x == y without ==: `!(x ^ y)`

                **Gotcha:** comparing signed and unsigned in C converts the signed one to unsigned, so `-1 < 0u` is FALSE.
            """),
        ),
        Note(
            title="Reading assembly for the bomb lab",
            tags=["assembly", "gdb", "pa3"],
            concepts=["x86-64 Assembly Basics", "Calling Conventions and Stack Frames", "Memory Layout"],
            body=_t("""
                ## Registers to remember
                - Args: `%rdi, %rsi, %rdx, %rcx, %r8, %r9` (in that order)
                - Return value: `%rax`
                - Stack pointer: `%rsp`; frame/base pointer: `%rbp`

                ## Instructions
                - `mov src, dst` (AT&T syntax, so **destination is on the right**)
                - `lea 0x8(%rdi), %rax` computes an address but does NOT read memory. Often just arithmetic: rax = rdi + 8.
                - `cmp a, b` sets flags from b - a, then `jg`/`jle` etc. read the flags.
                - `test %eax, %eax` + `je` = "jump if eax is 0".

                ## gdb commands
                - `break phase_1`, `run`, `disas`, `stepi`, `x/s $rdi`, `info registers`
                - `x/6dw $rsp` to see six ints on the stack (phase 2 reads six numbers).

                Still confused about why the function does `sub $0x18, %rsp` at the start. I think it's making space for locals in the stack frame? Ask in OH.
            """),
        ),
    ],
    documents=[
        Document(
            file_name="cs210-syllabus.pdf",
            category="syllabus",
            summary="CS 210 syllabus: how software meets hardware, covering data representation, C programming, x86-64 assembly, the memory hierarchy and linking, assessed with labs, programming assignments and exams.",
            concept_notes=[
                ConceptNote(name="Environment", description="All work is done on the course's Linux server using gcc, make and gdb."),
                ConceptNote(name="Grading", description="Labs 15% (lowest dropped), programming assignments 40%, exams 45%."),
                ConceptNote(name="Late days", description="Three free late days for programming assignments across the semester."),
            ],
            extracted_text=_t("""
                CAS CS 210: Computer Systems
                Boston University

                Course Description
                This course examines how programs are actually executed on a computer. Students learn how data is represented in binary, how C programs map onto x86-64 machine code, how the stack and heap are organized, and how the memory hierarchy affects performance. Prerequisite: CAS CS 112.

                Textbook
                Bryant and O'Hallaron, Computer Systems: A Programmer's Perspective, 3rd edition.

                Grading
                Labs: 15% (lowest dropped)
                Programming Assignments: 40%
                Midterm Exam: 20%
                Final Exam: 25%

                Programming Assignments
                PA1 Bit Puzzles: implement integer operations with a restricted set of bitwise operators.
                PA2 Dynamic Array: a resizable array in C with no memory leaks.
                PA3 Binary Bomb: defuse a compiled program by reverse engineering its assembly in gdb.
                PA4 Cache Simulator: simulate hits, misses and evictions for a set-associative cache.

                Late Policy
                Each student has three late days for programming assignments. After those are used, late work loses 25% per day.

                Schedule
                Weeks 1-3: Bits, bytes, integers, floating point
                Weeks 4-6: C programming, pointers, dynamic memory
                Week 7: Midterm
                Weeks 8-10: x86-64 assembly, control flow, procedures
                Weeks 11-12: Memory hierarchy and caches
                Weeks 13-14: Linking and loading
            """),
        ),
        Document(
            file_name="cs210-lecture07-pointers-and-memory.pdf",
            category="lecture_notes",
            summary="Lecture on C pointers and process memory: pointer arithmetic, arrays vs pointers, the layout of a process's address space, and correct use of malloc and free.",
            concept_notes=[
                ConceptNote(name="Pointer arithmetic", description="p + 1 advances by sizeof(*p) bytes, not by one byte."),
                ConceptNote(name="Array decay", description="An array name used in an expression becomes a pointer to its first element."),
                ConceptNote(name="Heap vs stack", description="Locals live on the stack and vanish on return; malloc'd memory lives on the heap until freed."),
                ConceptNote(name="Dangling pointer", description="A pointer to memory that has been freed or to a returned function's local variable."),
                ConceptNote(name="Memory leak", description="Heap memory that is never freed after its last pointer is lost."),
            ],
            extracted_text=_t("""
                Lecture 7: Pointers and Memory

                A pointer is a variable that holds a memory address.
                int x = 42;
                int *p = &x;     // p holds the address of x
                *p = 7;          // writes 7 into x

                Pointer Arithmetic
                If p is an int *, then p + 1 points sizeof(int) = 4 bytes later. For a char *, p + 1 is one byte later. a[i] is defined as *(a + i).

                Arrays and Pointers
                int a[5];
                int *q = a;      // a decays to &a[0]
                sizeof(a) is 20, but sizeof(q) is 8 on a 64-bit machine.

                Process Address Space (low to high)
                text (code) | data (initialized globals) | bss (zeroed globals) | heap (grows up) ... stack (grows down)

                Dynamic Allocation
                int *arr = malloc(n * sizeof(int));
                if (arr == NULL) { /* handle error */ }
                ...
                free(arr);
                arr = NULL;

                Common Bugs
                1. Returning the address of a local variable: the stack frame is gone after return.
                2. Forgetting to free: a memory leak.
                3. Freeing twice: undefined behavior.
                4. Writing past the end of a buffer: may corrupt other data.

                Use valgrind --leak-check=full ./prog to find leaks and invalid reads.
            """),
        ),
    ],
    flashcards=[
        Flashcard(front="What is -x in two's complement, in terms of bitwise ops?", back="~x + 1"),
        Flashcard(front="Range of a signed 8-bit integer?", back="-128 to 127"),
        Flashcard(front="If int *p = 0x1000, what is p + 3?", back="0x100C, because each int is 4 bytes."),
        Flashcard(front="Which register holds a function's first argument in x86-64 (System V)?", back="%rdi"),
        Flashcard(front="Which register holds a function's return value?", back="%rax"),
        Flashcard(front="What does lea do differently from mov?", back="lea computes an address expression and stores it without reading memory; mov with a memory operand reads/writes memory."),
        Flashcard(front="Is >> on a signed int logical or arithmetic in gcc?", back="Arithmetic: it copies the sign bit into the vacated high bits."),
        Flashcard(front="What tool finds memory leaks in a C program?", back="valgrind (e.g. valgrind --leak-check=full ./prog)"),
        Flashcard(front="Float bias for the exponent field?", back="127 for 32-bit float (8 exponent bits); 1023 for 64-bit double."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers data representation (integers, two's complement, bitwise ops, floating point) and C (pointers, arrays, structs, dynamic memory). Expect bit-level conversions by hand, short C-tracing questions, and one 'find the memory bug' problem.",
        topics=[
            StudyGuideTopic(name="Integer representation and bit manipulation",
                            importance="Several questions require converting between hex, binary, unsigned and signed by hand.",
                            concepts=["Binary and Two's Complement", "Bitwise Operations"]),
            StudyGuideTopic(name="Pointers and memory bugs",
                            importance="The longest question asks you to trace pointer code and identify leaks or dangling pointers.",
                            concepts=["C Pointers and Arrays", "Dynamic Memory Allocation", "Memory Layout"]),
            StudyGuideTopic(name="Floating point",
                            importance="One question decodes a 32-bit float; it's my weakest area, so do the practice problems twice.",
                            concepts=["IEEE 754 Floating Point"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Binary and Two's Complement", difficulty="easy", days_ago=45,
            questions=[
                QuizQuestion(
                    question="What is the 8-bit two's complement representation of -5?",
                    options=["1111 1011", "1000 0101", "1111 1010", "0000 0101"], correct_answer="1111 1011",
                    explanation="5 = 0000 0101, invert to 1111 1010, add 1."),
                QuizQuestion(
                    question="What is 0x2F in decimal?",
                    options=["47", "32", "215", "45"], correct_answer="47",
                    explanation="2 * 16 + 15 = 47."),
                QuizQuestion(
                    question="In C, what does the comparison -1 < 0u evaluate to?",
                    options=["0 (false)", "1 (true)", "It is a compile error", "Undefined behavior"], correct_answer="0 (false)",
                    explanation="-1 is converted to unsigned (UINT_MAX), which is larger than 0."),
            ],
            correct=[0, 1],
        ),
        QuizAttempt(
            concept="x86-64 Assembly Basics", difficulty="medium", days_ago=5,
            questions=[
                QuizQuestion(
                    question="In AT&T syntax, after mov %rdi, %rax, which register was written?",
                    options=["%rax", "%rdi", "Both", "Neither; it reads memory"], correct_answer="%rax",
                    explanation="AT&T syntax is source, destination."),
                QuizQuestion(
                    question="If %rdi = 0x100 and %rsi = 3, what does lea 8(%rdi,%rsi,4), %rax put in %rax?",
                    options=["0x114", "0x10C", "0x118", "The value stored at address 0x114"], correct_answer="0x114",
                    explanation="0x100 + 3*4 + 8 = 0x114; lea does not dereference."),
                QuizQuestion(
                    question="Which pair of instructions implements 'if (x == 0) goto L' for x in %eax?",
                    options=["test %eax, %eax then je L", "cmp %eax, %eax then jne L", "mov $0, %eax then jmp L", "add %eax, %eax then jg L"],
                    correct_answer="test %eax, %eax then je L",
                    explanation="test ANDs the register with itself, setting ZF when it is zero."),
                QuizQuestion(
                    question="What does the ret instruction do?",
                    options=["Pops the return address off the stack and jumps to it", "Copies %rax into the caller's frame",
                             "Restores every callee-saved register", "Frees the current stack frame's locals"],
                    correct_answer="Pops the return address off the stack and jumps to it",
                    explanation="call pushes the return address; ret pops it into %rip."),
            ],
            correct=[0, 2],
        ),
    ],
    session=TutorSession(
        name="Stack frames in the bomb lab",
        topic="Calling Conventions and Stack Frames",
        mode="expository",
        summary_bullets=[
            "Explained the function prologue (push %rbp; mov %rsp, %rbp; sub $N, %rsp).",
            "Connected sub from %rsp to reserving space for locals, since the stack grows down.",
            "Mapped phase_2's read_six_numbers buffer to offsets from %rsp.",
        ],
        messages=[
            ChatMessage(role="user", content="Phase 2 of my bomb starts with push %rbp, then sub $0x28,%rsp. Why subtract from the stack pointer? Doesn't that make it smaller?"),
            ChatMessage(role="assistant", content="It does make the address smaller, and that's the point: on x86-64 the stack grows toward lower addresses. Subtracting 0x28 from %rsp reserves 40 bytes below the old top of the stack for this function's local variables. When the function finishes, it adds the same amount back (or uses leave) before ret."),
            ChatMessage(role="user", content="So the 40 bytes are where the six numbers go? There's a call to read_six_numbers right after with mov %rsp,%rsi."),
            ChatMessage(role="assistant", content="Exactly. %rsi is the second argument register, so phase_2 is passing a pointer to the start of that local buffer as read_six_numbers's second argument (the first, in %rdi, is your input string). After the call, the six ints sit at (%rsp), 4(%rsp), 8(%rsp), up to 0x14(%rsp)."),
            ChatMessage(role="user", content="Oh, so in gdb I can do x/6dw $rsp right after that call to see what it parsed?"),
            ChatMessage(role="assistant", content="Yes. Then step through the loop after it: you'll usually see something like mov (%rbx),%eax compared against a value derived from the previous element. Write down the relationship between consecutive numbers, and that's the pattern the phase is checking."),
        ],
    ),
)


PACK = MajorPack(
    key="cs",
    label="Computer Science",
    year="Sophomore",
    courses=[CS111, CS112, CS131, CS210],
    total_xp=1480,
    streak_days=9,
)
