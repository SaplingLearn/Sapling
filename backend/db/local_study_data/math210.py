"""MATH210, Linear Algebra: the local study dataset's second class. Plain
content; ``spec.py`` says what each field is."""
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

SYSTEMS = "Vectors and Systems"
MATRICES = "Matrix Algebra"
SPACES = "Vector Spaces"
EIGEN = "Eigen Theory"

CONCEPTS = (
    Concept("vectors", "Vectors", SYSTEMS,
            "A vector is an ordered list of numbers that can be added to another and scaled by a number.",
            0.88, 8, 14),
    Concept("dot", "Dot Product and Orthogonality", SYSTEMS,
            "The dot product multiplies matching entries and adds them; it is zero exactly when two vectors are orthogonal.",
            0.76, 5, 9, ("vectors",)),
    Concept("systems", "Systems of Linear Equations", SYSTEMS,
            "A linear system is a set of linear equations that must all hold for the same unknowns.",
            0.82, 6, 20, ("vectors",)),
    Concept("elimination", "Gaussian Elimination", SYSTEMS,
            "Gaussian elimination uses row operations to turn a system into a triangular one that is solved from the bottom up.",
            0.58, 5, 4, ("systems",)),
    Concept("matrices", "Matrices", MATRICES,
            "A matrix is a rectangular array of numbers that stores a linear system or a linear map.",
            0.66, 6, 3, ("vectors",)),
    Concept("multiplication", "Matrix Multiplication", MATRICES,
            "The product AB takes dot products of the rows of A with the columns of B, and it composes two linear maps.",
            0.47, 4, 2, ("matrices",)),
    Concept("inverses", "Matrix Inverses", MATRICES,
            "The inverse of a square matrix A is the matrix that multiplies with A to give the identity.",
            0.36, 3, 1, ("multiplication", "elimination")),
    Concept("determinants", "Determinants", MATRICES,
            "The determinant is one number computed from a square matrix that is zero exactly when the matrix has no inverse.",
            0.22, 3, 0, ("multiplication",)),
    Concept("independence", "Linear Independence", SPACES,
            "Vectors are linearly independent when none of them is a combination of the others.",
            0.52, 4, 5, ("vectors", "elimination")),
    Concept("span", "Span and Basis", SPACES,
            "The span of some vectors is every combination of them, and a basis is an independent set that spans the space.",
            0.40, 3, 6, ("independence",)),
    Concept("subspaces", "Subspaces", SPACES,
            "A subspace is a set of vectors that contains zero and is closed under addition and scaling.",
            0.15, 2, 7, ("span",)),
    Concept("rank", "Rank and Nullity", SPACES,
            "The rank is the number of pivot columns and the nullity is the number of free variables; they add up to the number of columns.",
            0.0, needs=("subspaces", "elimination")),
    Concept("transformations", "Linear Transformations", SPACES,
            "A linear transformation is a map between vector spaces that respects addition and scaling.",
            0.50, 3, 8, ("multiplication",)),
    Concept("eigenvalues", "Eigenvalues", EIGEN,
            "An eigenvalue of A is a number that A scales some nonzero vector by.",
            0.20, 4, 2, ("matrices", "determinants")),
    Concept("eigenvectors", "Eigenvectors", EIGEN,
            "An eigenvector of A is a nonzero vector that A only stretches, without turning it.",
            0.0, needs=("eigenvalues",)),
    Concept("diagonalization", "Diagonalization", EIGEN,
            "Diagonalizing A writes it as a change of basis around a diagonal matrix of its eigenvalues.",
            0.0, needs=("eigenvectors",)),
    Concept("projections", "Orthogonal Projections", EIGEN,
            "The orthogonal projection of a vector onto a subspace is the closest point of the subspace to it.",
            0.0, needs=("dot", "span")),
)
_C = {c.key: c for c in CONCEPTS}

MATERIALS = (
    Material("syllabus", "MATH210 Syllabus.pdf", "syllabus", 74,
             "Course plan: weekly problem sets, three exams and a final.",
             ("vectors", "matrices"), (
                 "MATH210 covers vectors, linear systems, matrices, vector spaces and eigenvalues. "
                 "Problem sets are due every Thursday.",
                 "Grading: problem sets 20 percent, three exams 15 percent each, one project 10 percent, "
                 "final exam 25 percent.",
                 "Exam 2 covers systems and matrices. Exam 3 covers matrices and vector spaces. The "
                 "final exam covers the whole course, with extra weight on eigenvalues.",
             )),
    Material("lec02", "Lecture 02 - Vectors and Dot Products.pdf", "lecture_notes", 68,
             "Vector addition, scalar multiples, length and the dot product.",
             ("vectors", "dot"), (
                 "A vector in R^n is a list of n numbers. Vectors add entry by entry, and a scalar "
                 "multiple scales every entry.",
                 "The dot product of u and v multiplies matching entries and adds the results. The "
                 "length of v is the square root of v dot v.",
                 "Two vectors are orthogonal when their dot product is 0. For example (1, 2) and (2, -1) "
                 "are orthogonal because 1 times 2 plus 2 times -1 is 0.",
             )),
    Material("lec04", "Lecture 04 - Gaussian Elimination.pdf", "lecture_notes", 55,
             "Augmented matrices, the three row operations and back substitution.",
             ("systems", "elimination"), (
                 "A linear system can be written as an augmented matrix. Three row operations keep its "
                 "solutions: swap two rows, scale a row by a nonzero number, add a multiple of one row to another.",
                 "Elimination uses those operations to make zeros below each pivot. The result is an "
                 "upper triangular system that is solved from the last equation upward.",
                 "A row of zeros that ends in a nonzero number means there is no solution. A column "
                 "with no pivot gives a free variable and so infinitely many solutions.",
             )),
    Material("lec06", "Lecture 06 - Matrix Multiplication.pptx", "slides", 43,
             "The row-times-column rule, when products are defined, and why order matters.",
             ("matrices", "multiplication"), (
                 "The entry in row i and column j of AB is the dot product of row i of A with column j "
                 "of B. The product is defined only when A has as many columns as B has rows.",
                 "Matrix multiplication is associative but not commutative. In general AB and BA are "
                 "different, and one of them may not even be defined.",
                 "Multiplying by the identity matrix I changes nothing. A product AB applies B first "
                 "and then A, which is how matrices compose linear maps.",
             )),
    Material("lec08", "Lecture 08 - Inverses.pdf", "lecture_notes", 33,
             "What an inverse is, the 2 by 2 formula and finding inverses by row reduction.",
             ("inverses", "elimination"), (
                 "A square matrix A is invertible when some matrix B gives AB = BA = I. That B is "
                 "written A inverse, and it undoes what A does.",
                 "For a 2 by 2 matrix with rows (a, b) and (c, d), swap a and d, negate b and c, and "
                 "divide by ad - bc. If ad - bc is 0 there is no inverse.",
                 "For larger matrices, row reduce the block [A | I]. When the left side becomes I, the "
                 "right side is A inverse. The inverse of AB is B inverse times A inverse.",
             )),
    Material("lec10", "Lecture 10 - Determinants.pdf", "lecture_notes", 23,
             "The 2 by 2 and 3 by 3 determinant, cofactor expansion and what a zero determinant means.",
             ("determinants", "inverses"), (
                 "The determinant of the 2 by 2 matrix with rows (a, b) and (c, d) is ad - bc. It "
                 "measures how the matrix scales area.",
                 "A 3 by 3 determinant is found by cofactor expansion along a row: each entry times the "
                 "determinant of the 2 by 2 matrix left after deleting its row and column, with alternating signs.",
                 "A matrix is invertible exactly when its determinant is not 0. The determinant of a "
                 "product is the product of the determinants, and swapping two rows flips the sign.",
             )),
    Material("lec12", "Lecture 12 - Linear Independence and Span.pdf", "lecture_notes", 16,
             "Linear combinations, span, and how to test a set of vectors for independence.",
             ("independence", "span"), (
                 "A linear combination of vectors adds scalar multiples of them. The span of a set is "
                 "every linear combination of its vectors.",
                 "Vectors are linearly independent when the only combination that gives the zero vector "
                 "uses all zero coefficients. Otherwise one of them is a combination of the others.",
                 "To test independence, put the vectors in the columns of a matrix and row reduce. A "
                 "pivot in every column means independent. A free variable means dependent.",
             )),
    Material("reading", "Reading - Linear Transformations.pdf", "reading", 11,
             "Textbook chapter on linear maps, their matrices, and rotations, reflections and shears.",
             ("transformations", "multiplication"), (
                 "A transformation T is linear when T(u + v) = T(u) + T(v) and T(cv) = cT(v). Every "
                 "linear transformation sends the zero vector to the zero vector.",
                 "Every linear transformation from R^n to R^m is multiplication by a matrix. Its columns "
                 "are the images of the standard basis vectors.",
                 "In the plane, a rotation turns every vector by the same angle, a reflection flips "
                 "across a line, and a shear slides points parallel to an axis.",
             )),
    Material("lec14", "Lecture 14 - Subspaces and Basis.pptx", "slides", 9,
             "The three subspace tests, bases, dimension, and the column and null spaces of a matrix.",
             ("subspaces", "span", "rank"), (
                 "A subspace of R^n contains the zero vector, is closed under addition and is closed "
                 "under scalar multiplication. A line through the origin is a subspace; a line that misses it is not.",
                 "A basis of a subspace is a linearly independent set that spans it. Every basis of the "
                 "same subspace has the same number of vectors, called the dimension.",
                 "The column space of A is the span of its columns. The null space is every x with "
                 "Ax = 0. Rank plus nullity equals the number of columns.",
             )),
    Material("ps7", "Problem Set 7 - Subspaces.pdf", "assignment", 6,
             "Eight problems on subspace tests, bases and dimension.",
             ("subspaces", "independence"), (
                 "Problem 1: decide whether the set of vectors (x, y) with x + y = 1 is a subspace of "
                 "R^2. Name the test that fails.",
                 "Problem 4: find a basis for the null space of the matrix with rows (1, 2, 3) and "
                 "(2, 4, 6), and state its dimension.",
                 "Problem 7: three vectors in R^2 are given. Explain without computing why they cannot "
                 "be linearly independent.",
             )),
    Material("lec16", "Lecture 16 - Eigenvalues and Eigenvectors.pdf", "lecture_notes", 4,
             "The eigenvalue equation, the characteristic polynomial and a power iteration demo.",
             ("eigenvalues", "eigenvectors", "determinants"), (
                 "A nonzero vector v is an eigenvector of A when Av is a multiple of v. The multiple is "
                 "the eigenvalue. A only stretches an eigenvector; it does not turn it.",
                 "The eigenvalues are the solutions of det(A - tI) = 0. For the matrix with rows (2, 1) "
                 "and (1, 2) this is t^2 - 4t + 3 = 0, so the eigenvalues are 3 and 1.",
                 "Power iteration demo for that matrix, starting from (1, 0). The estimate of the "
                 "largest eigenvalue at step 0 was 2, at step 1 it was 2.8, at step 2 it was 2.98, at "
                 "step 3 it was 2.997 and at step 4 it was 3.0.",
             )),
    Material("lec17", "Lecture 17 - Diagonalization.pdf", "lecture_notes", 1,
             "Writing a matrix as P D P inverse and using it to compute powers.",
             ("diagonalization", "eigenvectors"), (
                 "A matrix is diagonalizable when it has enough independent eigenvectors to form a "
                 "basis. Put them in the columns of P and the eigenvalues on the diagonal of D.",
                 "Then A equals P times D times P inverse. Powers become easy: A to the k is P times D "
                 "to the k times P inverse, and D to the k just raises each diagonal entry to the k.",
                 "A matrix with n different eigenvalues is always diagonalizable. A repeated eigenvalue "
                 "may or may not supply enough eigenvectors.",
             )),
)

ASSESSMENTS = (
    Assessment("exam2", "Exam 2", "exam", -20, 100, 88, (SYSTEMS, MATRICES)),
    Assessment("exam3", "Exam 3", "exam", 5, covers=(MATRICES, SPACES)),
    Assessment("final", "Final Exam", "exam", 29, covers=(SYSTEMS, MATRICES, SPACES, EIGEN)),
    Assessment("quiz1", "Quiz 1: Dot Products", "quiz", -63, 10, 9),
    Assessment("quiz2", "Quiz 2: Eigenvalues", "quiz", 8, 10, covers=(EIGEN,)),
    Assessment("ps6", "Problem Set 6: Determinants", "homework", -8, 40, 31),
    Assessment("ps7", "Problem Set 7: Subspaces", "homework", 2, 40),
    Assessment("ps8", "Problem Set 8: Eigenvalues", "homework", 11, 40),
    Assessment("project", "Project: Image Compression", "project", 19, 100),
)

CARDS = {
    "vectors": (
        ("How do you add two vectors?", "Add their matching entries."),
        ("What does multiplying a vector by a scalar do?", "It multiplies every entry by that number."),
        ("What is the zero vector?", "The vector whose entries are all 0."),
        ("How do you find the length of a vector?", "Take the square root of the vector dotted with itself."),
        ("What is a unit vector?", "A vector of length 1."),
    ),
    "dot": (
        ("How is the dot product computed?", "Multiply matching entries and add the results."),
        ("When are two vectors orthogonal?", "When their dot product is 0."),
        ("What kind of object is a dot product?", "A single number, not a vector."),
        ("What is v dot v?", "The square of the length of v."),
    ),
    "systems": (
        ("How many solutions can a linear system have?", "None, exactly one, or infinitely many."),
        ("What is an augmented matrix?", "The coefficient matrix with the right-hand sides added as a last column."),
        ("What does an inconsistent system mean?", "It has no solution."),
        ("What is a free variable?", "A variable whose column has no pivot, so it can take any value."),
    ),
    "elimination": (
        ("What are the three row operations?", "Swap two rows, scale a row, add a multiple of one row to another."),
        ("What is a pivot?", "The first nonzero entry of a row after elimination."),
        ("What is back substitution?", "Solving a triangular system from the last equation upward."),
        ("What does the row 0 0 | 5 tell you?", "The system has no solution."),
        ("Do row operations change the solutions of a system?", "No, they keep the solution set the same."),
    ),
    "matrices": (
        ("What does a 2 by 3 matrix have?", "Two rows and three columns."),
        ("What is the identity matrix?", "A square matrix with 1 on the diagonal and 0 elsewhere."),
        ("What is the transpose of a matrix?", "The matrix with its rows and columns swapped."),
        ("When can two matrices be added?", "When they have the same number of rows and of columns."),
    ),
    "multiplication": (
        ("When is the product AB defined?", "When A has as many columns as B has rows."),
        ("How is the entry in row i, column j of AB found?", "Dot row i of A with column j of B."),
        ("Is matrix multiplication commutative?", "No, AB and BA are usually different."),
        ("What size is the product of a 2 by 3 and a 3 by 4 matrix?", "2 by 4."),
        ("Which map does AB apply first?", "B first, then A."),
        ("What does multiplying by the identity do?", "It leaves the matrix unchanged."),
    ),
    "inverses": (
        ("What does it mean for B to be the inverse of A?", "AB and BA both equal the identity."),
        ("When does a 2 by 2 matrix have no inverse?", "When ad - bc is 0."),
        ("What is the inverse of the product AB?", "B inverse times A inverse, in that order."),
        ("How do you find an inverse by row reduction?", "Reduce [A | I] until the left block is I; the right block is the inverse."),
        ("Can a 2 by 3 matrix have an inverse?", "No, only square matrices can."),
        ("How do you solve Ax = b with an inverse?", "Multiply both sides by A inverse to get x."),
    ),
    "determinants": (
        ("What is the determinant of the matrix with rows (a, b) and (c, d)?", "ad - bc."),
        ("What does a determinant of 0 tell you?", "The matrix has no inverse."),
        ("What does swapping two rows do to the determinant?", "It flips its sign."),
        ("What is the determinant of a product AB?", "The determinant of A times the determinant of B."),
        ("What does the size of a 2 by 2 determinant measure?", "How much the matrix scales area."),
        ("What is the determinant of the identity matrix?", "1."),
    ),
    "independence": (
        ("When are vectors linearly independent?", "When only the all-zero combination gives the zero vector."),
        ("How do you test independence by row reduction?", "Put the vectors in columns and look for a pivot in every column."),
        ("Can three vectors in the plane be independent?", "No, at most two can."),
        ("Is a set that contains the zero vector independent?", "No, it is always dependent."),
        ("What is a linear combination?", "A sum of scalar multiples of vectors."),
    ),
    "span": (
        ("What is the span of a set of vectors?", "Every linear combination of them."),
        ("What is a basis?", "A linearly independent set that spans the space."),
        ("What is the dimension of a space?", "The number of vectors in any basis of it."),
        ("What is the span of one nonzero vector?", "The line through the origin in its direction."),
        ("How many vectors does a basis of the plane have?", "Exactly two."),
    ),
    "subspaces": (
        ("What three things make a set a subspace?", "It contains zero and is closed under addition and scaling."),
        ("Is a line that misses the origin a subspace?", "No, it does not contain the zero vector."),
        ("What is the null space of A?", "Every vector x with Ax = 0."),
        ("What is the column space of A?", "The span of the columns of A."),
    ),
    "transformations": (
        ("What two rules make a transformation linear?", "It respects addition and it respects scaling."),
        ("Where does a linear transformation send the zero vector?", "To the zero vector."),
        ("How do you find the matrix of a linear transformation?", "Use the images of the standard basis vectors as its columns."),
        ("Is the map that adds (1, 1) to every vector linear?", "No, it moves the zero vector."),
        ("What does a shear do?", "It slides points parallel to an axis by an amount that depends on the other coordinate."),
    ),
    "eigenvalues": (
        ("What equation defines an eigenvalue t of A?", "Av = tv for some nonzero vector v."),
        ("How do you find the eigenvalues of A?", "Solve det(A - tI) = 0."),
        ("What are the eigenvalues of a triangular matrix?", "The entries on its diagonal."),
        ("What does an eigenvalue of 0 tell you?", "The matrix has no inverse."),
        ("What is the characteristic polynomial?", "The polynomial det(A - tI), whose roots are the eigenvalues."),
        ("What do the eigenvalues of a matrix add up to?", "Its trace, the sum of the diagonal entries."),
    ),
}

QUIZZES = (
    Quiz("vectors", 29, 18, 5, difficulty="easy"),
    Quiz("elimination", 25, 20, 4),
    Quiz("multiplication", 19, 17, 3),
    Quiz("multiplication", 7, 21, 4),
    Quiz("inverses", 15, 19, 2),
    Quiz("inverses", 4, 18, 3),
    Quiz("determinants", 10, 16, 1, difficulty="hard"),
    Quiz("determinants", 5, 20, 2),
    Quiz("determinants", 0, 0, 3, minutes_ago=150),
    Quiz("span", 6, 17, 2),
    Quiz("span", 1, 19, 2),
    Quiz("eigenvalues", 2, 21, 1),
    Quiz("independence", 9, 15, 0, state="abandoned"),
)

DIGESTS = (
    Digest("inverses",
           ("Divides by ad + bc instead of ad - bc in the 2 by 2 formula",
            "Inverts a product as A inverse times B inverse, in the wrong order"),
           ("Row reducing [A | I] without arithmetic slips",),
           "2 by 2 inverses, inverse of a product, solving with an inverse."),
    Digest("determinants",
           ("Forgets the alternating signs in a cofactor expansion",
            "Treats the determinant of a sum as the sum of the determinants"),
           ("3 by 3 determinants by hand",),
           "2 by 2 and 3 by 3 determinants, row swaps, zero determinants.", "easy"),
    Digest("span",
           ("Calls any spanning set a basis without checking independence",),
           ("Finding the dimension of a span",),
           "Span of one and two vectors, bases of the plane."),
    Digest("eigenvalues",
           ("Solves det(A) = 0 instead of det(A - tI) = 0",),
           (), "Characteristic polynomials of 2 by 2 matrices.", "easy"),
    Digest("multiplication",
           ("Multiplies matching entries instead of rows by columns",),
           (), "Sizes of products, order of multiplication.", "hard"),
)

TUTORING = (
    Tutoring("systems", "systems", "How Many Solutions", 30, 17, (0, 6, 14), ended=True),
    Tutoring("inverses", "inverses", "Inverses by Row Reduction", 14, 20, (0, 5, 11, 18, 26), ended=True),
    Tutoring("span", "span", "Span Versus Basis", 4, 19, (0, 4, 9, 16), "expository"),
    Tutoring("det", "determinants", "Determinants by Hand", 1, 21, (0, 5, 12, 20, 27)),
)

CARD_SETS = (
    CardSet("exam2", "Exam 2: systems and matrices", ("elimination", "matrices", "multiplication", "inverses"), 21,
            exam="exam2"),
    CardSet("exam3", "Exam 3 cram", ("determinants", "independence", "span", "subspaces"), 2, exam="exam3"),
    CardSet("eigen", "Eigenvalue basics", ("determinants", "eigenvalues"), 0, shuffle=False),
)

SECTIONS = {
    "vectors": SectionDraft(
        "Vectors",
        "Vectors add entry by entry, scale entry by entry, and are measured with the dot product.",
        (
            b.prose(
                ("A **vector** is a list of numbers. Two vectors of the same size add entry by entry, "
                 "and a **scalar** multiplies every entry.", "lec02"),
                ("The **dot product** turns two vectors into one number. It gives length, since the "
                 "length of v is the square root of v dot v, and it detects right angles.", "lec02"),
                summary="Add and scale entry by entry. The dot product gives lengths and detects right angles.",
            ),
            b.formula(
                "Dot product",
                r"\mathbf{u} \cdot \mathbf{v} = u_1 v_1 + u_2 v_2 + \dots + u_n v_n",
                "u dot v is the sum of the products of matching entries.",
                "lec02",
            ),
            b.terms(_C["vectors"], _C["dot"],
                    ("Orthogonal", "At a right angle: two vectors whose dot product is 0.")),
            b.check(
                "What is the dot product of (1, 2) and (2, -1)?",
                ("0", "4", "(2, -2)"), 0,
                "1 times 2 plus 2 times -1 is 0, so the two vectors are orthogonal.",
                "Multiply matching entries, then add. The answer is a number, not a vector.",
            ),
        ),
    ),
    "elimination": SectionDraft(
        "Gaussian elimination",
        "Row operations turn a system into a triangular one that you solve from the bottom up.",
        (
            b.prose(
                ("**Gaussian elimination** solves a linear system by clearing the entries below each "
                 "**pivot**. The three row operations it uses never change the solutions.", "lec04"),
                ("Once the system is triangular, **back substitution** solves the last equation first "
                 "and works upward. A row that reads 0 = 5 means there is no solution at all.", "lec04"),
                summary="Make zeros below each pivot, then solve from the last equation upward.",
            ),
            b.example(
                "Solve a 2 by 2 system",
                "Solve x + 2y = 5 and 3x + 4y = 11.",
                ("Clear below the pivot", "R2 - 3 R1: -2y = -4", "Subtracting 3 times row 1 removes x from row 2."),
                ("Solve the last equation", "y = 2", "Divide both sides by -2."),
                ("Substitute upward", "x + 2(2) = 5", "Put y into the first equation."),
                ("Answer", "x = 1, y = 2", "Check: 3(1) + 4(2) = 11."),
                source="lec04",
            ),
            b.compare(
                "Reading the reduced system", ("What you see", "What it means"),
                ("A pivot in every column", "No free variables", "Exactly one solution"),
                ("A column with no pivot", "A free variable", "Infinitely many solutions"),
                ("A row 0 0 | c with c not 0", "A false equation", "No solution"),
                emphasis=2,
            ),
            b.check(
                "After elimination a system has the row 0 0 0 | 4. How many solutions does it have?",
                ("None", "Exactly one", "Infinitely many"), 0,
                "The row says 0 = 4, which no values of the unknowns can satisfy.",
                "Write the row back out as an equation and read it.",
            ),
        ),
    ),
    "multiplication": SectionDraft(
        "Matrix multiplication",
        "Rows of A dot columns of B, defined only when the inner sizes match, and order matters.",
        (
            b.prose(
                ("Each entry of the product AB is the **dot product** of a row of A with a column of B. "
                 "So A must have as many columns as B has rows.", "lec06"),
                ("Multiplication is **not commutative**: AB and BA are usually different. The product "
                 "AB means apply B first, then A.", "lec06"),
                summary="Entry (i, j) of AB is row i of A dotted with column j of B. AB is usually not BA.",
            ),
            b.formula(
                "One entry of a product",
                r"(AB)_{ij} = \sum_{k} a_{ik}\, b_{kj}",
                "The i j entry of A B is the sum over k of a i k times b k j.",
                "lec06",
            ),
            b.example(
                "Multiply two 2 by 2 matrices",
                "A has rows (1, 2) and (3, 4). B has rows (0, 1) and (1, 0). Find AB.",
                ("Row 1 with column 1", "1(0) + 2(1) = 2", "Dot the first row of A with the first column of B."),
                ("Row 1 with column 2", "1(1) + 2(0) = 1", "Same row, second column."),
                ("Row 2 with both columns", "4 and 3", "3(0) + 4(1) = 4 and 3(1) + 4(0) = 3."),
                ("Answer", "rows (2, 1) and (4, 3)", "B swapped the columns of A."),
                source="lec06",
            ),
            b.check(
                "A is 2 by 3 and B is 3 by 4. What size is AB?",
                ("3 by 3", "2 by 4", "It is not defined"), 1,
                "The inner sizes match (3 and 3), and the product takes the outer sizes: 2 by 4.",
                "Write the sizes side by side and compare the two middle numbers first.",
            ),
        ),
    ),
    "inverses": SectionDraft(
        "Matrix inverses",
        "The inverse undoes a matrix, exists only when the determinant is not zero, and reverses the order of a product.",
        (
            b.prose(
                ("The **inverse** of a square matrix A is the matrix that gives the identity when "
                 "multiplied with A on either side. It undoes what A does.", "lec08"),
                ("For a 2 by 2 matrix there is a formula. For anything larger, row reduce the block "
                 "[A | I] until the left side is the identity.", "lec08"),
                "Not every square matrix has one. When ad - bc is 0 the formula divides by zero, and "
                "the matrix is called **singular**.",
                summary="A inverse undoes A. Use the 2 by 2 formula, or row reduce [A | I] for larger matrices.",
            ),
            b.formula(
                "Inverse of a 2 by 2 matrix",
                r"A^{-1} = \frac{1}{ad - bc}\begin{pmatrix} d & -b \\ -c & a \end{pmatrix}",
                "Swap a and d, negate b and c, and divide by a d minus b c.",
                "lec08",
            ),
            b.mistakes(
                (0, "Dividing by ad + bc",
                 "The divisor is the determinant, ad - bc. Compute it first and write it down on its own."),
                (1, "Inverting a product in the same order",
                 "Undo the last step first: the inverse of AB is B inverse times A inverse."),
            ),
            b.example(
                "Invert a 2 by 2 matrix",
                "Find the inverse of the matrix with rows (2, 1) and (5, 3).",
                ("Compute ad - bc", "2(3) - 1(5) = 1", "It is not 0, so the inverse exists."),
                ("Swap and negate", "rows (3, -1) and (-5, 2)", "Swap the diagonal, negate the other two."),
                ("Divide", "rows (3, -1) and (-5, 2)", "Dividing by 1 changes nothing."),
                source="lec08",
            ),
            b.check(
                "What is the inverse of the product AB, when both inverses exist?",
                ("A inverse times B inverse", "B inverse times A inverse", "The inverse of BA"), 1,
                "Undoing AB means undoing A last, so B inverse comes first in the product.",
                "Think of putting on socks and then shoes, and of the order you take them off.",
            ),
        ),
    ),
    "determinants": SectionDraft(
        "Determinants",
        "One number per square matrix: zero means no inverse, and its size is how much area is scaled.",
        (
            b.prose(
                ("The **determinant** of a 2 by 2 matrix is ad - bc. Its absolute value is the factor "
                 "by which the matrix scales area.", "lec10"),
                ("A 3 by 3 determinant is built from 2 by 2 ones by **cofactor expansion**, with signs "
                 "that alternate plus, minus, plus along the row.", "lec10"),
                ("The determinant is 0 exactly when the matrix has no inverse. That single test is why "
                 "it shows up again in eigenvalues.", "lec10"),
                summary="ad - bc for a 2 by 2. Zero means singular. Expand larger ones along a row with alternating signs.",
            ),
            b.formula(
                "Determinant of a 2 by 2 matrix",
                r"\det\begin{pmatrix} a & b \\ c & d \end{pmatrix} = ad - bc",
                "The determinant of the matrix a b c d is a d minus b c.",
                "lec10",
            ),
            b.mistakes(
                (0, "Dropping the minus sign on the middle cofactor",
                 "Write the signs + - + above the row before you expand, then copy them down."),
                (1, "Splitting a determinant over a sum",
                 "det(A + B) is not det A + det B. Only products split: det(AB) = det A det B."),
            ),
            b.compare(
                "What the determinant tells you", ("det A is not 0", "det A is 0"),
                ("Inverse", "Exists", "Does not exist"),
                ("Solutions of Ax = b", "Exactly one", "None or infinitely many"),
                ("Columns of A", "Linearly independent", "Linearly dependent"),
                emphasis=0,
            ),
            b.concept_map(
                "Where determinants sit",
                (_C["matrices"], "Foundations"), (_C["multiplication"], "Before this"),
                (_C["determinants"], "This section"), (_C["inverses"], "Alongside"),
                (_C["eigenvalues"], "Up next"),
            ),
            b.check(
                "What is the determinant of the matrix with rows (3, 2) and (6, 4)?",
                ("0", "24", "-24"), 0,
                "3 times 4 minus 2 times 6 is 0, so this matrix has no inverse.",
                "Multiply down the main diagonal, then subtract the product of the other diagonal.",
            ),
        ),
    ),
    "independence": SectionDraft(
        "Linear independence",
        "A set is independent when no vector in it can be built from the others.",
        (
            b.prose(
                ("Vectors are **linearly independent** when the only way to combine them into the zero "
                 "vector is to use all zero coefficients.", "lec12"),
                ("The test is mechanical: put the vectors in the columns of a matrix and row reduce. A "
                 "pivot in every column means independent.", "lec12"),
                summary="Independent means no vector is a combination of the others. Row reduce and look for a pivot in every column.",
            ),
            b.terms(_C["independence"],
                    ("Linear combination", "A sum of scalar multiples of vectors."),
                    ("Dependent", "Not independent: some vector in the set is a combination of the others.")),
            b.example(
                "Are these independent?",
                "Are (1, 2) and (2, 4) linearly independent?",
                ("Look for a multiple", "(2, 4) = 2 (1, 2)", "The second vector is twice the first."),
                ("Write the combination", "2 (1, 2) - (2, 4) = (0, 0)", "A combination with nonzero coefficients gives zero."),
                ("Answer", "Dependent", "Both vectors lie on the same line through the origin."),
                source="lec12",
            ),
            b.check(
                "Three vectors in the plane are given. Can they be linearly independent?",
                ("Yes, if none is a multiple of another", "No, never", "Only if one of them is zero"), 1,
                "A matrix with 2 rows has at most 2 pivots, so 3 columns always leave a free variable.",
                "Count how many pivots a matrix with two rows can have.",
            ),
        ),
    ),
    "span": SectionDraft(
        "Span and basis",
        "The span is everything you can build; a basis builds it with no vector to spare.",
        (
            b.prose(
                ("The **span** of a set of vectors is every linear combination of them. One nonzero "
                 "vector spans a line, and two independent ones span a plane.", "lec12"),
                ("A **basis** is a set that spans the space and is also independent. Every basis of a "
                 "space has the same size, and that number is the **dimension**.", "lec14"),
                summary="Span is all combinations. A basis spans with nothing redundant, and its size is the dimension.",
            ),
            b.mistakes(
                (0, "Calling a spanning set a basis",
                 "A basis has two jobs. After checking that the set spans, also check that it is independent."),
            ),
            b.compare(
                "Three words that get mixed up", ("Means", "In the plane"),
                ("Span", "Every combination of the set", "(1, 0) and (0, 1) span all of it"),
                ("Basis", "Spans and is independent", "Any two independent vectors"),
                ("Dimension", "The size of any basis", "2"),
                emphasis=1,
            ),
            b.concept_map(
                "How span fits in",
                (_C["vectors"], "Foundations"), (_C["independence"], "Before this"),
                (_C["span"], "This section"), (_C["subspaces"], "Up next"),
            ),
            b.check(
                "Do (1, 0), (0, 1) and (1, 1) form a basis of the plane?",
                ("Yes, because they span it", "No, because they are not independent",
                 "No, because they do not span it"), 1,
                "They span the plane, but (1, 1) is the sum of the other two, so the set is dependent.",
                "A basis has two requirements. Check both.",
            ),
        ),
    ),
    "subspaces": SectionDraft(
        "Subspaces",
        "A subspace passes three tests: it holds zero, sums stay inside, and multiples stay inside.",
        (
            b.prose(
                ("A **subspace** is a set of vectors that contains the zero vector and is closed under "
                 "addition and under scalar multiplication.", "lec14"),
                ("The quickest way to rule a set out is the zero test. A line that misses the origin "
                 "fails it at once, however straight it is.", "lec14"),
                summary="Check zero first, then sums, then multiples. Fail any one and it is not a subspace.",
            ),
            b.terms(_C["subspaces"],
                    ("Null space", "Every vector x with Ax = 0. It is always a subspace."),
                    ("Column space", "The span of the columns of A. It is always a subspace.")),
            b.example(
                "Run the three tests",
                "Is the set of vectors (x, y) with x + y = 1 a subspace of the plane?",
                ("Zero test", "0 + 0 = 0, not 1", "The zero vector is not in the set."),
                ("Stop here", "Not a subspace", "One failed test is enough."),
                ("Compare", "x + y = 0 passes all three", "Moving the line through the origin fixes it."),
            ),
            b.check(
                "Which of these is a subspace of the plane?",
                ("The line y = 2x", "The line y = 2x + 1", "The points with x at least 0"), 0,
                "The line y = 2x passes through the origin and stays closed under sums and multiples.",
                "Start with the zero vector, then try multiplying a point of the set by -1.",
            ),
        ),
    ),
    "transformations": SectionDraft(
        "Linear transformations",
        "A linear map respects sums and multiples, and every one of them is a matrix.",
        (
            b.prose(
                ("A **linear transformation** respects addition and scaling. As a result it always "
                 "sends the zero vector to the zero vector.", "reading"),
                ("Every linear transformation between finite spaces is multiplication by a matrix. Its "
                 "columns are where the **standard basis vectors** land.", "reading"),
                summary="Linear means it respects sums and multiples. Its matrix columns are the images of the basis vectors.",
            ),
            b.formula(
                "Linearity in one line",
                r"T(a\mathbf{u} + b\mathbf{v}) = a\,T(\mathbf{u}) + b\,T(\mathbf{v})",
                "T of a u plus b v equals a times T of u plus b times T of v.",
                "reading",
            ),
            b.compare(
                "Three maps of the plane", ("Matrix rows", "What it does"),
                ("Rotation by 90 degrees", "(0, -1) and (1, 0)", "Turns every vector a quarter turn"),
                ("Reflection in the x axis", "(1, 0) and (0, -1)", "Flips the sign of y"),
                ("Shear", "(1, 1) and (0, 1)", "Slides points sideways by their height"),
                emphasis=0,
            ),
            b.check(
                "T adds (1, 1) to every vector of the plane. Is T linear?",
                ("Yes, it is a shift", "No, it moves the zero vector", "Only for vectors on the line y = x"), 1,
                "A linear map must send zero to zero, and this one sends it to (1, 1).",
                "Check where the zero vector goes first.",
            ),
        ),
    ),
    "eigenvalues": SectionDraft(
        "Eigenvalues",
        "An eigenvalue is a stretch factor: A scales its eigenvector by it without turning it.",
        (
            b.prose(
                ("An **eigenvector** of A is a nonzero vector that A only stretches. The stretch factor "
                 "is its **eigenvalue**. Most vectors get turned as well, which is what makes these special.",
                 "lec16"),
                ("To find the eigenvalues, solve det(A - tI) = 0. The left side is a polynomial in t "
                 "called the **characteristic polynomial**.", "lec16"),
                summary="Av = tv for a nonzero v. Solve det(A - tI) = 0 to find the eigenvalues t.",
            ),
            b.chart(
                "What A does to two vectors", "x", "y",
                b.line("An eigenvector, (1, 1)", (0, 0), (1, 1)),
                b.line("Its image, (3, 3)", (0, 0), (3, 3), after=True),
                b.line("Another vector, (1, 0)", (0, 0), (1, 0)),
                b.line("Its image, (2, 1)", (0, 0), (2, 1), after=True),
                alt="The eigenvector is stretched along its own line. The other vector is turned off its line.",
                markers=(b.marker(1, 1, "1", "1"), b.marker(3, 3, "3", "3", after=True)),
                readouts=(b.readout("Eigenvector", "(1, 1)", "(3, 3)", "Same direction"),
                          b.readout("Other vector", "(1, 0)", "(2, 1)", "Turns")),
                after_label="After A",
            ),
            b.formula(
                "The characteristic equation",
                r"\det(A - tI) = 0",
                "The determinant of A minus t times the identity equals zero.",
                "lec16",
            ),
            b.mistakes(
                (0, "Setting det(A) to zero",
                 "Subtract t from each diagonal entry first. The equation is det(A - tI) = 0."),
            ),
            b.example(
                "Find the eigenvalues",
                "Find the eigenvalues of the matrix with rows (2, 1) and (1, 2).",
                ("Subtract t on the diagonal", "rows (2 - t, 1) and (1, 2 - t)", "This is A - tI."),
                ("Take the determinant", "(2 - t)(2 - t) - 1", "ad - bc for the new matrix."),
                ("Expand", "t^2 - 4t + 3 = 0", "Multiply out and collect terms."),
                ("Factor", "(t - 3)(t - 1) = 0", "The eigenvalues are 3 and 1."),
                source="lec16",
            ),
            b.chart(
                "Power iteration closing in", "Step", "Largest eigenvalue estimate",
                b.line("Estimate", (0, 2), (1, 2.8), (2, 2.98), (3, 2.997), (4, 3.0)),
                alt="The estimate rises quickly at first and then levels off at the largest eigenvalue.",
                source="lec16",
            ),
            b.check(
                "What are the eigenvalues of the matrix with rows (4, 0) and (0, 7)?",
                ("4 and 7", "0 and 28", "11 only"), 0,
                "For a diagonal matrix, det(A - tI) is (4 - t)(7 - t), which is zero at 4 and 7.",
                "Write out A - tI and take its determinant. A diagonal matrix makes this short.",
            ),
        ),
    ),
}

GUIDES = (
    GuideSpec(
        "exam2", "Exam 2: systems and matrices",
        "A cram sheet for Exam 2: elimination, the product rule and inverses.",
        ("Row operations never change the solutions.",
         "AB is defined when the inner sizes match.",
         "The inverse of AB is B inverse times A inverse."),
        "exam2", "exam_prep", "cram", ("elimination", "multiplication", "inverses"),
        made_hours_ago=22 * 24, saved_hours_ago=21 * 24,
        read=("elimination", "multiplication", "inverses"), answers={"elimination": "a"}, feedback="no",
    ),
    GuideSpec(
        "exam3", "Determinants, independence and subspaces",
        "Exam 3 in six sections, with the most room for inverses, determinants, span and subspaces.",
        ("A zero determinant means no inverse and dependent columns.",
         "A basis spans the space and is independent.",
         "Test a subspace with zero first."),
        "exam3", "exam_prep", "deep",
        ("inverses", "determinants", "independence", "span", "subspaces", "transformations"),
        made_hours_ago=7 * 24,
        read=("inverses", "determinants"), answers={"determinants": "b", "independence": "b"},
    ),
    GuideSpec(
        "course", "Linear algebra, the whole course",
        "Seven sections from vectors to eigenvalues, for a steady review before the final.",
        ("Almost every question reduces to row reduction.",
         "Invertible, nonzero determinant and independent columns all mean the same thing.",
         "Eigenvalues come from det(A - tI) = 0."),
        None, "review", "deep",
        ("vectors", "elimination", "multiplication", "inverses", "determinants", "independence", "eigenvalues"),
        made_hours_ago=2 * 24, saved_hours_ago=2 * 24 - 2, failed=("eigenvalues",),
        read=("vectors",),
    ),
    GuideSpec(
        "ps8", "Eigenvalues before Problem Set 8",
        "Practice for Problem Set 8: the matrix skills eigenvalues lean on, then eigenvalues themselves.",
        ("An eigenvector is only stretched, never turned.",
         "Subtract t on the diagonal before taking the determinant.",
         "A diagonal matrix shows its eigenvalues on the diagonal."),
        "ps8", "practice", "standard", ("multiplication", "determinants", "transformations", "eigenvalues"),
        made_hours_ago=1,
    ),
)

CLASS = ClassData(
    key="math210",
    course_id="rich-course-math210",
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
)
