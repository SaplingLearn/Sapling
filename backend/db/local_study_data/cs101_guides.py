"""CS101's study guides: one section draft per concept, and the guides that
pick from them. A draft is written once at every length it is read at
(``spec.LENGTHS``): its opening passage is the cram version, and the
``standard`` and ``deep`` passages are what the longer versions add."""
from __future__ import annotations

from db.local_study_data import blocks as b
from db.local_study_data.cs101_concepts import CONCEPTS
from db.local_study_data.spec import GuideSpec, SectionDraft

_C = {c.key: c for c in CONCEPTS}

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
                at="brief",
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
                at="brief",
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
                ("Every variable in a running program lives at an **address**, a number that says where "
                 "its bytes sit in memory. A **pointer** is a variable whose value is one of those "
                 "addresses. Two operators do all the work. `&x` gives you the address of x, so "
                 "`int *p = &x;` makes p point at x. `*p` goes the other way: it follows the address "
                 "stored in p and lands on the value that lives there.", "lec09"),
                ("Pointers matter because of what happens when you write through one. `*p = 7;` does "
                 "not change p. It changes the variable p points at, so after that line x is 7 even "
                 "though the line never names x. This is how a C function changes its caller's data: "
                 "the caller passes `&x` and the function writes through the pointer it was handed. "
                 "Keep one sentence in your head and most questions come apart: p is where, `*p` is "
                 "what.", "lec09"),
                summary="A pointer holds an address. & takes an address, * follows one, and writing "
                        "through *p changes the variable it points at.",
            ),
            b.prose(
                ("A pointer is only as good as the address inside it. One that was declared and never "
                 "set holds whatever bytes were already there, so following it reads or writes some "
                 "arbitrary part of memory. One that holds **NULL** points at nothing, and there is "
                 "no value to follow it to. The habit that prevents both is to give every pointer a "
                 "value on the line where you declare it, a real address or NULL, and to test for "
                 "NULL before the first `*`. The two slips below come from your own quiz answers.",
                 "lec09"),
                summary="Set every pointer where you declare it, to a real address or NULL, and check "
                        "for NULL before you follow it.",
                at="standard",
            ),
            b.mistakes(
                (0, "Following a pointer before it is set",
                 "Initialise every pointer where you declare it, and check for NULL before the first *."),
                (1, "Mixing up p and *p",
                 "Say it out loud: p is where, *p is what. Draw the box and the arrow before you answer."),
            ),
            b.prose(
                "When a question asks what a variable holds after a few lines of pointer code, the "
                "hard part is reading the symbols, because the same star means two different things. "
                "In a declaration, `int *p` says that p is a pointer to an int, and nothing is "
                "followed. Everywhere else, `*p` follows the pointer. The table sets the two "
                "operators side by side. Its first row is the one to learn: reading `&x` and `*p` "
                "aloud in plain words is what stops you swapping them half way through a trace.",
                summary="A star in a declaration makes a pointer; a star anywhere else follows one. "
                        "Read &x and *p aloud as you trace.",
                at="standard",
            ),
            b.compare(
                "The two pointer operators", ("&x", "*p"),
                ("Read as", "The address of x", "The value p points at"),
                ("Applied to", "A variable", "A pointer"),
                ("In a declaration", "Not used", "int *p declares p as a pointer to int"),
                emphasis=0,
            ),
            b.bridge(
                "Work the example with a sketch: a box for x, an arrow from p to the box, and a "
                "redraw after every line.",
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
            b.prose(
                ("Pointers are not a topic you finish and leave behind. An array's name acts as a "
                 "pointer to its first element. Memory from malloc lives on the heap until the "
                 "program frees it, and a pointer is the only way to reach it. A linked list is a "
                 "chain of structs joined by pointers. The map shows that order. If the two "
                 "operators still feel shaky, settle them here, because every later stop on the map "
                 "assumes them.", "lec11", "lec09"),
                summary="Arrays, heap memory and linked lists all rest on pointers, so the two "
                        "operators have to be solid first.",
                at="standard",
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
                ("An **array** stores values of one type side by side in memory, and you reach each "
                 "one by its **index**, its position counted from 0. An array of 5 items therefore "
                 "has indexes 0 to 4, and there is no item 5. C does not check that an index is in "
                 "range. Ask for `a[5]` and the program reads whatever happens to sit just past the "
                 "array, with no error to warn you.", "lec11"),
                ("A C **string** is a char array with one extra rule: it ends with a zero byte, the "
                 "terminator, and that byte is how the code that reads a string knows where to stop. "
                 "So the string cat needs 4 bytes, three letters and the terminator. `strlen` counts "
                 "the letters and not the terminator, which is why the length of a string is always "
                 "one less than the space it needs.", "lec11"),
                summary="Indexes start at 0 and C never checks them. A string is a char array that "
                        "needs one extra byte for its terminator.",
            ),
            b.terms(
                ("Index", "An element's position in its array, counted from 0."),
                ("Terminator", "The zero byte that marks the end of a C string."),
                ("Out-of-range access", "Using an index outside the array, which C does not detect."),
            ),
            b.prose(
                ("The name of an array acts as a pointer to its first element, and that one fact "
                 "explains indexing. `a[i]` means the same as `*(a + i)`: move i elements along from "
                 "the start, then follow the pointer. It also explains why the first index is 0, "
                 "since the first element is zero steps from the start. The program can work out "
                 "where any element lives with one multiplication and one addition, so reaching "
                 "`a[i]` costs the same for every i. The formula below is that sentence written out.",
                 "lec11"),
                summary="a[i] is *(a + i): step i elements from the start, then follow the pointer. "
                        "That is why indexes start at 0.",
                at="standard",
            ),
            b.formula(
                "Where element i lives",
                r"\text{address}(a[i]) = \text{address}(a[0]) + i \times \text{size of one element}",
                "The address of element i is the address of element zero plus i times the element size.",
                "lec11",
            ),
            b.prose(
                "Sizing a buffer is where the two rules above meet. A buffer has to hold every letter "
                "and the terminator, so the space you need is the string's length plus one. Declare "
                "it one byte short and the code still compiles and runs. The terminator is written "
                "into the byte just past the buffer, the same unchecked out-of-range access as "
                "before, and the damage shows up later, somewhere that looks unrelated. Count the "
                "letters, add one, and only then write the size. The example walks through it.",
                summary="A buffer needs the string's length plus one. One byte short still runs, "
                        "then overwrites memory it does not own.",
                at="standard",
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
                ("A **recursive** function solves a problem by calling itself on a smaller input. "
                 "Every such function has two parts. The **base case** is the input it answers "
                 "directly, with no further call. The **recursive case** handles every other input "
                 "by reducing it toward the base case and calling again. factorial is the standard "
                 "example: factorial(0) is answered at once, and any other n is handed down as "
                 "n - 1.", "lec07"),
                ("Each call gets its own frame on the **call stack**, with its own copy of the "
                 "parameters, so the n in one call is not the n in the next. factorial(3) calls "
                 "factorial(2), which calls factorial(1), which calls factorial(0), and all four "
                 "frames sit on the stack at once, waiting. Nothing is multiplied on the way down. "
                 "The answers come back in reverse order as each frame finishes its own work: 1, "
                 "then 1, then 2, then 6.", "lec07"),
                summary="A recursive function calls itself on a smaller input until it reaches a base "
                        "case. Calls stack up going down, and answers come back in reverse.",
            ),
            b.prose(
                ("Recursion goes wrong in two ways, and both are worth checking before you trust a "
                 "function you wrote. The first is a base case the input never reaches. A function "
                 "with no reachable base case never stops, and it overflows the stack. Problem 3 of "
                 "Homework 6 is exactly this: count_down(n) prints n and calls count_down(n - 1), "
                 "with nothing to end it. The second is quieter. The call below returns a value, and "
                 "the recursive case forgets to combine it with its own n, so the right answer is "
                 "worked out and then thrown away. Your quizzes show both.", "lec07", "hw6"),
                summary="Check two things in every recursive function: each call moves toward a base "
                        "case, and the recursive case uses what the call below returns.",
                at="standard",
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
            b.prose(
                ("The definition above is already the code. Its second half, zero factorial is one, "
                 "is the base case. Its first half is the recursive case, and the multiplication by "
                 "n in it is the work each frame still has to do once the call below returns. That "
                 "is why a trace has two passes. Homework 6 asks for one line per call, so write the "
                 "calls going down first, with every multiplication left open, then fill in the "
                 "return values from the bottom up. The example does this for factorial(3).", "hw6"),
                summary="Trace in two passes: one line per call going down, then the return values "
                        "from the bottom up.",
                at="standard",
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
            b.prose(
                ("Writing a recursive function is the same skill run backwards. Homework 6 asks you "
                 "to state the base case and the recursive case before you write any code, and that "
                 "order is the method: decide which input you can answer directly, then decide how "
                 "any other input becomes a smaller one. Recursion rests on what you already know "
                 "about functions, since each call is an ordinary call with a frame of its own. The "
                 "map shows what it rests on and where it is used next.", "hw6"),
                summary="To write one, state the base case and the recursive case before any code. "
                        "Each call is an ordinary function call with its own frame.",
                at="standard",
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
                ("**Big-O** describes how the number of steps an algorithm takes grows with the size "
                 "of its input, written n. It is not a stopwatch. It ignores constant factors and "
                 "keeps only the fastest growing term, because that term decides what happens once "
                 "the input gets large. Two programs with the same Big-O can differ in speed, but "
                 "they slow down in the same way as n grows.", "lec13"),
                ("Three patterns cover most of the code you will be asked about. One loop over n "
                 "items is O(n): twice the input, twice the steps. A loop inside a loop is O(n^2), "
                 "because the inner loop runs in full for every pass of the outer one. Halving the "
                 "problem at each step, as binary search does, is O(log n), which grows so slowly "
                 "that a far longer list costs only a few more steps.", "lec13"),
                summary="Big-O counts how steps grow with n and keeps the fastest growing term. One "
                        "loop is O(n), nested loops are O(n^2) and halving is O(log n).",
            ),
            b.bridge(
                "The chart shows the shape of that difference: switch it to After sorting and compare "
                "the new line with the old one at the right-hand edge.",
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
            b.prose(
                ("Read the chart by its shapes. Linear search climbs in a straight line, one more "
                 "step for every item added. Binary search barely leaves the floor, because each "
                 "step throws away half of what is left, so doubling the list adds a single step. "
                 "That saving has a price: binary search needs the list to be sorted first. The "
                 "table puts the common growth rates in one place. Its last row deserves the most "
                 "attention, since a loop inside a loop is easy to write and expensive to run.",
                 "lec13", "lec15"),
                summary="Linear search grows in a straight line and binary search stays nearly flat, "
                        "but only on a sorted list.",
                at="standard",
            ),
            b.compare(
                "Common growth rates", ("Typical code", "Steps for 1,000 items"),
                ("O(1)", "Index into an array", "1"),
                ("O(log n)", "Binary search", "About 10"),
                ("O(n)", "One loop over the input", "1,000"),
                ("O(n^2)", "A loop inside a loop", "1,000,000"),
                emphasis=3,
            ),
            b.prose(
                "To find the Big-O of code you are handed, count how many times the innermost line "
                "runs. Loops that follow one another add, and loops that sit inside one another "
                "multiply. An inner loop of n steps that runs once for each of n outer passes is n "
                "times n steps, not n plus n, and calling that O(n) is the slip to watch for. Once "
                "you have a count like the one in the formula below, keep its largest term and drop "
                "the constant in front of it.",
                ("Keep in mind what the answer does and does not tell you. Big-O is about growth "
                 "and not about speed on one input. An O(n^2) program can beat an O(n) program on a "
                 "small list and still lose badly on a large one, so a question about which is "
                 "faster for ten items cannot be settled from the Big-O alone.", "lec13"),
                summary="Count how often the innermost line runs: nested loops multiply. Keep the "
                        "largest term, and remember Big-O compares growth, not speed on one input.",
                at="standard",
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
                ("**Insertion sort** grows a sorted region one item at a time: it takes the next item "
                 "and slides it back into place among the ones already in order. Each item may have "
                 "to pass every item before it, which is why the work is O(n^2). **Merge sort** "
                 "takes a different route. It splits the list in half, sorts each half and merges "
                 "the two sorted halves, and that is O(n log n).", "lec15"),
                ("Sorting is usually done for the sake of searching. **Binary search** looks at the "
                 "middle of a sorted list and throws away the half that cannot hold the target, then "
                 "does the same to what is left. It only works because the list is in order. On an "
                 "unsorted list the half you throw away might hold the target, and the only safe "
                 "search left is to check every item in turn.", "lec15"),
                summary="Insertion sort is O(n^2) and merge sort is O(n log n). Binary search halves "
                        "the list at each look, but only if the list is sorted.",
            ),
            b.prose(
                ("The lab timings make the two growth rates visible. Insertion sort took 12 "
                 "milliseconds for 1000 items, 47 for 2000, 190 for 4000 and 760 for 8000: every "
                 "time the list doubles, the time goes up about four times, which is what n^2 "
                 "predicts. Merge sort took 2, 4, 9 and 19 milliseconds for the same lists, a little "
                 "more than double each time. Read the chart from left to right and watch the gap "
                 "between the two lines widen.", "lec15"),
                summary="In the lab, doubling the list made insertion sort about four times slower "
                        "and merge sort a little more than twice as slow.",
                at="standard",
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
            b.prose(
                "Speed is not the whole comparison, and the table shows what merge sort pays for it: "
                "a second array as long as the first. On a short list, or one that is nearly in "
                "order already, insertion sort has little to do and no extra memory to find, so it "
                "is the sensible choice there. When a question asks which sort to use, answer with "
                "the size and the state of the list. The example then runs binary search by hand: "
                "at every look, say which half you discard and why.",
                summary="Merge sort wins on long lists but needs a second array; insertion sort "
                        "suits short or nearly sorted ones.",
                at="standard",
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
        # The dataset's model guide: just written, up to date, nothing read,
        # answered or saved, with every block type between its passages.
        made_hours_ago=2,
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
