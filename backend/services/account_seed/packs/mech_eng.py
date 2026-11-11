"""Mechanical Engineering seed pack.

Student profile: a confident MATLAB programmer and solid on Physics 1
kinematics, steady but slipping in multivariable calculus once integrals
arrive, and genuinely struggling with trusses in Statics.
"""
from __future__ import annotations

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

# ---------------------------------------------------------------------------
# ENG EK 125 — Introduction to Programming for Engineers (MATLAB)
# ---------------------------------------------------------------------------

EK125 = Course(
    code="ENG EK 125",
    name="Introduction to Programming for Engineers",
    department="Engineering Core",
    nickname="MATLAB",
    color="#2563EB",
    concepts=[
        Concept(name="Vectors and Matrices", mastery=0.96,
                description="Creating arrays with [ ], colon notation and linspace; indexing with "
                            "row/column subscripts and `end`; size, numel and reshape."),
        Concept(name="Element-wise Operators", mastery=0.84,
                description="The difference between matrix operators (*, /, ^) and array operators "
                            "(.*, ./, .^), and vectorizing a formula over a whole array."),
        Concept(name="Selection Statements", mastery=0.8,
                description="if/elseif/else and switch, relational and logical operators, and "
                            "short-circuit && / || in conditions."),
        Concept(name="Loops", mastery=0.72,
                description="for loops over a range or array, while loops with a condition, running sums, "
                            "preallocation with zeros(), and when a loop can be replaced by vectorized code."),
        Concept(name="User-Defined Functions", mastery=0.66,
                description="Function files with multiple inputs and outputs, local variables and scope, "
                            "nargin, and anonymous functions with @."),
        Concept(name="Plotting and Visualization", mastery=0.58,
                description="plot, subplot, hold on, axis labels and legends, and choosing bar, scatter "
                            "or semilogy for engineering data."),
        Concept(name="Logical Indexing", mastery=0.5,
                description="Building a logical mask (x > 0) and using it to select, count with sum, or "
                            "replace elements — plus find, any and all."),
        Concept(name="Cell Arrays and Structures", mastery=0.3,
                description="Curly-brace vs parenthesis indexing of cell arrays, struct fields, and "
                            "vectors of structs for records like sensor readings."),
        Concept(name="File Input and Output", mastery=0.14,
                description="Reading data with readmatrix, readtable, fopen/fgetl/fclose and textscan, "
                            "and writing results with fprintf and writematrix."),
        Concept(name="Recursion", mastery=0.02,
                description="Functions that call themselves with a base case and a smaller subproblem, "
                            "e.g. factorial and Fibonacci, and their cost compared to loops."),
    ],
    edges=[
        Edge(source="Vectors and Matrices", target="Element-wise Operators", relationship="prerequisite", strength=0.9),
        Edge(source="Vectors and Matrices", target="Logical Indexing", relationship="prerequisite", strength=0.8),
        Edge(source="Selection Statements", target="Loops", relationship="related", strength=0.6),
        Edge(source="Element-wise Operators", target="Plotting and Visualization", relationship="prerequisite", strength=0.65),
        Edge(source="User-Defined Functions", target="Recursion", relationship="prerequisite", strength=0.85),
        Edge(source="Cell Arrays and Structures", target="File Input and Output", relationship="related", strength=0.7),
        Edge(source="Loops", target="Logical Indexing", relationship="related", strength=0.5),
    ],
    mastery_events=[
        MasteryEvent(concept="Vectors and Matrices", delta=0.1, reason="HW 1 full marks"),
        MasteryEvent(concept="Loops", delta=0.08, reason="Vectorized the HW 3 loop correctly"),
        MasteryEvent(concept="Cell Arrays and Structures", delta=-0.05, reason="Used () instead of {} on quiz"),
        MasteryEvent(concept="Logical Indexing", delta=0.12, reason="Tutor session on logical masks"),
    ],
    categories=[
        Category(name="Homework", weight=0.35),
        Category(name="Exams", weight=0.45),
        Category(name="Final Project", weight=0.2),
    ],
    assignments=[
        Assignment(title="HW 1: Variables, Vectors and the Command Window", category="Homework", type="homework",
                   due_offset_days=10, points_possible=20, points_earned=20),
        Assignment(title="HW 2: Selection Statements and a Menu-Driven Script", category="Homework", type="homework",
                   due_offset_days=24, points_possible=20, points_earned=19),
        Assignment(title="HW 3: Loops and Vectorizing Code", category="Homework", type="homework",
                   due_offset_days=38, points_possible=20, points_earned=18),
        Assignment(title="Exam 1", category="Exams", type="exam",
                   due_offset_days=50, points_possible=100, points_earned=93, is_midterm=True),
        Assignment(title="HW 4: Cell Arrays and Structs", category="Homework", type="homework",
                   due_offset_days=70, points_possible=20),
        Assignment(title="HW 5: File I/O and Sensor Data Processing", category="Homework", type="homework",
                   due_offset_days=84, points_possible=20),
        Assignment(title="Final Project: Projectile Trajectory Simulator", category="Final Project", type="project",
                   due_offset_days=98, points_possible=100),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=112, points_possible=100),
    ],
    notes=[
        Note(
            title="Vectorizing loops — HW 3 notes",
            tags=["loops", "vectorization", "hw3"],
            concepts=["Loops", "Element-wise Operators"],
            body=(
                "HW 3 asked for the sum of `1/n^2` for n = 1..1000 (should approach pi^2/6).\n\n"
                "**Loop version**\n"
                "```matlab\n"
                "total = 0;\n"
                "for n = 1:1000\n"
                "    total = total + 1/n^2;\n"
                "end\n"
                "```\n\n"
                "**Vectorized version**\n"
                "```matlab\n"
                "n = 1:1000;\n"
                "total = sum(1 ./ n.^2);\n"
                "```\n"
                "The dots matter: `n^2` tries a matrix power on a 1x1000 vector and errors. "
                "`.^` squares each element, `./` divides element-wise.\n\n"
                "**Preallocation:** if a loop must build an array, start with `y = zeros(1, N);` "
                "instead of growing `y(end+1) = ...` — growing reallocates memory every iteration and "
                "was ~20x slower when I timed it with tic/toc.\n\n"
                "Rule of thumb from lecture: if each iteration doesn't depend on the previous one, it "
                "can probably be vectorized. Running totals like a bank balance with interest do depend "
                "on the previous value, so those stay loops (or use cumsum / cumprod)."
            ),
        ),
        Note(
            title="Cell arrays vs structs (still confusing)",
            tags=["cell arrays", "structs", "hw4"],
            concepts=["Cell Arrays and Structures", "File Input and Output"],
            body=(
                "## Cell arrays — containers that hold *anything*\n"
                "```matlab\n"
                "c = {'beam', 3.2, [1 2 3]};\n"
                "c(1)   % returns a 1x1 CELL containing 'beam'\n"
                "c{1}   % returns the char array 'beam' itself\n"
                "```\n"
                "Parentheses give you the box, curly braces give you what's inside. This is the "
                "mistake I made on the quiz: `upper(c(1))` errors, `upper(c{1})` works.\n\n"
                "## Structs — named fields\n"
                "```matlab\n"
                "s.name = 'Sensor A';\n"
                "s.readings = [20.1 20.4 21.0];\n"
                "s(2).name = 'Sensor B';   % now s is a 1x2 struct array\n"
                "mean(s(1).readings)\n"
                "```\n\n"
                "When to use which: a struct when each record has the same named properties; a cell "
                "array when you just need a list of mixed things, e.g. lines of text returned by "
                "`textscan` or `strsplit`.\n\n"
                "For HW 5: `readtable` returns a table, and `T.Temperature` pulls one column — closer to "
                "a struct of column vectors."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ek125-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for ENG EK 125: problem solving and programming in MATLAB for engineers, with "
                    "weekly homework, two exams and a final simulation project.",
            concept_notes=[
                ConceptNote(name="Vectors and Matrices", description="Weeks 1–2; MATLAB's core data type."),
                ConceptNote(name="Loops", description="Weeks 4–5, with vectorization as the follow-up."),
                ConceptNote(name="Cell Arrays and Structures", description="Weeks 8–9 after Exam 1."),
                ConceptNote(name="File Input and Output", description="Weeks 10–11, feeding the final project."),
            ],
            extracted_text=(
                "ENG EK 125 Introduction to Programming for Engineers\n"
                "Boston University College of Engineering\n\n"
                "Course Description: Introduction to computer programming and algorithmic problem solving "
                "using MATLAB. Topics include variables and arrays, vectorized computation, selection and "
                "loop statements, user-defined functions, data structures (cell arrays and structures), "
                "file input/output, plotting and data visualization, and an introduction to recursion. "
                "Engineering applications are emphasized throughout.\n\n"
                "Textbook: Attaway, MATLAB: A Practical Introduction to Programming and Problem Solving.\n\n"
                "Grading\n"
                "  Homework (weekly, submitted as .m files)  35%\n"
                "  Exam 1  20%\n"
                "  Final exam  25%\n"
                "  Final project  20%\n\n"
                "Academic conduct: You may discuss approaches with classmates but all submitted code must "
                "be your own. Code is checked with similarity-detection software.\n\n"
                "Weekly schedule\n"
                "  1-2  MATLAB environment, variables, vectors and matrices, colon operator\n"
                "  3  Selection statements: if, switch, logical operators\n"
                "  4-5  Loops; vectorizing code; preallocation\n"
                "  6  User-defined functions and anonymous functions\n"
                "  7  EXAM 1 (weeks 1-6)\n"
                "  8-9  Strings, cell arrays, structures\n"
                "  10-11  File I/O: readmatrix, readtable, fprintf; data processing\n"
                "  12  Plotting for engineering reports\n"
                "  13  Recursion\n"
                "  14  Final project demos"
            ),
        ),
        Document(
            file_name="ek125-lecture06-functions.pdf",
            category="lecture_notes",
            summary="Lecture on user-defined functions in MATLAB: function file syntax, multiple return "
                    "values, variable scope, and anonymous function handles used with fzero and plotting.",
            concept_notes=[
                ConceptNote(name="User-Defined Functions", description="Header syntax and multiple outputs."),
                ConceptNote(name="Variable scope", description="Function workspaces are separate from the base workspace."),
                ConceptNote(name="Anonymous functions", description="@(x) handles passed to fzero and fplot."),
            ],
            extracted_text=(
                "Lecture 6 — User-Defined Functions\n\n"
                "A function file must have the same name as the function. General form:\n"
                "  function [out1, out2] = fname(in1, in2)\n"
                "  % FNAME  one-line description shown by help and lookfor\n"
                "      out1 = ...;\n"
                "      out2 = ...;\n"
                "  end\n\n"
                "Example — area and circumference of a circle:\n"
                "  function [A, C] = circleProps(r)\n"
                "      A = pi * r.^2;\n"
                "      C = 2 * pi * r;\n"
                "  end\n"
                "Call with [a, c] = circleProps(2). Using .^ means the function also accepts a vector of radii.\n\n"
                "Scope: variables inside a function live in the function's own workspace. They are not "
                "visible from the Command Window and do not overwrite variables there. Pass everything "
                "in as an argument and return everything you need as an output.\n\n"
                "nargin returns the number of inputs actually passed, so a function can supply defaults:\n"
                "  if nargin < 2, tol = 1e-6; end\n\n"
                "Anonymous functions: a one-line function stored in a variable.\n"
                "  f = @(x) x.^3 - 2*x - 5;\n"
                "  root = fzero(f, 2)      % approx 2.0946\n"
                "  fplot(f, [0 3]); grid on\n\n"
                "Common errors: calling a script name as a function, forgetting to assign an output, and "
                "naming a file sum.m, which shadows the built-in sum."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Difference between * and .*", back="* is matrix multiplication (inner dimensions must agree); .* multiplies element by element (same size or compatible)."),
        Flashcard(front="linspace(0, 1, 5)", back="[0 0.25 0.5 0.75 1] — five evenly spaced points including both endpoints."),
        Flashcard(front="c(2) vs c{2} for a cell array c", back="c(2) returns a 1x1 cell; c{2} returns the contents of that cell."),
        Flashcard(front="Count the negative values in vector x", back="sum(x < 0) — the logical mask is summed as 0s and 1s."),
        Flashcard(front="Why preallocate with zeros()?", back="Growing an array inside a loop reallocates memory every iteration; preallocating is much faster."),
        Flashcard(front="Anonymous function for f(x) = x^2 + 3x", back="f = @(x) x.^2 + 3*x;"),
        Flashcard(front="What does nargin return?", back="The number of input arguments the caller actually passed to the function."),
        Flashcard(front="Two parts every recursive function needs", back="A base case that stops the recursion, and a recursive call on a smaller problem."),
    ],
    study_guide=StudyGuide(
        overview="Exam 1 covers weeks 1–6: arrays, operators, selection, loops and functions. Part A is "
                 "tracing code by hand (what does this print?); Part B is writing short scripts and "
                 "functions on paper, so practise without MATLAB's autocomplete.",
        topics=[
            StudyGuideTopic(name="Arrays and operators", importance="Every tracing question depends on these.",
                            concepts=["Vectors and Matrices", "Element-wise Operators"]),
            StudyGuideTopic(name="Control flow", importance="Expect one loop and one if/switch to write.",
                            concepts=["Selection Statements", "Loops"]),
            StudyGuideTopic(name="Functions", importance="Write a function with two outputs from a word problem.",
                            concepts=["User-Defined Functions"]),
            StudyGuideTopic(name="Logical indexing", importance="Bonus-style question; a weaker spot to shore up.",
                            concepts=["Logical Indexing"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Element-wise Operators", difficulty="easy", days_ago=45, correct=[0, 1, 2],
            questions=[
                QuizQuestion(question="x = [1 2 3]; What is x.^2?",
                             options=["[1 4 9]", "14", "An error", "[2 4 6]"],
                             correct_answer="[1 4 9]",
                             explanation=".^ squares each element; x^2 on a 1x3 vector errors."),
                QuizQuestion(question="a = [1 2; 3 4]; b = [1 0; 0 1]; What is a .* b?",
                             options=["[1 0; 0 4]", "[1 2; 3 4]", "[2 2; 3 5]", "An error"],
                             correct_answer="[1 0; 0 4]",
                             explanation="Element-wise multiply by the identity zeroes the off-diagonal."),
                QuizQuestion(question="Which expression computes 1/x for every element of vector x?",
                             options=["1 ./ x", "1 / x", "x ^ -1", "inv(x)"],
                             correct_answer="1 ./ x",
                             explanation="./ divides element-wise; 1/x attempts a matrix division."),
            ],
        ),
        QuizAttempt(
            concept="Cell Arrays and Structures", difficulty="medium", days_ago=3, correct=[1, 3],
            questions=[
                QuizQuestion(question="c = {'steel', 200}; What is class(c(1))?",
                             options=["cell", "char", "double", "string"],
                             correct_answer="cell",
                             explanation="Parentheses return a sub-cell; c{1} would be char."),
                QuizQuestion(question="s.E = 200; s.nu = 0.3; How do you access Poisson's ratio?",
                             options=["s.nu", "s{nu}", "s('nu')", "nu.s"],
                             correct_answer="s.nu",
                             explanation="Struct fields use dot notation."),
                QuizQuestion(question="c = {1, 'two', [3 4]}; numel(c{3}) returns:",
                             options=["2", "3", "1", "An error"],
                             correct_answer="2",
                             explanation="c{3} is the vector [3 4], which has two elements."),
                QuizQuestion(question="Which function returns a list of substrings as a cell array?",
                             options=["strsplit", "num2str", "strcat", "fprintf"],
                             correct_answer="strsplit",
                             explanation="strsplit('a,b,c', ',') returns {'a','b','c'}."),
            ],
        ),
    ],
    session=TutorSession(
        name="Logical indexing instead of loops",
        topic="Logical Indexing",
        mode="socratic",
        summary_bullets=[
            "Replaced a for/if loop with a logical mask",
            "Used sum() on a mask to count and the mask itself to replace values",
            "Practised combining conditions with & instead of &&",
        ],
        messages=[
            ChatMessage(role="user", content="I wrote a loop that goes through temperature readings and sets any reading above 120 to NaN because the sensor glitches. It works but the TA said 'use logical indexing'. What does that mean?"),
            ChatMessage(role="assistant", content="Let's build it up. If temps = [98 130 101 125], what do you think the expression temps > 120 evaluates to?"),
            ChatMessage(role="user", content="Maybe [false true false true]? Like a 0/1 for each element?"),
            ChatMessage(role="assistant", content="Exactly — a logical array the same size as temps. MATLAB lets you index with that mask: temps(mask) picks out only the elements where the mask is true. So how would you write the replacement in one line?"),
            ChatMessage(role="user", content="temps(temps > 120) = NaN;"),
            ChatMessage(role="assistant", content="That's the whole loop in one line. Two more tricks for the same mask: sum(temps > 120) counts the glitches, since true counts as 1, and you can combine conditions with element-wise & — temps(temps < 32 | temps > 120) = NaN catches both ends. Use & and | here, not && and ||, because those short-circuit operators only work on single true/false values, not whole arrays."),
        ],
    ),
)

# ---------------------------------------------------------------------------
# ENG EK 301 — Engineering Mechanics 1 (Statics)
# ---------------------------------------------------------------------------

EK301 = Course(
    code="ENG EK 301",
    name="Engineering Mechanics 1",
    department="Engineering Core",
    nickname="Statics",
    color="#EA580C",
    concepts=[
        Concept(name="Force Vectors", mastery=0.96,
                description="Resolving forces into Cartesian components, unit vectors and direction cosines, "
                            "and position vectors r = (xB − xA)i + (yB − yA)j + (zB − zA)k."),
        Concept(name="Free-Body Diagrams", mastery=0.78,
                description="Isolating a body, replacing supports with reactions (pin: 2 forces, roller: 1, "
                            "fixed: 2 forces + moment), and drawing every external load."),
        Concept(name="Particle Equilibrium", mastery=0.7,
                description="ΣF = 0 for a particle: ΣFx = 0, ΣFy = 0 (and ΣFz = 0 in 3D), applied to cables, "
                            "pulleys and springs."),
        Concept(name="Moments and Couples", mastery=0.55,
                description="Moment of a force M = r × F, the scalar form M = Fd, Varignon's theorem, couple "
                            "moments and equivalent force-couple systems."),
        Concept(name="Rigid Body Equilibrium", mastery=0.48,
                description="ΣFx = 0, ΣFy = 0, ΣM = 0 for a rigid body; choosing a moment point to eliminate "
                            "unknowns; statically determinate vs indeterminate supports."),
        Concept(name="Method of Joints", mastery=0.4,
                description="Analysing a truss joint by joint as concurrent-force particles; tension positive, "
                            "compression negative; spotting zero-force members."),
        Concept(name="Distributed Loads", mastery=0.3,
                description="Replacing a distributed load w(x) with a resultant equal to the area under the "
                            "load curve, acting through its centroid."),
        Concept(name="Method of Sections", mastery=0.22,
                description="Cutting a truss through at most three members of unknown force and using "
                            "rigid-body equilibrium of one side to find them directly."),
        Concept(name="Friction", mastery=0.05,
                description="Dry (Coulomb) friction F ≤ μs N, impending motion, tipping vs slipping, and "
                            "wedges."),
        Concept(name="Centroids and Moments of Inertia", mastery=0.0,
                description="Centroids of composite areas x̄ = ΣxA/ΣA, area moments of inertia, and the "
                            "parallel-axis theorem I = Ic + Ad²."),
    ],
    edges=[
        Edge(source="Force Vectors", target="Particle Equilibrium", relationship="prerequisite", strength=0.9),
        Edge(source="Free-Body Diagrams", target="Particle Equilibrium", relationship="prerequisite", strength=0.85),
        Edge(source="Free-Body Diagrams", target="Rigid Body Equilibrium", relationship="prerequisite", strength=0.9),
        Edge(source="Moments and Couples", target="Rigid Body Equilibrium", relationship="prerequisite", strength=0.9),
        Edge(source="Particle Equilibrium", target="Method of Joints", relationship="prerequisite", strength=0.85),
        Edge(source="Method of Sections", target="Method of Joints", relationship="builds_on", strength=0.7),
        Edge(source="Rigid Body Equilibrium", target="Method of Sections", relationship="prerequisite", strength=0.85),
        Edge(source="Distributed Loads", target="Centroids and Moments of Inertia", relationship="related", strength=0.7),
        Edge(source="Free-Body Diagrams", target="Friction", relationship="prerequisite", strength=0.7),
    ],
    mastery_events=[
        MasteryEvent(concept="Force Vectors", delta=0.12, reason="HW 1: 28/30"),
        MasteryEvent(concept="Moments and Couples", delta=-0.06, reason="Sign errors on HW 3 cross products"),
        MasteryEvent(concept="Method of Joints", delta=-0.08, reason="HW 4: mixed up tension and compression"),
        MasteryEvent(concept="Method of Sections", delta=0.1, reason="Tutor session cutting a Pratt truss"),
    ],
    categories=[
        Category(name="Homework", weight=0.2),
        Category(name="Exams", weight=0.55),
        Category(name="Truss Project", weight=0.25),
    ],
    assignments=[
        Assignment(title="HW 1: Force Vectors in 2D and 3D", category="Homework", type="homework",
                   due_offset_days=9, points_possible=30, points_earned=28),
        Assignment(title="HW 2: Particle Equilibrium and FBDs", category="Homework", type="homework",
                   due_offset_days=21, points_possible=30, points_earned=26),
        Assignment(title="HW 3: Moments, Couples and Equivalent Systems", category="Homework", type="homework",
                   due_offset_days=35, points_possible=30, points_earned=22),
        Assignment(title="Midterm Exam: Particles and Rigid Bodies", category="Exams", type="exam",
                   due_offset_days=48, points_possible=100, points_earned=71, is_midterm=True),
        Assignment(title="HW 4: Method of Joints and Sections", category="Homework", type="homework",
                   due_offset_days=62, points_possible=30, points_earned=19),
        Assignment(title="Truss Analysis Project: Design Report", category="Truss Project", type="project",
                   due_offset_days=85, points_possible=100),
        Assignment(title="HW 5: Distributed Loads and Friction", category="Homework", type="homework",
                   due_offset_days=94, points_possible=30),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=110, points_possible=100),
    ],
    notes=[
        Note(
            title="Rigid body equilibrium — my checklist",
            tags=["equilibrium", "FBD", "midterm"],
            concepts=["Rigid Body Equilibrium", "Free-Body Diagrams", "Moments and Couples"],
            body=(
                "1. **Draw the FBD.** Remove every support and replace with reactions:\n"
                "   - Pin -> Ax, Ay\n"
                "   - Roller -> one force normal to the surface\n"
                "   - Fixed support -> Ax, Ay, **M_A**\n"
                "2. **Count unknowns.** 2D gives 3 equations. More than 3 unknowns = statically indeterminate "
                "(not on our exams).\n"
                "3. **Take moments about the point with the most unknowns** — they drop out.\n"
                "4. Then ΣFx = 0 and ΣFy = 0 for the rest.\n"
                "5. **Sanity check** with a moment sum about a different point.\n\n"
                "**Sign convention:** counterclockwise moments positive. I lost points on HW 3 because I "
                "switched conventions halfway through a problem.\n\n"
                "**Example (simply supported beam):** 6 m span, 12 kN point load 2 m from A.\n"
                "ΣM_A = 0: B_y(6) − 12(2) = 0 -> **B_y = 4 kN**\n"
                "ΣFy = 0: A_y + 4 − 12 = 0 -> **A_y = 8 kN**\n"
                "Makes sense: the load is closer to A, so A carries more.\n\n"
                "A negative answer just means the reaction points the other way — don't redraw the FBD."
            ),
        ),
        Note(
            title="Trusses — joints vs sections",
            tags=["trusses", "project"],
            concepts=["Method of Joints", "Method of Sections", "Particle Equilibrium"],
            body=(
                "**Assumptions:** members are two-force members, pinned at the joints, loads only at the joints, "
                "weight neglected. So each member force is purely axial.\n\n"
                "### Method of joints\n"
                "- Find support reactions first (whole-truss FBD)\n"
                "- Start at a joint with **≤ 2 unknowns**\n"
                "- Assume every member is in **tension** (arrow pulling away from the joint). A negative "
                "result = compression. Keep the sign when moving to the next joint!\n\n"
                "### Zero-force members\n"
                "- Two non-collinear members at an unloaded joint -> both zero\n"
                "- Three members, two collinear, unloaded joint -> the third is zero\n\n"
                "### Method of sections\n"
                "- Cut through **at most 3** members including the one you want\n"
                "- Take moments about the point where the other two cut members intersect -> one equation, "
                "one unknown\n\n"
                "For the truss project we need the force in every member to size them, so joints for the "
                "full table and sections to double-check the critical members at midspan."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ek301-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for ENG EK 301 Engineering Mechanics 1: statics of particles and rigid bodies, "
                    "trusses, distributed loads, friction and centroids, plus a team truss design project.",
            concept_notes=[
                ConceptNote(name="Force Vectors", description="Weeks 1–2, 2D and 3D components."),
                ConceptNote(name="Rigid Body Equilibrium", description="Weeks 5–6, core of the midterm."),
                ConceptNote(name="Method of Joints", description="Weeks 8–9, basis of the truss project."),
                ConceptNote(name="Friction", description="Week 12, after distributed loads."),
            ],
            extracted_text=(
                "ENG EK 301 Engineering Mechanics 1\n"
                "Boston University College of Engineering\n\n"
                "Course Description: Vector description of forces and moments. Equilibrium of particles and "
                "rigid bodies in two and three dimensions. Analysis of trusses, frames and machines. "
                "Distributed loads, centroids and area moments of inertia. Dry friction. Emphasis on "
                "drawing correct free-body diagrams and on systematic problem solving.\n\n"
                "Prerequisites: CAS PY 211 or concurrent enrollment; CAS MA 124 or equivalent.\n\n"
                "Grading\n"
                "  Homework  20%\n"
                "  Midterm exam  25%\n"
                "  Final exam  30%\n"
                "  Truss design project  25%\n\n"
                "Truss Design Project: Teams of three design a planar truss to span a fixed gap and carry "
                "a specified joint load at the lowest cost, where cost = material cost per unit length + "
                "cost per joint. Teams must compute every member force by the method of joints in MATLAB, "
                "identify the critical compression member using the provided buckling strength fit, and "
                "predict the failure load. Deliverables: design report, MATLAB code, and a cost table.\n\n"
                "Homework is due Fridays at 11:59 pm. Show the FBD for every problem: an answer without a "
                "free-body diagram receives at most half credit.\n\n"
                "Schedule\n"
                "  1-2  Force vectors, dot product, unit vectors\n"
                "  3-4  Particle equilibrium; moments and couples\n"
                "  5-6  Rigid body equilibrium in 2D and 3D\n"
                "  7  MIDTERM\n"
                "  8-9  Trusses: method of joints, method of sections\n"
                "  10-11  Distributed loads; centroids\n"
                "  12  Friction; 13 Moments of inertia"
            ),
        ),
        Document(
            file_name="ek301-lecture15-method-of-sections.pdf",
            category="lecture_notes",
            summary="Lecture on the method of sections for trusses: choosing a cut, taking moments about the "
                    "intersection of two cut members, and a worked Howe truss example.",
            concept_notes=[
                ConceptNote(name="Method of Sections", description="Cut through no more than three unknown members."),
                ConceptNote(name="Rigid Body Equilibrium", description="Each side of the cut is a rigid body in equilibrium."),
                ConceptNote(name="Zero-force members", description="Identify them first to simplify the analysis."),
                ConceptNote(name="Method of Joints", description="Used to check the sections result at one joint."),
            ],
            extracted_text=(
                "Lecture 15 — Trusses: The Method of Sections\n\n"
                "When to use it: you need the force in a few specific members, usually in the middle of a "
                "long truss, and working joint by joint from the support would take many steps and "
                "accumulate rounding error.\n\n"
                "Procedure\n"
                "  1. Find the support reactions from the FBD of the entire truss.\n"
                "  2. Pass an imaginary section through the truss, cutting the member of interest and no "
                "more than three members with unknown forces.\n"
                "  3. Draw the FBD of ONE side of the cut. Show each cut member force as tension (pointing "
                "away from the section).\n"
                "  4. Apply rigid-body equilibrium: ΣFx = 0, ΣFy = 0, ΣM = 0.\n"
                "  5. Choose the moment point at the intersection of two unknown member lines of action so "
                "that the third force is found from a single equation.\n\n"
                "Example: Howe truss, 6 panels at 3 m, height 4 m, 20 kN at each lower joint. By symmetry "
                "Ay = Gy = 50 kN. Cut through panel 3. Moments about the upper joint above the cut "
                "give the bottom chord force: F_bottom(4) = 50(9) − 20(6) − 20(3) = 270, so "
                "F_bottom = 67.5 kN (T). Moments about the lower joint give the top chord in compression. "
                "Vertical force balance gives the diagonal.\n\n"
                "Check: the top and bottom chords near midspan carry the largest forces — the truss acts "
                "like a deep beam, with compression on top and tension on the bottom."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Reactions at a pin, a roller and a fixed support (2D)", back="Pin: 2 forces. Roller: 1 force normal to the surface. Fixed: 2 forces + 1 couple moment."),
        Flashcard(front="Moment of a force (vector form)", back="M_O = r × F, where r runs from O to any point on the line of action of F."),
        Flashcard(front="Varignon's theorem", back="The moment of a force about a point equals the sum of the moments of its components about that point."),
        Flashcard(front="Equilibrium equations for a 2D rigid body", back="ΣFx = 0, ΣFy = 0, ΣM_O = 0 — three independent equations."),
        Flashcard(front="Zero-force member rule (two members)", back="If only two non-collinear members meet at an unloaded joint, both carry zero force."),
        Flashcard(front="Method of sections: max unknown members per cut", back="Three — one for each 2D equilibrium equation."),
        Flashcard(front="Resultant of a triangular distributed load", back="Magnitude = ½ w₀ L, acting at L/3 from the large end (2L/3 from the zero end)."),
        Flashcard(front="Static friction condition", back="F ≤ μs N; at impending motion F = μs N."),
        Flashcard(front="Parallel-axis theorem", back="I = I_c + A d², where d is the distance from the centroidal axis."),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers weeks 1–6: force vectors, particle equilibrium, moments and rigid "
                 "body equilibrium. Every problem starts from a free-body diagram, and FBDs are graded "
                 "separately — a correct FBD earns partial credit even if the algebra goes wrong.",
        topics=[
            StudyGuideTopic(name="Forces in 3D", importance="One full problem with position vectors and unit vectors.",
                            concepts=["Force Vectors", "Particle Equilibrium"]),
            StudyGuideTopic(name="Moments", importance="Cross products are where you've been losing points; practise the sign.",
                            concepts=["Moments and Couples"]),
            StudyGuideTopic(name="Rigid body equilibrium", importance="Two of the four exam problems.",
                            concepts=["Rigid Body Equilibrium", "Free-Body Diagrams"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Moments and Couples", difficulty="medium", days_ago=38, correct=[0, 2],
            questions=[
                QuizQuestion(question="A 50 N force acts perpendicular to a 0.4 m wrench. The moment about the bolt is:",
                             options=["20 N·m", "125 N·m", "50.4 N·m", "12.5 N·m"],
                             correct_answer="20 N·m",
                             explanation="M = Fd = 50 × 0.4 = 20 N·m."),
                QuizQuestion(question="r = 2i m and F = 3j N. M = r × F equals:",
                             options=["6k N·m", "−6k N·m", "6i N·m", "0"],
                             correct_answer="6k N·m",
                             explanation="i × j = k, so (2)(3)k = 6k."),
                QuizQuestion(question="A couple moment has the same value about:",
                             options=["Every point", "Only its centroid", "Only the origin", "Points on its line of action"],
                             correct_answer="Every point",
                             explanation="A couple is a free vector."),
                QuizQuestion(question="Moving a force to a parallel line of action requires adding:",
                             options=["A couple moment equal to F times the offset distance", "A second equal force",
                                      "Nothing, forces are free vectors", "A distributed load"],
                             correct_answer="A couple moment equal to F times the offset distance",
                             explanation="An equivalent force-couple system keeps the same resultant moment."),
            ],
        ),
        QuizAttempt(
            concept="Method of Joints", difficulty="hard", days_ago=8, correct=[1],
            questions=[
                QuizQuestion(question="At an unloaded joint, members AB and AC are collinear and AD is not. The force in AD is:",
                             options=["Zero", "Equal to AB", "Equal to AB + AC", "Cannot be determined"],
                             correct_answer="Zero",
                             explanation="With no load, nothing balances AD's perpendicular component, so it must be zero."),
                QuizQuestion(question="Solving a joint you get F_AB = −12 kN with tension assumed. Member AB is:",
                             options=["In compression, 12 kN", "In tension, 12 kN", "A zero-force member", "Statically indeterminate"],
                             correct_answer="In compression, 12 kN",
                             explanation="A negative result reverses the assumed tension."),
                QuizQuestion(question="Why start the method of joints at a support joint?",
                             options=["It usually has at most two unknown member forces once reactions are known",
                                      "Supports carry no force", "Moments are zero there", "It avoids zero-force members"],
                             correct_answer="It usually has at most two unknown member forces once reactions are known",
                             explanation="A joint is a particle, so it gives only two equations in 2D."),
            ],
        ),
    ],
    session=TutorSession(
        name="Method of sections on a Pratt truss",
        topic="Method of Sections",
        mode="socratic",
        summary_bullets=[
            "Chose a cut through three members including the one asked for",
            "Picked the moment point where two unknown members intersect",
            "Interpreted the sign to call the member tension or compression",
        ],
        messages=[
            ChatMessage(role="user", content="HW 4 asks for the force in member CD in the middle of a Pratt truss. Doing joints from A takes forever and my numbers keep drifting. Is there a faster way?"),
            ChatMessage(role="assistant", content="That's exactly what the method of sections is for. Since you already have the reactions, where would you cut so you slice through CD and no more than two other members?"),
            ChatMessage(role="user", content="Through CD on the top chord, the diagonal DI, and the bottom chord IJ?"),
            ChatMessage(role="assistant", content="Good, that's three unknowns, which a 2D rigid body can handle. Now, if you only want CD, which point could you take moments about so that DI and IJ both drop out?"),
            ChatMessage(role="user", content="Where DI and IJ meet — joint I. Then only CD and the left reaction plus the loads make moments."),
            ChatMessage(role="assistant", content="Exactly. Sum moments about I on the left piece: Ay times its distance to I, minus each joint load times its distance, plus F_CD times the truss height. If F_CD comes out negative while assumed in tension, CD is in compression, which is what you'd expect for a top chord near midspan. One equation, one unknown, and no drift from earlier joints."),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS MA 225 — Multivariate Calculus
# ---------------------------------------------------------------------------

MA225 = Course(
    code="CAS MA 225",
    name="Multivariate Calculus",
    department="Mathematics & Statistics",
    nickname="Calc III",
    color="#7C3AED",
    concepts=[
        Concept(name="Dot and Cross Products", mastery=0.96,
                description="u·v = |u||v|cos θ for angles and projections; u×v perpendicular to both, with "
                            "|u×v| equal to the parallelogram area."),
        Concept(name="Lines and Planes in Space", mastery=0.76,
                description="Vector and parametric equations of lines, the plane a(x−x₀)+b(y−y₀)+c(z−z₀)=0 "
                            "from a normal vector, and distances between them."),
        Concept(name="Partial Derivatives", mastery=0.68,
                description="Differentiating with respect to one variable holding the others fixed; "
                            "higher-order partials and Clairaut's theorem."),
        Concept(name="Gradient and Directional Derivatives", mastery=0.57,
                description="∇f = ⟨fx, fy, fz⟩ points in the direction of steepest ascent; D_u f = ∇f · u for "
                            "a unit vector u."),
        Concept(name="Multivariable Chain Rule", mastery=0.45,
                description="dz/dt = fx dx/dt + fy dy/dt and tree diagrams for composite functions of "
                            "several variables."),
        Concept(name="Double Integrals", mastery=0.38,
                description="Iterated integrals over rectangles and general regions, choosing the order of "
                            "integration, and Fubini's theorem."),
        Concept(name="Lagrange Multipliers", mastery=0.27,
                description="Optimising f subject to g = k by solving ∇f = λ∇g together with the "
                            "constraint."),
        Concept(name="Double Integrals in Polar Coordinates", mastery=0.12,
                description="Converting with x = r cos θ, y = r sin θ and dA = r dr dθ for circular and "
                            "annular regions."),
        Concept(name="Triple Integrals", mastery=0.04,
                description="Integrating over solid regions in rectangular, cylindrical and spherical "
                            "coordinates (dV = ρ² sin φ dρ dφ dθ)."),
        Concept(name="Line Integrals and Green's Theorem", mastery=0.0,
                description="Work as ∫C F·dr, conservative fields and path independence, and Green's theorem "
                            "relating a circulation to a double integral."),
    ],
    edges=[
        Edge(source="Dot and Cross Products", target="Lines and Planes in Space", relationship="prerequisite", strength=0.85),
        Edge(source="Partial Derivatives", target="Gradient and Directional Derivatives", relationship="prerequisite", strength=0.9),
        Edge(source="Partial Derivatives", target="Multivariable Chain Rule", relationship="prerequisite", strength=0.85),
        Edge(source="Gradient and Directional Derivatives", target="Lagrange Multipliers", relationship="prerequisite", strength=0.85),
        Edge(source="Dot and Cross Products", target="Gradient and Directional Derivatives", relationship="related", strength=0.55),
        Edge(source="Double Integrals", target="Double Integrals in Polar Coordinates", relationship="prerequisite", strength=0.8),
        Edge(source="Triple Integrals", target="Double Integrals", relationship="builds_on", strength=0.8),
        Edge(source="Line Integrals and Green's Theorem", target="Double Integrals", relationship="builds_on", strength=0.65),
    ],
    mastery_events=[
        MasteryEvent(concept="Dot and Cross Products", delta=0.1, reason="WeBWorK 1 completed 20/20"),
        MasteryEvent(concept="Multivariable Chain Rule", delta=-0.07, reason="Quiz 2: missed a branch of the tree"),
        MasteryEvent(concept="Lagrange Multipliers", delta=0.09, reason="Tutor session on the box problem"),
        MasteryEvent(concept="Gradient and Directional Derivatives", delta=0.06, reason="Flashcard review"),
    ],
    categories=[
        Category(name="WeBWorK Homework", weight=0.2),
        Category(name="Quizzes", weight=0.15),
        Category(name="Exams", weight=0.65),
    ],
    assignments=[
        Assignment(title="WeBWorK 1: Vectors, Dot and Cross Products", category="WeBWorK Homework", type="homework",
                   due_offset_days=8, points_possible=20, points_earned=20),
        Assignment(title="WeBWorK 3: Partial Derivatives and Tangent Planes", category="WeBWorK Homework", type="homework",
                   due_offset_days=27, points_possible=20, points_earned=18),
        Assignment(title="Quiz 2: Chain Rule and Gradient", category="Quizzes", type="quiz",
                   due_offset_days=34, points_possible=10, points_earned=7),
        Assignment(title="WeBWorK 5: Lagrange Multipliers", category="WeBWorK Homework", type="homework",
                   due_offset_days=55, points_possible=20, points_earned=14),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=68, points_possible=100, is_midterm=True),
        Assignment(title="WeBWorK 8: Triple Integrals", category="WeBWorK Homework", type="homework",
                   due_offset_days=88, points_possible=20),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=113, points_possible=100),
    ],
    notes=[
        Note(
            title="Gradient, directional derivative, tangent plane",
            tags=["gradient", "midterm"],
            concepts=["Gradient and Directional Derivatives", "Partial Derivatives", "Lines and Planes in Space"],
            body=(
                "**Gradient:** ∇f(x, y) = ⟨fx, fy⟩\n\n"
                "**Directional derivative** in direction of unit vector **u**: D_u f = ∇f · u\n"
                "- Must normalise u first! (lost a point on WeBWorK for using ⟨3, 4⟩ instead of ⟨3/5, 4/5⟩)\n"
                "- Max value of D_u f is |∇f|, in the direction of ∇f\n"
                "- D_u f = 0 when u is perpendicular to ∇f -> that's along the level curve\n\n"
                "**Example:** f = x²y + 3y at (1, 2)\n"
                "fx = 2xy = 4, fy = x² + 3 = 4 -> ∇f = ⟨4, 4⟩\n"
                "u = ⟨3/5, 4/5⟩ -> D_u f = 12/5 + 16/5 = **28/5**\n"
                "Steepest ascent rate = |⟨4, 4⟩| = **4√2**\n\n"
                "**Tangent plane** to z = f(x, y) at (a, b):\n"
                "z − f(a, b) = fx(a, b)(x − a) + fy(a, b)(y − b)\n\n"
                "For a level surface F(x, y, z) = k, ∇F is the **normal vector** to the tangent plane — "
                "this is the connection to the plane equations from week 2."
            ),
        ),
        Note(
            title="Lagrange multipliers — step by step",
            tags=["optimization", "lagrange"],
            concepts=["Lagrange Multipliers", "Gradient and Directional Derivatives"],
            body=(
                "**Goal:** max/min f(x, y) subject to g(x, y) = k.\n\n"
                "**Idea:** at the optimum, the level curve of f is tangent to the constraint curve, so "
                "their gradients are parallel: **∇f = λ∇g**.\n\n"
                "**Steps**\n"
                "1. Write fx = λgx, fy = λgy, and g = k (3 equations, 3 unknowns x, y, λ)\n"
                "2. Eliminate λ — usually divide the first two equations\n"
                "3. Substitute into the constraint\n"
                "4. Evaluate f at **every** candidate point; biggest = max, smallest = min\n\n"
                "**Example:** maximise f = xy on x + y = 10\n"
                "y = λ, x = λ -> x = y -> 2x = 10 -> (5, 5), f = 25 ✔\n\n"
                "Where I go wrong: dividing by a variable that could be zero and losing solutions. "
                "Check the x = 0 or y = 0 cases separately.\n\n"
                "Interpretation of λ: rate of change of the optimal value as k changes (shadow price)."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ma225-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for CAS MA 225 Multivariate Calculus: vectors, partial derivatives, optimization, "
                    "multiple integrals and vector calculus, graded by WeBWorK, quizzes, a midterm and a final.",
            concept_notes=[
                ConceptNote(name="Dot and Cross Products", description="Chapter 12, first two weeks."),
                ConceptNote(name="Lagrange Multipliers", description="End of Chapter 14, right before the midterm."),
                ConceptNote(name="Double Integrals", description="Chapter 15, included on the midterm."),
                ConceptNote(name="Line Integrals and Green's Theorem", description="Chapter 16, final weeks."),
            ],
            extracted_text=(
                "CAS MA 225 Multivariate Calculus\n"
                "Department of Mathematics & Statistics, Boston University\n\n"
                "Course Description: Vectors, lines, planes, and surfaces in three-dimensional space. "
                "Functions of several variables: partial derivatives, gradients and directional "
                "derivatives, the chain rule, tangent planes, and optimization including Lagrange "
                "multipliers. Double and triple integrals in rectangular, polar, cylindrical and spherical "
                "coordinates. Introduction to vector calculus: vector fields, line integrals and Green's "
                "theorem.\n\n"
                "Prerequisite: CAS MA 124 or equivalent.\n"
                "Text: Stewart, Calculus: Early Transcendentals, Chapters 12-16.\n\n"
                "Grading\n"
                "  WeBWorK homework  20% (lowest two dropped)\n"
                "  Discussion quizzes  15%\n"
                "  Midterm exam  30%\n"
                "  Final exam (cumulative)  35%\n\n"
                "WeBWorK sets close Thursdays at 11:59 pm. Each problem allows unlimited attempts. "
                "Discussion quizzes are 15 minutes at the start of section on weeks with no exam.\n\n"
                "Tentative schedule\n"
                "  Weeks 1-2  12.1-12.6 Vectors, dot and cross product, lines and planes\n"
                "  Weeks 3-4  14.1-14.4 Functions of several variables, partial derivatives, tangent planes\n"
                "  Weeks 5-6  14.5-14.8 Chain rule, gradient, extrema, Lagrange multipliers\n"
                "  Week 7  15.1-15.3 Double integrals\n"
                "  Week 8  15.4 Polar coordinates; MIDTERM (through 15.4)\n"
                "  Weeks 10-11  15.6-15.8 Triple integrals\n"
                "  Weeks 12-14  16.1-16.4 Vector fields, line integrals, Green's theorem"
            ),
        ),
        Document(
            file_name="ma225-lecture-15-4-polar.pdf",
            category="lecture_notes",
            summary="Lecture notes on double integrals in polar coordinates: the r dr dθ area element, "
                    "describing circular regions, and two worked examples including a volume under a paraboloid.",
            concept_notes=[
                ConceptNote(name="Double Integrals in Polar Coordinates", description="dA = r dr dθ and polar regions."),
                ConceptNote(name="Double Integrals", description="Iterated integrals as the starting point."),
                ConceptNote(name="Jacobian factor r", description="Why the extra r appears in the area element."),
            ],
            extracted_text=(
                "15.4 Double Integrals in Polar Coordinates\n\n"
                "Motivation: regions bounded by circles are awkward in x and y. The disk x² + y² ≤ 4 needs "
                "−√(4 − x²) ≤ y ≤ √(4 − x²), but in polar coordinates it is simply 0 ≤ r ≤ 2, 0 ≤ θ ≤ 2π.\n\n"
                "Conversion: x = r cos θ, y = r sin θ, x² + y² = r²\n"
                "Area element: dA = r dr dθ (do NOT forget the r)\n\n"
                "Why the r? A small polar rectangle has radial side Δr and arc side r Δθ, so its area is "
                "approximately r Δr Δθ. Equivalently, the Jacobian of (r, θ) -> (x, y) is r.\n\n"
                "Example 1: ∬_R (3x + 4y²) dA, R = upper half annulus 1 ≤ r ≤ 2, 0 ≤ θ ≤ π\n"
                "  = ∫₀^π ∫₁² (3r cos θ + 4r² sin²θ) r dr dθ = 15π/2\n\n"
                "Example 2: Volume under z = 1 − x² − y² above the xy-plane\n"
                "  The paraboloid meets z = 0 on the unit circle, so 0 ≤ r ≤ 1.\n"
                "  V = ∫₀^{2π} ∫₀¹ (1 − r²) r dr dθ = 2π [r²/2 − r⁴/4]₀¹ = 2π(1/4) = π/2\n\n"
                "Regions between curves: for r = 1 + cos θ (cardioid), the area is "
                "∫₀^{2π} ∫₀^{1+cos θ} r dr dθ = 3π/2.\n\n"
                "Exam tip: decide whether the region or the integrand is circular. Either one is a good "
                "reason to switch to polar."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Angle between vectors u and v", back="cos θ = (u·v) / (|u||v|)"),
        Flashcard(front="Normal vector to the plane 2x − y + 3z = 7", back="⟨2, −1, 3⟩"),
        Flashcard(front="Directional derivative D_u f", back="∇f · u, where u is a UNIT vector."),
        Flashcard(front="Direction and rate of steepest ascent", back="Direction of ∇f; rate equals |∇f|."),
        Flashcard(front="Lagrange multiplier condition", back="∇f = λ∇g together with the constraint g(x, y) = k."),
        Flashcard(front="Polar area element", back="dA = r dr dθ"),
        Flashcard(front="Second derivative test discriminant", back="D = fxx fyy − (fxy)². D > 0 and fxx > 0 -> local min; D > 0 and fxx < 0 -> local max; D < 0 -> saddle."),
        Flashcard(front="Spherical volume element", back="dV = ρ² sin φ dρ dφ dθ"),
    ],
    study_guide=StudyGuide(
        overview="The midterm covers Stewart 12.1–15.4: vectors and planes, partial derivatives through "
                 "Lagrange multipliers, and double integrals including polar. The second half is where "
                 "your quiz and WeBWorK scores dipped, so weight your review toward optimisation and "
                 "integration.",
        topics=[
            StudyGuideTopic(name="Vectors, lines and planes", importance="Reliable early points — a quick review is enough.",
                            concepts=["Dot and Cross Products", "Lines and Planes in Space"]),
            StudyGuideTopic(name="Derivatives of several variables", importance="Chain rule tree diagrams and gradients.",
                            concepts=["Partial Derivatives", "Multivariable Chain Rule", "Gradient and Directional Derivatives"]),
            StudyGuideTopic(name="Constrained optimisation", importance="Always one full Lagrange problem; practise the algebra.",
                            concepts=["Lagrange Multipliers"]),
            StudyGuideTopic(name="Double integrals", importance="Setting up bounds and switching to polar — highest priority.",
                            concepts=["Double Integrals", "Double Integrals in Polar Coordinates"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Gradient and Directional Derivatives", difficulty="medium", days_ago=36, correct=[0, 1, 3],
            questions=[
                QuizQuestion(question="For f(x, y) = x²y, ∇f at (1, 3) is:",
                             options=["⟨6, 1⟩", "⟨2, 1⟩", "⟨6, 3⟩", "⟨3, 1⟩"],
                             correct_answer="⟨6, 1⟩",
                             explanation="fx = 2xy = 6, fy = x² = 1."),
                QuizQuestion(question="The maximum rate of change of f at a point equals:",
                             options=["|∇f|", "fx + fy", "∇f · ∇f", "The largest partial derivative"],
                             correct_answer="|∇f|",
                             explanation="D_u f = |∇f| cos θ is largest when u points along ∇f."),
                QuizQuestion(question="Before computing D_u f in the direction ⟨1, 1⟩ you must:",
                             options=["Normalise it to ⟨1/√2, 1/√2⟩", "Square each component", "Take its cross product with ∇f", "Nothing"],
                             correct_answer="Normalise it to ⟨1/√2, 1/√2⟩",
                             explanation="The formula requires a unit vector."),
                QuizQuestion(question="The gradient of f is always ______ to the level curves of f.",
                             options=["Perpendicular", "Parallel", "Tangent", "Unrelated"],
                             correct_answer="Perpendicular",
                             explanation="Along a level curve f doesn't change, so ∇f · u = 0."),
            ],
        ),
        QuizAttempt(
            concept="Double Integrals in Polar Coordinates", difficulty="hard", days_ago=2, correct=[1],
            questions=[
                QuizQuestion(question="∬_D (x² + y²) dA over the disk of radius 2 equals:",
                             options=["8π", "4π", "16π", "2π"],
                             correct_answer="8π",
                             explanation="∫₀^{2π}∫₀² r²·r dr dθ = 2π · 4 = 8π."),
                QuizQuestion(question="In polar coordinates dA equals:",
                             options=["r dr dθ", "dr dθ", "r² dr dθ", "r sin θ dr dθ"],
                             correct_answer="r dr dθ",
                             explanation="The Jacobian of the polar transformation is r."),
                QuizQuestion(question="The region in the first quadrant between circles of radius 1 and 3 is:",
                             options=["1 ≤ r ≤ 3, 0 ≤ θ ≤ π/2", "0 ≤ r ≤ 3, 0 ≤ θ ≤ π/2", "1 ≤ r ≤ 3, 0 ≤ θ ≤ π", "1 ≤ r ≤ 9, 0 ≤ θ ≤ π/2"],
                             correct_answer="1 ≤ r ≤ 3, 0 ≤ θ ≤ π/2",
                             explanation="An annular sector: r between the radii, θ over the first quadrant."),
            ],
        ),
    ],
    session=TutorSession(
        name="Lagrange multipliers: the open box",
        topic="Lagrange Multipliers",
        mode="expository",
        summary_bullets=[
            "Set up f, g and ∇f = λ∇g for an open-top box with fixed surface area",
            "Eliminated λ by dividing equations to find x = y = 2z",
            "Checked the answer makes physical sense",
        ],
        messages=[
            ChatMessage(role="user", content="WeBWorK 5 #4: open-top box, surface area 12 m², maximise volume. I set ∇V = λ∇S but the algebra gets messy. Can you walk me through it?"),
            ChatMessage(role="assistant", content="Sure. V = xyz and the constraint is S = xy + 2xz + 2yz = 12; there's only one xy term because the top is open. The gradient equations are: yz = λ(y + 2z), xz = λ(x + 2z), and xy = λ(2x + 2y)."),
            ChatMessage(role="user", content="That's where I get stuck — three equations with λ in all of them."),
            ChatMessage(role="assistant", content="The trick is to multiply each equation so the left sides match: multiply the first by x, the second by y, the third by z. Every left side becomes xyz, so the right sides must be equal too: λ(xy + 2xz) = λ(xy + 2yz) = λ(2xz + 2yz). λ can't be 0, because then the volume would be zero, so you can cancel it."),
            ChatMessage(role="user", content="So xy + 2xz = xy + 2yz gives x = y, and xy + 2yz = 2xz + 2yz gives xy = 2xz, so y = 2z."),
            ChatMessage(role="assistant", content="Exactly — x = y = 2z. Substitute into the constraint: 4z² + 4z² + 4z² = 12, so z = 1, and x = y = 2. Maximum volume is 4 m³. Sanity check: an open box should be twice as wide as it is tall, since the missing lid lets it grow sideways. That pattern of multiplying to match the left sides works on most symmetric Lagrange problems."),
        ],
    ),
)

# ---------------------------------------------------------------------------
# CAS PY 211 — General Physics 1
# ---------------------------------------------------------------------------

PY211 = Course(
    code="CAS PY 211",
    name="General Physics 1",
    department="Physics",
    nickname="Physics 1",
    color="#16A34A",
    concepts=[
        Concept(name="One-Dimensional Kinematics", mastery=0.96,
                description="Displacement, velocity and acceleration; the constant-acceleration equations "
                            "v = v₀ + at, x = x₀ + v₀t + ½at², v² = v₀² + 2aΔx."),
        Concept(name="Projectile Motion", mastery=0.8,
                description="Independent horizontal (constant velocity) and vertical (a = −g) motion; range, "
                            "maximum height and time of flight."),
        Concept(name="Newton's Laws of Motion", mastery=0.76,
                description="Inertia, ΣF = ma, and action–reaction pairs; drawing force diagrams and applying "
                            "Newton's second law along chosen axes."),
        Concept(name="Friction and Inclined Planes", mastery=0.64,
                description="Static and kinetic friction (fs ≤ μs N, fk = μk N), tilted axes on an incline, "
                            "and N = mg cos θ."),
        Concept(name="Uniform Circular Motion", mastery=0.52,
                description="Centripetal acceleration a = v²/r, the net force toward the centre, banked "
                            "curves and vertical loops."),
        Concept(name="Work-Energy Theorem", mastery=0.47,
                description="W = F·d = Fd cos θ, kinetic energy ½mv², and W_net = ΔK; work by variable "
                            "forces like springs (½kx²)."),
        Concept(name="Conservation of Energy", mastery=0.36,
                description="K + U conserved when only conservative forces act; Ki + Ui + W_nc = Kf + Uf when "
                            "friction does work."),
        Concept(name="Momentum and Collisions", mastery=0.2,
                description="p = mv, impulse J = FΔt = Δp, and conservation of momentum in elastic and "
                            "perfectly inelastic collisions."),
        Concept(name="Rotational Dynamics", mastery=0.07,
                description="Torque τ = rF sin θ, moment of inertia, τ = Iα, and rotational kinetic energy "
                            "½Iω² for rolling objects."),
        Concept(name="Simple Harmonic Motion", mastery=0.0,
                description="Mass-spring and pendulum oscillators, ω = √(k/m), period T = 2π√(L/g), and "
                            "energy exchange in oscillation."),
    ],
    edges=[
        Edge(source="One-Dimensional Kinematics", target="Projectile Motion", relationship="prerequisite", strength=0.9),
        Edge(source="Newton's Laws of Motion", target="Friction and Inclined Planes", relationship="prerequisite", strength=0.85),
        Edge(source="Newton's Laws of Motion", target="Uniform Circular Motion", relationship="prerequisite", strength=0.8),
        Edge(source="Conservation of Energy", target="Work-Energy Theorem", relationship="builds_on", strength=0.8),
        Edge(source="Newton's Laws of Motion", target="Momentum and Collisions", relationship="related", strength=0.6),
        Edge(source="Momentum and Collisions", target="Rotational Dynamics", relationship="related", strength=0.5),
        Edge(source="Conservation of Energy", target="Simple Harmonic Motion", relationship="related", strength=0.6),
        Edge(source="Newton's Laws of Motion", target="Rotational Dynamics", relationship="prerequisite", strength=0.7),
    ],
    mastery_events=[
        MasteryEvent(concept="Projectile Motion", delta=0.12, reason="Mastering Physics HW 2: 19/20"),
        MasteryEvent(concept="Friction and Inclined Planes", delta=0.07, reason="Midterm incline problem full credit"),
        MasteryEvent(concept="Conservation of Energy", delta=-0.06, reason="Forgot friction work on a ramp problem"),
        MasteryEvent(concept="Momentum and Collisions", delta=0.08, reason="Tutor session on inelastic collisions"),
    ],
    categories=[
        Category(name="Mastering Physics", weight=0.2),
        Category(name="Labs", weight=0.2),
        Category(name="Exams", weight=0.6),
    ],
    assignments=[
        Assignment(title="Mastering Physics HW 2: Projectile Motion", category="Mastering Physics", type="homework",
                   due_offset_days=13, points_possible=20, points_earned=19),
        Assignment(title="Lab 2: Measuring g with a Picket Fence", category="Labs", type="project",
                   due_offset_days=20, points_possible=20, points_earned=18),
        Assignment(title="Mastering Physics HW 5: Newton's Laws and Friction", category="Mastering Physics", type="homework",
                   due_offset_days=36, points_possible=20, points_earned=17),
        Assignment(title="Midterm Exam 1", category="Exams", type="exam",
                   due_offset_days=46, points_possible=100, points_earned=86, is_midterm=True),
        Assignment(title="Lab 5: Ballistic Pendulum", category="Labs", type="project",
                   due_offset_days=70, points_possible=20),
        Assignment(title="Mastering Physics HW 8: Momentum and Collisions", category="Mastering Physics", type="homework",
                   due_offset_days=80, points_possible=20),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=111, points_possible=100),
    ],
    notes=[
        Note(
            title="Inclined planes — tilt your axes",
            tags=["newton", "friction", "midterm"],
            concepts=["Friction and Inclined Planes", "Newton's Laws of Motion"],
            body=(
                "**Always tilt the axes** so x is along the incline and y is perpendicular to it.\n\n"
                "Forces on a block on a ramp at angle θ:\n"
                "- Gravity components: **mg sin θ** down the slope, **mg cos θ** into the surface\n"
                "- Normal: N = mg cos θ (if nothing else pushes perpendicular)\n"
                "- Friction opposes motion (or *tendency* of motion)\n\n"
                "**Sliding down with kinetic friction:**\n"
                "ma = mg sin θ − μk mg cos θ -> **a = g(sin θ − μk cos θ)**\n\n"
                "**Example (HW 5 #3):** θ = 30°, μk = 0.20\n"
                "a = 9.8(0.500 − 0.20 × 0.866) = 9.8(0.327) = **3.2 m/s²**\n\n"
                "**Will it slide at all?** It starts sliding when tan θ > μs. "
                "So at θ = 30°, tan θ = 0.577; with μs = 0.6 it stays put.\n\n"
                "Mass cancels in all of these — a heavy and a light box with the same μ slide the same."
            ),
        ),
        Note(
            title="Energy vs momentum — which one when?",
            tags=["energy", "momentum", "review"],
            concepts=["Conservation of Energy", "Momentum and Collisions", "Work-Energy Theorem"],
            body=(
                "## Energy\n"
                "Ki + Ui + W_nc = Kf + Uf\n"
                "- U_grav = mgh, U_spring = ½kx²\n"
                "- W_nc is negative for friction: −μk N d\n"
                "- Use when you care about **speeds and heights/positions**, not time\n\n"
                "## Momentum\n"
                "Σp_before = Σp_after when no external impulse (collisions, explosions)\n"
                "- Elastic: KE also conserved\n"
                "- Perfectly inelastic: objects stick, KE is **lost** -> m₁v₁ = (m₁ + m₂)v_f\n\n"
                "## The ballistic pendulum (Lab 5) uses BOTH, in order\n"
                "1. Collision (bullet embeds): **momentum only** — energy is lost to deformation\n"
                "   v_f = m v / (m + M)\n"
                "2. Swing up: **energy only** — ½(m + M)v_f² = (m + M)g h\n"
                "   v_f = √(2gh)\n\n"
                "My mistake on the practice exam: I used energy conservation across the collision and "
                "got a bullet speed way too low."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="py211-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for CAS PY 211 General Physics 1: calculus-based mechanics from kinematics "
                    "through oscillations, with weekly Mastering Physics homework, labs and three exams.",
            concept_notes=[
                ConceptNote(name="One-Dimensional Kinematics", description="Chapters 2–3, weeks 1–2."),
                ConceptNote(name="Newton's Laws of Motion", description="Chapters 4–5, core of Midterm 1."),
                ConceptNote(name="Conservation of Energy", description="Chapters 7–8 after the midterm."),
                ConceptNote(name="Rotational Dynamics", description="Chapters 10–11, late semester."),
            ],
            extracted_text=(
                "CAS PY 211 General Physics 1\n"
                "Boston University Department of Physics\n\n"
                "Course Description: The first semester of a two-semester introductory physics sequence "
                "for science and engineering students. Topics: kinematics in one and two dimensions, "
                "Newton's laws, friction and circular motion, work and energy, conservation of energy, "
                "linear momentum and collisions, rotational motion and torque, static equilibrium, and "
                "simple harmonic motion. Calculus is used where appropriate.\n\n"
                "Corequisite: CAS MA 123 or equivalent.\n\n"
                "Course components\n"
                "  Lectures (3 per week) with clicker questions\n"
                "  Discussion section (1 per week)\n"
                "  Laboratory (biweekly, 2 hours) — lab reports due at the end of the session\n\n"
                "Grading\n"
                "  Mastering Physics homework  20%\n"
                "  Labs  20%\n"
                "  Midterm exam 1  25%\n"
                "  Final exam  35%\n"
                "A formula sheet is provided on exams. Bring a scientific calculator; no phones.\n\n"
                "Schedule\n"
                "  Wk 1-2  Units, vectors, 1D kinematics\n"
                "  Wk 3  Projectile motion\n"
                "  Wk 4-5  Newton's laws; friction; inclined planes\n"
                "  Wk 6  Circular motion; MIDTERM 1 end of week 6\n"
                "  Wk 7-8  Work, kinetic energy, potential energy, conservation of energy\n"
                "  Wk 9-10  Momentum, impulse, collisions\n"
                "  Wk 11-12  Rotation, torque, angular momentum\n"
                "  Wk 13-14  Oscillations; review"
            ),
        ),
        Document(
            file_name="py211-lecture-projectiles.pdf",
            category="lecture_notes",
            summary="Lecture notes on projectile motion: splitting launch velocity into components, solving "
                    "for time of flight, range and maximum height, with a worked cliff-launch example.",
            concept_notes=[
                ConceptNote(name="Projectile Motion", description="Horizontal and vertical motion are independent."),
                ConceptNote(name="One-Dimensional Kinematics", description="Each axis uses the constant-acceleration equations."),
                ConceptNote(name="Range equation", description="R = v₀² sin 2θ / g, valid only for level ground."),
            ],
            extracted_text=(
                "Lecture 6 — Projectile Motion\n\n"
                "Key idea: once launched, the only force is gravity (ignoring air resistance). The "
                "horizontal and vertical motions are INDEPENDENT and share only the time t.\n\n"
                "Launch at speed v₀ and angle θ above horizontal:\n"
                "  v₀x = v₀ cos θ (constant)\n"
                "  v₀y = v₀ sin θ, and ay = −g = −9.8 m/s²\n\n"
                "Equations\n"
                "  x = v₀x t\n"
                "  y = v₀y t − ½ g t²\n"
                "  vy = v₀y − g t\n\n"
                "Results for level ground (launch and landing at the same height)\n"
                "  Time of flight: T = 2 v₀ sin θ / g\n"
                "  Maximum height: H = v₀² sin²θ / (2g)\n"
                "  Range: R = v₀² sin 2θ / g, maximized at θ = 45°\n"
                "  Complementary angles (30° and 60°) give the same range\n\n"
                "Worked example: A ball is thrown horizontally at 12 m/s from a 20 m cliff.\n"
                "  Vertical: 20 = ½(9.8)t², so t = 2.02 s\n"
                "  Horizontal: x = 12 × 2.02 = 24.2 m from the base\n"
                "  Impact speed: vy = 9.8 × 2.02 = 19.8 m/s; v = √(12² + 19.8²) = 23.2 m/s\n\n"
                "Common mistake: using the range equation when the launch and landing heights differ. "
                "In that case, solve the y equation for t first, then use x = v₀x t.\n\n"
                "Clicker: at the top of the trajectory, vy = 0 but the acceleration is still g downward."
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Constant-acceleration equation without time", back="v² = v₀² + 2aΔx"),
        Flashcard(front="Range on level ground", back="R = v₀² sin 2θ / g; maximum at 45°."),
        Flashcard(front="Acceleration of a block sliding down an incline with friction", back="a = g(sin θ − μk cos θ)"),
        Flashcard(front="Centripetal acceleration", back="a_c = v²/r, directed toward the centre of the circle."),
        Flashcard(front="Work-energy theorem", back="W_net = ΔK = ½mv_f² − ½mv_i²"),
        Flashcard(front="Impulse", back="J = FΔt = Δp — the change in momentum."),
        Flashcard(front="Perfectly inelastic collision final velocity", back="v_f = (m₁v₁ + m₂v₂) / (m₁ + m₂); kinetic energy is not conserved."),
        Flashcard(front="Newton's third law pair for a book on a table", back="Earth pulls the book down; the book pulls Earth up. (The normal force is NOT the pair of gravity.)"),
    ],
    study_guide=StudyGuide(
        overview="Midterm 1 covers chapters 2–6: kinematics, projectiles, Newton's laws, friction and "
                 "circular motion. Expect four multi-part problems plus conceptual multiple choice; a "
                 "formula sheet is provided, so focus on setting up force diagrams and choosing axes.",
        topics=[
            StudyGuideTopic(name="Kinematics and projectiles", importance="Your strongest area; a quick refresher.",
                            concepts=["One-Dimensional Kinematics", "Projectile Motion"]),
            StudyGuideTopic(name="Newton's laws with friction", importance="At least two problems; draw the FBD first every time.",
                            concepts=["Newton's Laws of Motion", "Friction and Inclined Planes"]),
            StudyGuideTopic(name="Circular motion", importance="One problem; identify which force supplies the centripetal force.",
                            concepts=["Uniform Circular Motion"]),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Projectile Motion", difficulty="medium", days_ago=50, correct=[0, 1, 2, 3],
            questions=[
                QuizQuestion(question="At the top of a projectile's path, its acceleration is:",
                             options=["9.8 m/s² downward", "Zero", "9.8 m/s² upward", "Horizontal"],
                             correct_answer="9.8 m/s² downward",
                             explanation="Gravity acts throughout; only vy is zero at the peak."),
                QuizQuestion(question="Which launch angle gives the same range as 30° on level ground?",
                             options=["60°", "45°", "15°", "75°"],
                             correct_answer="60°",
                             explanation="sin 2θ is equal for complementary angles."),
                QuizQuestion(question="A ball rolls off a 1.25 m table at 3 m/s. How far from the table does it land?",
                             options=["1.5 m", "3.0 m", "0.75 m", "2.5 m"],
                             correct_answer="1.5 m",
                             explanation="t = √(2 × 1.25 / 9.8) ≈ 0.5 s; x = 3 × 0.5 = 1.5 m."),
                QuizQuestion(question="Ignoring air resistance, the horizontal velocity of a projectile:",
                             options=["Stays constant", "Increases", "Decreases", "Is zero at the top"],
                             correct_answer="Stays constant",
                             explanation="No horizontal force acts."),
            ],
        ),
        QuizAttempt(
            concept="Momentum and Collisions", difficulty="medium", days_ago=5, correct=[0, 2],
            questions=[
                QuizQuestion(question="A 2 kg cart at 3 m/s sticks to a stationary 1 kg cart. Their final speed is:",
                             options=["2 m/s", "3 m/s", "1 m/s", "1.5 m/s"],
                             correct_answer="2 m/s",
                             explanation="(2)(3) = (3)v_f, so v_f = 2 m/s."),
                QuizQuestion(question="In the collision above, the kinetic energy lost is:",
                             options=["3 J", "0 J", "9 J", "6 J"],
                             correct_answer="3 J",
                             explanation="Ki = 9 J, Kf = ½(3)(2²) = 6 J, so 3 J is lost."),
                QuizQuestion(question="Airbags reduce injury mainly by:",
                             options=["Increasing the stopping time so the force is smaller", "Reducing the change in momentum",
                                      "Increasing the passenger's mass", "Making the collision elastic"],
                             correct_answer="Increasing the stopping time so the force is smaller",
                             explanation="Δp is fixed; a longer Δt means a smaller F."),
                QuizQuestion(question="In a perfectly elastic collision, which quantities are conserved?",
                             options=["Both momentum and kinetic energy", "Only momentum", "Only kinetic energy", "Neither"],
                             correct_answer="Both momentum and kinetic energy",
                             explanation="Elastic means no kinetic energy is lost."),
            ],
        ),
    ],
    session=TutorSession(
        name="Ballistic pendulum prep",
        topic="Momentum and Collisions",
        mode="socratic",
        summary_bullets=[
            "Split the ballistic pendulum into a collision stage and a swing stage",
            "Used momentum conservation for the collision and energy for the swing",
            "Explained why energy is not conserved through the inelastic collision",
        ],
        messages=[
            ChatMessage(role="user", content="For Lab 5 we fire a ball into a pendulum and measure how high it swings. I tried ½mv² = (m+M)gh to get the launch speed but the TA said that's wrong. Why?"),
            ChatMessage(role="assistant", content="Let's break the event into two stages. Stage one is the ball hitting and sticking in the pendulum, stage two is the pendulum swinging up. During stage one, what kind of collision is it?"),
            ChatMessage(role="user", content="Perfectly inelastic, since they stick together."),
            ChatMessage(role="assistant", content="Right. And what happens to kinetic energy in a perfectly inelastic collision?"),
            ChatMessage(role="user", content="It isn't conserved — some goes into deformation and heat. So I can't use energy across the collision?"),
            ChatMessage(role="assistant", content="Exactly. Use momentum for stage one: m v = (m + M) V. Then use energy for stage two, where only gravity does work: ½(m + M)V² = (m + M)gh, so V = √(2gh). Combine them: v = ((m + M)/m)·√(2gh). Your energy-only version skipped the energy lost in the collision, which is why it gave a launch speed that was too low."),
        ],
    ),
)

PACK = MajorPack(
    key="mech_eng",
    label="Mechanical Engineering",
    year="Sophomore",
    courses=[EK125, EK301, MA225, PY211],
    total_xp=1140,
    streak_days=4,
)
