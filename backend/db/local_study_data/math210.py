"""MATH210, Linear Algebra: the local study dataset's second class. Plain
content; ``spec.py`` says what each field is."""
from __future__ import annotations

from db.local_study_data.math210_concepts import (
    CONCEPTS,
    EIGEN,
    MATRICES,
    SPACES,
    SYSTEMS,
)
from db.local_study_data.math210_guides import GUIDES, SECTIONS
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
    Assessment("quiz1", "Quiz 1: Dot Products", "quiz", -63, 10, 9, concepts=("vectors", "dot")),
    Assessment("quiz2", "Quiz 2: Eigenvalues", "quiz", 8, 10,
               concepts=("determinants", "eigenvalues", "eigenvectors")),
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
    # The rich seed's midterm stands where an Exam 1 would.
    earlier_exams={"Midterm Exam": ("vectors", "dot", "systems", "elimination")},
)
