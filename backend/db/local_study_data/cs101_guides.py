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
                ("A **variable** is a named place that holds a value, and its **type** says what kind "
                 "of value that is. Declaring `int count;` asks for a place big enough for a whole "
                 "number and gives it the name count. From then on the type decides what the program "
                 "may do with it: an int can be added and compared, and it cannot quietly hold half "
                 "of something.", "lec03"),
                "**Assignment** copies a value into that place. It does not tie two variables "
                "together. After `b = a;` the two hold the same number, but they are separate places, "
                "so changing a later leaves b exactly as it was. Read every assignment from right to "
                "left: work out the value on the right first, then store it in the name on the left.",
                summary="A variable is a typed, named place for a value. Assignment copies the value; "
                        "it does not link two variables.",
            ),
            b.terms(_C["variables"],
                    ("Assignment", "The statement that copies a value into a variable."),
                    ("Integer division", "Division of two ints, which drops the fraction.")),
            b.prose(
                "One character separates the two operators you will use most. A single `=` assigns. "
                "A double `==` compares and gives back true or false, which C stores as 1 or 0. "
                "Mixing them up still compiles, and that is what makes it dangerous. `if (x = 5)` "
                "stores 5 in x and then treats that 5 as true, so the branch always runs and x has "
                "been changed on the way. The table lays the two side by side. Its last row is the "
                "classic bug, and it is the first thing to look for when a condition seems to be "
                "ignored.",
                summary="= stores a value and == tests for equality. Writing = inside a condition "
                        "compiles, changes the variable and is always true.",
                at="standard",
            ),
            b.compare(
                "Assignment and comparison", ("=", "=="),
                ("What it does", "Copies the right side into the left", "Tests whether two values are equal"),
                ("What it gives back", "The value that was assigned", "1 for true or 0 for false"),
                ("Classic bug", "if (x = 5) is always true", "x == 5; on its own line does nothing"),
                emphasis=2,
            ),
            b.prose(
                "The type also decides what an operator means, and division is where this catches "
                "people. With two int operands, `/` is **integer division**: it drops the fraction, "
                "so 7 / 2 is 3 and not 3.5. Nothing is rounded and no warning appears. The fraction "
                "is gone before the result is stored, even when the variable receiving it could have "
                "held one. When a result looks too small or comes out as zero, check the types of "
                "both operands before you check the arithmetic.",
                summary="With two ints, division drops the fraction: 7 / 2 is 3. Check the operand "
                        "types first.",
                at="standard",
            ),
            b.prose(
                "You should now be able to read a declaration and say what the variable can hold, "
                "follow an assignment without tying two variables together, spot integer division "
                "from the types of its operands, and tell `=` from `==` at a glance. The question "
                "below asks for one of those.",
                summary="You can now read declarations, follow assignments, spot integer division and "
                        "tell = from ==.",
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
                ("**Control flow** is the order in which statements run. Left alone, a program runs "
                 "from top to bottom, one line after the next. An `if` statement changes that: it "
                 "runs its block only when its condition is true, and an `else` block runs when the "
                 "condition is false. Exactly one of the two branches runs each time the `if` is "
                 "reached.", "lec03"),
                ("A **loop** repeats its body. A `while` loop checks its condition before every pass, "
                 "the first one included, so its body can run zero times. A `for` loop packs the "
                 "start, the condition and the step into one line and stops by the same rule. Both "
                 "stop the first time the condition is false, and the check happens only at the top "
                 "of a pass, never half way through one.", "lec03"),
                summary="An if picks one branch and a loop repeats its body. A loop checks its "
                        "condition before every pass and stops the first time it is false.",
            ),
            b.prose(
                ("Questions about loops rarely ask what a loop is. They ask how many times its body "
                 "runs and what it prints, and the reliable method is the one from lecture: list the "
                 "values the loop variable takes while the condition holds. A loop that starts at 0 "
                 "and adds 3 while below 10 takes 0, 3, 6 and 9, so its body runs four times. The "
                 "value 12 is computed too, but it fails the check and the body never sees it. The "
                 "formula below gives the same count without the list, which is useful for checking "
                 "your work.", "lec03"),
                summary="To trace a loop, list the values its variable takes while the condition "
                        "holds, then count them.",
                at="standard",
            ),
            b.formula(
                "Passes of a counting loop",
                r"\text{passes} = \left\lceil \frac{\text{stop} - \text{start}}{\text{step}} \right\rceil",
                "Passes equal stop minus start, divided by step, rounded up.",
                "lec03",
            ),
            b.prose(
                "The formula has one catch, and it is the most common slip in this unit: the "
                "comparison sign. With `<` the stop value itself is never used. With `<=` it is, and "
                "the loop makes one more pass whenever the variable lands exactly on it. That is the "
                "**off-by-one error**. When you are unsure, do not argue it out in your head. Write "
                "the last value that passes the check and the first that fails, side by side, and "
                "the count settles itself. The example does this for a loop that steps by 4.",
                summary="With < the stop value is left out and with <= it is included. Write the "
                        "last value that passes and the first that fails.",
                at="standard",
            ),
            b.example(
                "Count the passes",
                "A loop starts i at 1 and adds 4 while i is below 14. How many times does the body run?",
                ("List the values", "1, 5, 9, 13", "Keep adding the step while the condition still holds."),
                ("Check the next one", "17 < 14 is false", "The loop stops before the body runs for 17."),
                ("Count them", "4 passes", "One pass for each value listed."),
                source="lec03",
            ),
            b.prose(
                "It helps to count checks as well as passes. A loop whose body runs four times "
                "checks its condition five times, four that pass and one that fails, and the failing "
                "check is what ends it. This explains two things that look odd at first. The loop "
                "variable is still there after the loop and holds the first value that failed, 17 in "
                "the example and not 13. And a loop whose condition is false at the start makes one "
                "check, runs no passes and is not an error. A question that asks for the value of i "
                "after the loop is testing exactly this.",
                summary="A loop with n passes makes n + 1 checks. After it ends, the loop variable "
                        "holds the first value that failed the check.",
                at="deep",
            ),
            b.prose(
                ("Because a for loop and a while loop stop by the same rule, any for loop can be "
                 "rewritten as a while loop. The start goes on a line above, the condition stays at "
                 "the top, and the step becomes the last line of the body. Doing that rewrite on "
                 "paper is a good way to trace a for loop that confuses you, since it puts the three "
                 "parts in the order they really run. The start runs once. Then the condition, the "
                 "body and the step repeat in that order until the condition fails. The step always "
                 "comes after the body, which is why the body sees the start value first.", "lec03"),
                summary="A for loop is a while loop with its start above it and its step at the end "
                        "of the body. Rewrite it that way to trace it.",
                at="deep",
            ),
            b.prose(
                "You should now be able to say which branch of an if runs, list the values a loop "
                "variable takes, count the passes with the list or with the formula, and catch an "
                "off-by-one error by checking the comparison sign. The question below asks you to "
                "count the passes of one loop.",
                summary="You can now pick the branch, list a loop's values and count its passes.",
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
                ("A **function** has a name, parameters and a return type. Calling it copies each "
                 "**argument** into the matching **parameter**, runs the body and hands back the "
                 "return value. The call then stands for that value in the expression it was "
                 "written in.", "lec05"),
                ("C passes arguments by value. The function works on its own copies, so when it "
                 "changes a parameter it changes that copy and not the caller's variable. To change "
                 "the caller's data it has to be handed a pointer to it.", "lec05"),
                summary="A call copies arguments into parameters and returns one value. Changes to a "
                        "parameter stay inside the function.",
                at="brief",
            ),
            b.terms(("Parameter", "A variable in the function's definition that receives an argument."),
                    ("Argument", "The value the caller passes in."),
                    ("Return value", "The one value a call evaluates to.")),
            b.prose(
                ("It pays to slow a call down into its steps, because every question about functions "
                 "is a question about one of them. First the arguments are worked out, in the "
                 "caller. Then each value is copied into its parameter, which is a new variable that "
                 "exists only for this call. The body runs, using those parameters. Last, the return "
                 "value is handed back and the parameters disappear. Nothing in that sequence "
                 "touches the caller's variables, and that is the whole reason a function like the "
                 "one in the example cannot change what it was given.", "lec05"),
                summary="A call works out the arguments, copies them into new parameters, runs the "
                        "body and returns. The caller's variables are never touched.",
                at="standard",
            ),
            b.example(
                "What does the caller see?",
                "void bump(int n) { n = n + 1; } is called as bump(x) with x equal to 5. What is x afterwards?",
                ("Copy the argument", "n = 5", "The call copies the value of x into the parameter n."),
                ("Run the body", "n = 6", "Only the copy changes."),
                ("Return", "x = 5", "n is destroyed and x was never touched."),
            ),
            b.prose(
                "The other half of a function is what comes back. A call hands back one value, and "
                "the caller has to do something with it: store it, print it or use it inside a "
                "larger expression. Calling a function and ignoring its result is allowed and is "
                "nearly always a mistake, because the work was done and then dropped. A function "
                "whose return type is void hands back nothing and is called only for its effect. "
                "bump in the example is one of these, and since its only effect was on a copy, the "
                "call achieved nothing. When you read code, find each call and ask two things: what "
                "goes in, and where does the result go.",
                summary="A call returns one value, and the caller must use it. Ask of every call "
                        "what goes in and where the result goes.",
                at="standard",
            ),
            b.prose(
                "You should now be able to walk through a call step by step, say what each parameter "
                "holds, explain why a change to a parameter never reaches the caller, and say where a "
                "call's result goes. The question below checks the central point.",
                summary="You can now trace a call and explain why the caller's variable is unchanged.",
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
                ("**Scope** is where in the code a name can be used, and **lifetime** is how long "
                 "its value exists. A variable declared inside a function is local: only that "
                 "function can name it, and it is created when the function is called.", "lec05"),
                ("A local is gone when its function returns, and the next call starts with a fresh "
                 "one. A global variable is declared outside every function and lives for the whole "
                 "run, where any function can read it and change it.", "lec05"),
                summary="Locals live for one call and are visible only inside it. Globals live for "
                        "the whole run.",
                at="brief",
            ),
            b.prose(
                "The two ideas are easy to blur, because for a local variable they begin and end "
                "together. Keep them apart with two questions. Scope asks where: on which lines of "
                "the program may this name appear? Lifetime asks when: between which moments of the "
                "run does the value exist? A local answers both with one call of its function. A "
                "global answers them with the rest of the file and the whole run. The table lines "
                "the answers up, and its lifetime row is the one that explains the bugs.",
                summary="Scope is where a name can be used and lifetime is when its value exists. "
                        "For a local, both are one call.",
                at="standard",
            ),
            b.compare(
                "Local and global variables", ("Local", "Global"),
                ("Declared", "Inside a function", "Outside every function"),
                ("Lifetime", "One call of the function", "The whole run of the program"),
                ("Visible from", "That function only", "Every function below the declaration"),
                emphasis=1,
            ),
            b.prose(
                "The bug this leads to is returning the address of a local variable. The address is "
                "only a number, so it can be returned without any complaint. But the variable it "
                "named is gone the moment the function returns, and that memory is free to be used "
                "by the next call. The caller is left holding a pointer to a place that no longer "
                "belongs to anything, and reading through it may give the old value once and "
                "nonsense the next time.",
                "Globals avoid that problem and bring another. Since every function can change a "
                "global, a wrong value in one could have come from anywhere, and you have to read "
                "the whole program to find out. Prefer locals, and pass values in as arguments. When "
                "you trace code, note where each variable was declared, because that tells you both "
                "who can see it and how long it will last.",
                summary="Never return the address of a local: it is gone when the function returns. "
                        "Prefer locals to globals, so fewer functions can change a value.",
                at="standard",
            ),
            b.prose(
                "You should now be able to say, for any variable in a program, where its name can be "
                "used and how long its value lasts, and to explain why a pointer to a local goes bad "
                "when its function returns. The question below asks for that explanation.",
                summary="You can now give a variable's scope and lifetime and explain the returned-address bug.",
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
            b.compare(
                "The two pointer operators", ("&x", "*p"),
                ("Read as", "The address of x", "The value p points at"),
                ("Applied to", "A variable", "A pointer"),
                ("In a declaration", "Not used", "int *p declares p as a pointer to int"),
                emphasis=0,
            ),
            b.prose(
                "When a question asks what a variable holds after a few lines of pointer code, the "
                "hard part is reading the symbols, because the same star means two different things. "
                "In a declaration, `int *p` says that p is a pointer to an int, and nothing is "
                "followed. Everywhere else, `*p` follows the pointer. Reading `&x` and `*p` aloud in "
                "plain words, as the first row of the table does, is what stops you swapping them "
                "half way through a trace. The example below is such a trace. Work it with a sketch: "
                "a box for x, an arrow from p to the box, and a redraw after every line.",
                summary="A star in a declaration makes a pointer; a star anywhere else follows one. "
                        "Trace pointer code with a box and an arrow.",
                at="standard",
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
                ("The example is worth one more look, because its last step is the idea the rest of "
                 "the course leans on. x and `*p` are not two variables that happen to agree. They "
                 "are two names for one place, so there is no moment at which one has changed and "
                 "the other has not. The same holds across a function call. C copies every argument, "
                 "so a function handed x gets a copy and cannot change the original. A function "
                 "handed `&x` also gets a copy, but a copy of the address, and that address still "
                 "leads to the caller's x. That is why a function that must change a variable takes "
                 "a pointer to it.", "lec09"),
                summary="x and *p are two names for one place. A function changes its caller's "
                        "variable only when it is given that variable's address.",
                at="deep",
            ),
            b.prose(
                ("A pointer is only as good as the address inside it. One that was declared and never "
                 "set holds whatever bytes were already there, so following it reads or writes some "
                 "arbitrary part of memory. One that holds **NULL** points at nothing, and there is no "
                 "value to follow it to. Give every pointer a value on the line where you declare it, "
                 "a real address or NULL, and test for NULL before the first `*`. The two slips below "
                 "come from your own quizzes, and both start the same way: treating the pointer as if "
                 "it were the thing it points at.", "lec09"),
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
                ("There is a third way for a pointer to go bad, besides never being set and being "
                 "NULL: it can outlive the thing it points at. Local variables live on the stack and "
                 "vanish when their function returns, so a pointer to a local must not be kept after "
                 "that return. The address inside it is unchanged and looks perfectly normal, which "
                 "is what makes the bug hard to see. Before you follow any pointer, ask whether the "
                 "variable it was aimed at still exists.", "lec09"),
                ("Pointers are not a topic you finish and leave behind. An array's name acts as a "
                 "pointer to its first element. Memory from malloc lives on the heap until the "
                 "program frees it, and a pointer is the only way to reach it. A linked list is a "
                 "chain of structs joined by pointers. The map shows that order. If the two operators "
                 "still feel shaky, settle them here, because every later stop on the map assumes "
                 "them.", "lec11", "lec09"),
                summary="A pointer must not outlive what it points at. Arrays, heap memory and linked "
                        "lists all build on pointers.",
                at="deep",
            ),
            b.at("deep", b.concept_map(
                "Where pointers lead",
                (_C["variables"], "Foundations"), (_C["pointers"], "This section"),
                (_C["dynamic"], "Up next"), (_C["linkedlists"], "Later"),
            )),
            b.prose(
                "You should now be able to read `&x` and `*p` without hesitating, trace code that "
                "writes through a pointer, and name the two habits that keep pointers safe: set every "
                "pointer when you declare it, and check for NULL before you follow it. The question "
                "below is a short trace.",
                summary="You can now read & and *, trace writes through a pointer and keep pointers safe.",
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
                ("The formula also shows why C cannot warn you about a bad index. An index is only a "
                 "distance from the start, and the arithmetic works just as well for a distance that "
                 "runs off the end. Nothing stored with the array records how long it is, so the "
                 "program has no length to compare your index against. That is your job. Any code "
                 "that walks an array needs the length handed to it separately, and a loop over an "
                 "array of n items must stop while the index is still below n, because n itself is "
                 "the first index that is out of range.", "lec11"),
                summary="An index is a distance from the start and the array stores no length, so C "
                        "cannot check it. A loop must stop before index n.",
                at="deep",
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
            b.prose(
                ("A string has no stored length either, and that is the reason for the terminator. "
                 "Code that prints or measures a string starts at the first byte and keeps going "
                 "until it meets the zero byte. So the terminator is part of the data and not a "
                 "formality. If it is missing, because the buffer was one byte short or because you "
                 "filled the array one character at a time and never wrote it, the code runs on past "
                 "the end of the array into whatever memory follows. Two numbers describe every "
                 "string, and they always differ by one: the length `strlen` reports and the bytes "
                 "the string needs.", "lec11"),
                summary="Code finds the end of a string by looking for the zero byte, so a missing "
                        "terminator sends it past the array.",
                at="deep",
            ),
            b.prose(
                "You should now be able to give the index of any element, explain why C will not stop "
                "a bad one, and size a buffer for a string by counting its letters and adding one for "
                "the terminator. The question below checks whether you can place the terminator.",
                summary="You can now index an array, explain the missing range check and size a string buffer.",
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
                 "input it answers directly, and the **recursive case** reduces every other input "
                 "toward it. A function whose calls never reach the base case never stops, and it "
                 "overflows the stack.", "lec07"),
                ("Each call gets its own frame on the call stack, with its own copy of the parameters. "
                 "The calls stack up on the way down and the answers come back in reverse order, so "
                 "trace in two passes: one line per call going down, then the return values from the "
                 "bottom up.", "lec07", "hw6"),
                summary="A recursive function calls itself on a smaller input until a base case. Trace "
                        "the calls down, then the return values back up.",
                upto="cram",
            ),
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
                at="standard",
            ),
            b.at("deep", b.formula(
                "Factorial, defined recursively",
                r"n! = n \times (n-1)!, \qquad 0! = 1",
                "n factorial is n times the factorial of n minus one, and zero factorial is one.",
                "lec07",
            )),
            b.prose(
                ("The definition above is already the code. Its second half, zero factorial is one, "
                 "is the base case. Its first half is the recursive case, and the multiplication by "
                 "n in it is the work each frame still has to do once the call below returns. That "
                 "is why a trace has two passes. Homework 6 asks for one line per call, so write the "
                 "calls going down first, with every multiplication left open, then fill in the "
                 "return values from the bottom up. The example does this for factorial(3).", "hw6"),
                summary="Trace in two passes: one line per call going down, then the return values "
                        "from the bottom up.",
                at="deep",
            ),
            b.at("cram", b.example(
                "Trace factorial(3)",
                "factorial(n) returns 1 when n is 0 and n * factorial(n - 1) otherwise. What does factorial(3) return?",
                ("Go down", "f(3) -> f(2) -> f(1) -> f(0)", "Each call waits for the one below it."),
                ("Hit the base case", "f(0) = 1", "No further call is made."),
                ("Come back up", "f(1) = 1 * 1 = 1", "The waiting call finishes its multiplication."),
                ("Keep going", "f(2) = 2 * 1 = 2", "Each frame uses the value returned to it."),
                ("Answer", "f(3) = 3 * 2 = 6", "The first call is the last to return."),
                source="lec07",
            )),
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
            b.prose(
                ("Writing a recursive function is the same skill run backwards. Homework 6 asks you "
                 "to state the base case and the recursive case before you write any code, and that "
                 "order is the method: decide which input you can answer directly, then decide how "
                 "any other input becomes a smaller one. If you cannot say both in a sentence each, "
                 "you are not ready to write the function. Recursion rests on what you already know "
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
            b.prose(
                ("Problem 5 of Homework 6 tests the habit of stating both cases first, because its "
                 "smaller input is not n - 1. It asks for the number of digits in a positive integer. "
                 "Ask the two questions in order. Which input can be answered directly? A number with "
                 "a single digit. How does any other input become a smaller one? Not by subtracting "
                 "1, which would take thousands of calls, but by making the number one digit shorter. "
                 "Notice what you never have to do: follow the calls all the way down in your head. "
                 "Assume the call on the smaller input returns the right answer and decide only what "
                 "this frame adds to it. That assumption is safe as long as every call moves toward "
                 "the base case.", "hw6"),
                summary="The smaller input is not always n - 1. Assume the call below is right, and "
                        "decide only what this frame adds.",
                at="deep",
            ),
            b.prose(
                "You should now be able to find the base case and the recursive case of any recursive "
                "function, trace it in two passes, one line per call going down and the return values "
                "coming back up, and say what goes wrong when the base case cannot be reached. The "
                "question below is a trace of your own.",
                summary="You can now find both cases, trace in two passes and spot an unreachable base case.",
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
                 "problem at each step, as binary search does, is O(log n), which grows very slowly. "
                 "The chart shows the shape of that difference: switch it to After sorting and "
                 "compare the new line with the old one at the right-hand edge.", "lec13"),
                summary="Big-O counts how steps grow with n and keeps the fastest growing term. One "
                        "loop is O(n), nested loops are O(n^2) and halving is O(log n).",
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
                ("There is a second way to find a growth rate that needs no code at all: double the "
                 "input and see what happens to the work. If the work doubles, the algorithm is "
                 "O(n). If it goes up about four times, it is O(n^2). If it rises by a single step, "
                 "it is O(log n). The lab timings from the sorting lecture can be read this way. "
                 "Insertion sort took 12 milliseconds for 1000 items and 47 for 2000, about four "
                 "times as long, which is the mark of n^2. Use the doubling test to check an answer "
                 "you reached by counting loops, or when a question gives you a table of timings in "
                 "place of code.", "lec15"),
                summary="Double the input: work that doubles is O(n), work that quadruples is "
                        "O(n^2), and one extra step is O(log n).",
                at="deep",
            ),
            b.prose(
                "To find the Big-O of code you are handed, count how many times the innermost line "
                "runs. Loops that follow one another add, and loops that sit inside one another "
                "multiply. An inner loop of n steps that runs once for each of n outer passes is n "
                "times n steps, not n plus n, and calling that O(n) is the slip to watch for. Once "
                "you have a count like the one in the formula below, keep its largest term and drop "
                "the constant in front of it.",
                ("Keep in mind what the answer does not tell you. Big-O is about growth and not about "
                 "speed on one input: an O(n^2) program can beat an O(n) program on a small list and "
                 "still lose badly on a large one.", "lec13"),
                summary="Count how often the innermost line runs: nested loops multiply. Keep the "
                        "largest term, and remember Big-O compares growth, not speed on one input.",
                at="standard",
            ),
            b.formula(
                "Keep the largest term",
                r"3n^2 + 5n + 2 = O(n^2)",
                "Three n squared plus five n plus two is big O of n squared.",
            ),
            b.prose(
                "Dropping terms can feel like cheating, so test it on the count in the formula. At "
                "n = 10 the three terms are 300, 50 and 2, and the first is already most of the "
                "total. At n = 1,000 they are 3,000,000, 5,000 and 2, and the smaller two no longer "
                "matter at all. The constant 3 goes for a different reason. It changes how long each "
                "step takes, which depends on the machine, and not how the work grows: doubling n "
                "multiplies 3n^2 by four exactly as it multiplies n^2 by four. Big-O keeps only "
                "what would survive a change of machine.",
                summary="As n grows the largest term swamps the rest, and a constant factor does not "
                        "change how the work scales, so both are dropped.",
                at="deep",
            ),
            b.prose(
                "You should now be able to find the Big-O of a piece of code by counting how often "
                "its innermost line runs, simplify the count to its largest term, and say why a "
                "faster growth rate matters more as the input grows. The question below gives you a "
                "pair of loops to classify.",
                summary="You can now count the innermost line, keep the largest term and name the growth rate.",
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
                ("The lab timings make the two growth rates visible. Insertion sort took 12 "
                 "milliseconds for 1000 items, 47 for 2000, 190 for 4000 and 760 for 8000: every "
                 "time the list doubles, the time goes up about four times, which is what n^2 "
                 "predicts. Merge sort took 2, 4, 9 and 19 milliseconds for the same lists, a little "
                 "more than double each time. Read the chart from left to right and watch the gap "
                 "between the two lines widen.", "lec15"),
                summary="Insertion sort is O(n^2) and merge sort is O(n log n). In the lab, doubling "
                        "the list made insertion sort about four times slower.",
            ),
            b.chart(
                "Measured sorting time", "Items", "Milliseconds",
                b.line("Insertion sort", (1000, 12), (2000, 47), (4000, 190), (8000, 760)),
                b.line("Merge sort", (1000, 2), (2000, 4), (4000, 9), (8000, 19)),
                alt="Insertion sort's time climbs steeply as the list grows while merge sort's stays close to flat.",
                source="lec15",
            ),
            b.prose(
                "Speed is not the whole comparison. Merge sort pays for its speed with memory: it "
                "needs a second array as long as the first, while insertion sort sorts the list where "
                "it stands. On a short list, or one that is nearly in order already, insertion sort "
                "has little to do and nothing extra to find, so it is the sensible choice there. When "
                "a question asks which sort to use, answer with the size and the state of the list. "
                "The table lines the two up, and its first row is the one to know cold.",
                summary="Merge sort wins on long lists but needs a second array; insertion sort suits "
                        "short or nearly sorted ones.",
                at="standard",
            ),
            b.compare(
                "Two sorts", ("Insertion sort", "Merge sort"),
                ("Worst case", "O(n^2)", "O(n log n)"),
                ("Extra memory", "None", "A second array of n items"),
                ("Good for", "Short or nearly sorted lists", "Long lists"),
                emphasis=0,
            ),
            b.prose(
                ("Sorting is usually done for the sake of searching. **Binary search** looks at the "
                 "middle of a sorted list and throws away the half that cannot hold the target, then "
                 "does the same to what is left. It only works because the list is in order: on an "
                 "unsorted list the half you throw away might hold the target. The example runs it by "
                 "hand. At every look, say which half you discard and why.", "lec15"),
                summary="Binary search halves a sorted list at each look. On an unsorted list it "
                        "cannot safely discard anything.",
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
            b.prose(
                "You should now be able to say how each sort works and what it costs, choose between "
                "them for a given list, and carry out a binary search step by step. Keep in mind the "
                "one condition the search depends on, because the question below asks about it.",
                summary="You can now compare the two sorts and run a binary search on a sorted list.",
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
                ("A **linked list** is made of **nodes**. Each node is a struct that holds a value "
                 "and a pointer to the next node, and the list as a whole is known by a single "
                 "pointer to its first node, the **head**. The last node points to NULL. That NULL "
                 "is the only thing that marks the end, and it is how a loop over the list knows to "
                 "stop.", "lec17"),
                ("This layout trades one strength for another. To insert at the front you point the "
                 "new node at the old head and move the head to the new node. No element moves, so "
                 "the cost is O(1) however long the list is. Reaching item i is the price: there is "
                 "no index arithmetic, only i pointers to follow from the head, so indexing is "
                 "O(n).", "lec17"),
                summary="A linked list is nodes chained by pointers from a head to NULL. Inserting "
                        "at the front is O(1), but reaching item i is O(n).",
            ),
            b.terms(_C["linkedlists"],
                    ("Node", "One element of the list: a value and a pointer to the next node."),
                    ("Head", "The pointer to the first node. An empty list has a NULL head.")),
            b.prose(
                ("Set a linked list beside an array and each is strong exactly where the other is "
                 "weak. An array keeps its items side by side, so it can jump to item i with "
                 "arithmetic, but putting a new item at the front means shifting every other item "
                 "along by one. A linked list scatters its nodes and joins them with pointers, so "
                 "nothing ever has to shift, but there is no way to jump: you walk. Neither is "
                 "better. The question to ask is which operation the program does most. Many lookups "
                 "by position favour an array. Many insertions and removals at the front favour a "
                 "list.", "lec17"),
                summary="Arrays index fast and insert slowly at the front; linked lists do the "
                        "reverse. Choose by the operation you do most.",
                at="deep",
            ),
            b.prose(
                ("Every operation on a linked list is a small number of pointer assignments, and the "
                 "order of those assignments is what questions test. Inserting at the front takes "
                 "two. If you move the head first, the old first node has nothing pointing at it any "
                 "more, and the rest of the list is lost with it. So the rule is to connect the new "
                 "node to the list before you disconnect anything: aim the new node's next pointer "
                 "at the old head, and only then move the head. The example goes through it. Draw "
                 "one box per node as you read.", "lec17"),
                summary="Link the new node to the list before you move the head. Moving the head "
                        "first loses the rest of the list.",
                at="standard",
            ),
            b.example(
                "Insert at the front",
                "The list is 5 -> 9 and head points at the node holding 5. Insert 2 at the front.",
                ("Make the node", "new->value = 2", "malloc one node and store the value."),
                ("Link it in", "new->next = head", "The new node now points at the old first node."),
                ("Move the head", "head = new", "The list is 2 -> 5 -> 9. Doing this before the link would lose the list."),
                source="lec17",
            ),
            b.prose(
                "Removing the first node is insertion run backwards, with one extra step that is "
                "easy to forget. Move the head to the second node and the list is correct again, but "
                "the old first node is still sitting in memory with nothing pointing at it. So keep "
                "a pointer to it before you move the head, and free it afterwards. Order matters "
                "here as well: read the old node's next pointer before you free the node, because "
                "after that its contents cannot be trusted. Like insertion, this changes two "
                "pointers and moves no elements, so it costs the same for three items or three "
                "thousand.",
                summary="To remove the first node, save a pointer to it, move the head to the second "
                        "node, then free the saved node.",
                at="deep",
            ),
            b.prose(
                "Walking a list uses the same picture. Keep a pointer to the current node, start it "
                "at the head, and move it to the next node until it is NULL. Two cases need care "
                "because they sit at the edges. An empty list has a NULL head, so a loop that follows "
                "the head without checking fails on its first step. And the loop must test the "
                "current pointer itself, not the node after it, or it stops one node early. The map "
                "shows why this topic arrives now: a node is a struct, it is reached through a "
                "pointer, and it is made with malloc.",
                summary="Walk a list from the head until the pointer is NULL. Check for an empty "
                        "list, and test the current node, not the next one.",
                at="standard",
            ),
            b.concept_map(
                "What a linked list is built from",
                (_C["pointers"], "Foundations"), (_C["structs"], "Before this"),
                (_C["dynamic"], "Before this"), (_C["linkedlists"], "This section"),
                (_C["stacks"], "Up next"),
            ),
            b.prose(
                "You should now be able to draw a list as boxes and arrows, insert and remove a node "
                "at the front in the right order, and walk the list without running off its end. The "
                "question below asks why the front of a list is cheap.",
                summary="You can now draw a list, change its front safely and walk it.",
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
