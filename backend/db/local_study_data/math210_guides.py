"""MATH210's study guides: one section draft per concept, and the guides that
pick from them. A draft is written once at every length it is read at
(``spec.LENGTHS``): its opening passage is the cram version, and the
``standard`` and ``deep`` passages are what the longer versions add."""
from __future__ import annotations

from db.local_study_data import blocks as b
from db.local_study_data.math210_concepts import CONCEPTS
from db.local_study_data.spec import GuideSpec, SectionDraft

_C = {c.key: c for c in CONCEPTS}

SECTIONS = {
    "vectors": SectionDraft(
        "Vectors",
        "Vectors add entry by entry, scale entry by entry, and are measured with the dot product.",
        (
            b.prose(
                ("A **vector** in R^n is a list of n numbers, and the order of the list matters. Two "
                 "operations are defined on vectors, and everything else in the course is built from "
                 "them. Vectors of the same size add entry by entry, and a **scalar**, an ordinary "
                 "number, multiplies every entry. So (1, 2) + (3, 5) is (4, 7), and 2 times (1, 2) "
                 "is (2, 4).", "lec02"),
                ("The **dot product** is the third tool, and it is different in kind: it takes two "
                 "vectors and gives back a single number. Multiply the matching entries and add the "
                 "results. That number measures things. The length of v is the square root of v dot "
                 "v, and two vectors are **orthogonal**, at right angles, exactly when their dot "
                 "product is 0.", "lec02"),
                summary="Vectors add and scale entry by entry. The dot product turns two vectors into "
                        "one number that gives lengths and detects right angles.",
            ),
            b.formula(
                "Dot product",
                r"\mathbf{u} \cdot \mathbf{v} = u_1 v_1 + u_2 v_2 + \dots + u_n v_n",
                "u dot v is the sum of the products of matching entries.",
                "lec02",
            ),
            b.prose(
                "Work the formula once by hand and it stops being abstract. Take v = (3, 4). Then v "
                "dot v is 3 times 3 plus 4 times 4, which is 25, and the length of v is the square "
                "root of 25, so 5. The same arithmetic tests for a right angle: line up the two "
                "vectors, multiply down the columns, add, and see whether the total is 0. Keep track "
                "of what kind of thing each answer is. A sum of vectors is a vector. A scalar "
                "multiple is a vector. A dot product is always a single number, and writing a vector "
                "there is the most common slip.",
                summary="For v = (3, 4), v dot v is 25 and the length is 5. A dot product is always a "
                        "number, never a vector.",
                at="standard",
            ),
            b.terms(_C["vectors"], _C["dot"],
                    ("Orthogonal", "At a right angle: two vectors whose dot product is 0.")),
            b.prose(
                "These three ideas keep returning under other names, which is the reason to have "
                "them solid now. A linear combination is nothing more than scaling some vectors and "
                "adding the results. Each entry of a matrix product is a dot product of a row with a "
                "column. A system of linear equations asks which combination of the columns gives "
                "the right-hand side. When a later topic looks new, look for the addition, the "
                "scaling and the dot product inside it, because they are nearly always there.",
                summary="Linear combinations, matrix products and linear systems are all built from "
                        "adding, scaling and dot products.",
                at="standard",
            ),
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
                ("**Gaussian elimination** solves a linear system by rewriting it until the answer "
                 "can be read off. Write the system as an augmented matrix, then use three row "
                 "operations: swap two rows, scale a row by a nonzero number, or add a multiple of "
                 "one row to another. None of them changes the solutions, so every matrix along the "
                 "way describes the same system.", "lec04"),
                ("The aim is a zero below every **pivot**, the first nonzero entry of each row. That "
                 "leaves an upper triangular system, and **back substitution** finishes it: solve "
                 "the last equation, which has one unknown, then put that value into the equation "
                 "above and work upward. Each step up has only one unknown left to find.", "lec04"),
                summary="Use row operations to make zeros below each pivot, then solve the triangular "
                        "system from the last equation upward.",
            ),
            b.prose(
                "Almost every step you take is the third operation, and it helps to see it as a "
                "recipe. Pick the pivot. For each row below it, ask what multiple of the pivot row "
                "would cancel the entry under the pivot, and subtract that multiple. In the example "
                "the pivot is 1 and the entry below it is 3, so you subtract 3 times row 1 from row "
                "2. Apply the operation to the whole row, right-hand side included. Forgetting the "
                "last column is the usual arithmetic slip, and it gives a tidy answer that fails "
                "when you check it.",
                summary="To clear an entry, subtract the right multiple of the pivot row from the "
                        "whole row, right-hand side included.",
                at="standard",
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
            b.prose(
                "Why is it safe to change the equations at all? Because each row operation can be "
                "undone by another one. A swap is undone by the same swap, scaling by a nonzero "
                "number is undone by scaling by its reciprocal, and adding a multiple of a row is "
                "undone by subtracting it. So any values that satisfy the old rows satisfy the new "
                "ones, and the reverse. This is also why scaling by 0 is not allowed: it wipes out "
                "an equation, nothing can bring it back, and the new system may accept values the "
                "old one refused. Check your final answer in the original equations, as the example "
                "does in its last step.",
                summary="Every row operation can be reversed, so the solutions never change. Scaling "
                        "a row by 0 is not allowed because it cannot be undone.",
                at="deep",
            ),
            b.prose(
                ("Elimination also tells you how many solutions there are, before you solve "
                 "anything. A row of zeros that ends in a nonzero number is a false equation, so "
                 "there is no solution. A column with no pivot gives a **free variable**, one you "
                 "may choose freely, and so infinitely many solutions. A pivot in every column "
                 "leaves nothing free and exactly one solution. Look for the false row first, "
                 "because it settles the question at once whatever the other rows say. The table "
                 "sets the three cases side by side.", "lec04"),
                summary="A false row means no solution, a column with no pivot means infinitely "
                        "many, and a pivot in every column means exactly one.",
                at="standard",
            ),
            b.compare(
                "Reading the reduced system", ("What you see", "What it means"),
                ("A pivot in every column", "No free variables", "Exactly one solution"),
                ("A column with no pivot", "A free variable", "Infinitely many solutions"),
                ("A row 0 0 | c with c not 0", "A false equation", "No solution"),
                emphasis=2,
            ),
            b.prose(
                ("The same reduction answers questions that do not look like systems. To find an "
                 "inverse you row reduce the block [A | I]. To test whether vectors are independent "
                 "you put them in columns, reduce, and look for a pivot in every column. In both "
                 "cases the work is the elimination you already know, and only the reading at the "
                 "end changes. So practise until the mechanics cost you no thought: choose the "
                 "pivot, clear below it, move one row down and one column right, and repeat. Speed "
                 "here is worth more than any single formula in the course, because nearly every "
                 "later method starts with this one.", "lec08"),
                summary="Finding an inverse and testing independence are the same row reduction read "
                        "differently, so fluent elimination pays off everywhere.",
                at="deep",
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
                ("Matrices do not multiply entry by entry. The entry in row i and column j of the "
                 "product AB is the **dot product** of row i of A with column j of B. That only "
                 "makes sense when the row and the column have the same number of entries, so AB is "
                 "defined only when A has as many columns as B has rows.", "lec06"),
                ("Order matters. Matrix multiplication is **not commutative**: AB and BA are usually "
                 "different, and one of them may not even be defined. The product AB means apply B "
                 "first and then A, so the matrix written on the right acts first. Multiplying by "
                 "the identity matrix I changes nothing.", "lec06"),
                summary="Entry (i, j) of AB is row i of A dotted with column j of B. The inner sizes "
                        "must match, and AB is usually not BA.",
            ),
            b.prose(
                "Check the sizes before you compute anything. Write the two sizes next to each "
                "other, such as 2 by 3 and 3 by 2, and look at the inner pair of numbers. If they "
                "match, the product exists, and the outer pair gives its size, here 2 by 2. If they "
                "do not match there is nothing to compute, and saying so is the full answer. The "
                "inner numbers have to agree because each entry of the product pairs one row of A "
                "with one column of B, entry for entry. The formula below says the same thing with "
                "indexes.",
                summary="Write the sizes side by side: the inner numbers must match, and the outer "
                        "numbers give the size of the product.",
                at="standard",
            ),
            b.formula(
                "One entry of a product",
                r"(AB)_{ij} = \sum_{k} a_{ik}\, b_{kj}",
                "The i j entry of A B is the sum over k of a i k times b k j.",
                "lec06",
            ),
            b.prose(
                "The mistake to guard against is multiplying matching entries, the way addition "
                "works. A product is built one entry at a time, and each entry needs a whole row and "
                "a whole column. A steady routine helps. Put a finger on row i of A and another on "
                "column j of B, multiply the pairs as you move along both, add them up, and write "
                "the total in position (i, j). Then move to the next column. The example does all "
                "four entries of a 2 by 2 product in that order, and its answer shows what "
                "multiplying by this particular B does to A.",
                summary="Each entry of AB needs a whole row of A and a whole column of B. Never "
                        "multiply matching entries.",
                at="standard",
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
            b.prose(
                ("Order matters because a matrix stands for an action, and actions done in a "
                 "different order give different results. AB applies B first and then A. Turning a "
                 "shape and then flipping it does not in general leave it where flipping and then "
                 "turning would, and the two products record that difference. The example shows it "
                 "in numbers: multiplying A by that B on the right swapped the columns of A, and "
                 "multiplying by it on the left would swap the rows of A. So never reorder a product "
                 "to make it easier. You may regroup, since multiplication is associative and (AB)C "
                 "equals A(BC), but the letters stay in the order they were written.", "lec06"),
                summary="AB applies B first, and a different order is a different action. You may "
                        "regroup a product but never reorder it.",
                at="deep",
            ),
            b.prose(
                "Two habits from ordinary arithmetic survive, and the rest do not. The identity "
                "matrix I plays the part of the number 1: multiplying by it on either side changes "
                "nothing. Grouping is free as well. What fails is treating a matrix product like a "
                "product of numbers in every other way. AB and BA are different matrices, a product "
                "can be defined in one order and not in the other, and squaring a matrix means "
                "multiplying it by itself with the full row by column rule, not squaring its "
                "entries. When an answer came too easily, check whether you slipped back into entry "
                "by entry thinking.",
                summary="The identity acts like 1 and grouping is free, but order is not: never swap "
                        "factors or work entry by entry.",
                at="deep",
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
                ("The **inverse** of a square matrix A is the matrix that undoes it. It is written A "
                 "inverse, and multiplying it with A on either side gives the identity I. Not every "
                 "square matrix has one. A matrix with an inverse is called invertible and one "
                 "without is called **singular**, and telling the two apart is the first thing any "
                 "question about inverses asks of you.", "lec08"),
                ("For a 2 by 2 matrix with rows (a, b) and (c, d) there is a formula: swap a and d, "
                 "negate b and c, and divide every entry by ad - bc. If ad - bc is 0 there is "
                 "nothing to divide by and no inverse exists. For larger matrices, row reduce the "
                 "block [A | I] until the left side becomes I, and the right side is then A "
                 "inverse.", "lec08"),
                summary="A inverse undoes A and exists only when ad - bc is not 0. Use the 2 by 2 "
                        "formula, or row reduce [A | I] for larger matrices.",
            ),
            b.formula(
                "Inverse of a 2 by 2 matrix",
                r"A^{-1} = \frac{1}{ad - bc}\begin{pmatrix} d & -b \\ -c & a \end{pmatrix}",
                "Swap a and d, negate b and c, and divide by a d minus b c.",
                "lec08",
            ),
            b.prose(
                ("Compute ad - bc before anything else and write it on a line of its own. It is the "
                 "determinant of the matrix, and it answers the first question, whether an inverse "
                 "exists at all, before you have done any other work. It is also where the "
                 "arithmetic goes wrong: the sign in the middle is a minus, and with negative "
                 "entries it is easy to lose. The second slip is about products. To undo AB you "
                 "must undo A last, so the inverse of AB is B inverse times A inverse, in the "
                 "reverse order. Both slips have turned up in your quizzes.", "lec08", "lec10"),
                summary="Work out ad - bc first: it decides whether the inverse exists. The inverse "
                        "of AB is B inverse times A inverse.",
                at="standard",
            ),
            b.mistakes(
                (0, "Dividing by ad + bc",
                 "The divisor is the determinant, ad - bc. Compute it first and write it down on its own."),
                (1, "Inverting a product in the same order",
                 "Undo the last step first: the inverse of AB is B inverse times A inverse."),
            ),
            b.prose(
                "The reversed order is not a rule to memorise, because you can check it in one line. "
                "Multiply AB by B inverse times A inverse. The B and the B inverse in the middle "
                "meet first and become I, which drops out, and then A meets A inverse and becomes I "
                "as well. Try the other order, A inverse times B inverse, and nothing cancels, "
                "because B is now sitting next to A inverse and those two have nothing to do with "
                "each other. The same reasoning undoes three steps: the inverse of ABC is C inverse "
                "times B inverse times A inverse, the last step undone first.",
                summary="In AB times B inverse times A inverse the middle pair cancels, then the "
                        "outer pair. In the other order nothing cancels.",
                at="deep",
            ),
            b.prose(
                "An inverse is easy to check, and you should always check it. Multiply your answer "
                "by the original matrix. If you get the identity you are right, and if a single "
                "entry is off you know to look again at the swap, the two sign changes or the "
                "division. The same idea shows what an inverse is for. If Ax = b and A is "
                "invertible, multiplying both sides by A inverse leaves x on its own, so the system "
                "has exactly one solution. The example runs the formula on a matrix whose ad - bc "
                "is 1, which keeps the division out of the way.",
                summary="Check an inverse by multiplying it with the original: the result must be "
                        "the identity.",
                at="standard",
            ),
            b.example(
                "Invert a 2 by 2 matrix",
                "Find the inverse of the matrix with rows (2, 1) and (5, 3).",
                ("Compute ad - bc", "2(3) - 1(5) = 1", "It is not 0, so the inverse exists."),
                ("Swap and negate", "rows (3, -1) and (-5, 2)", "Swap the diagonal, negate the other two."),
                ("Divide", "rows (3, -1) and (-5, 2)", "Dividing by 1 changes nothing."),
                source="lec08",
            ),
            b.prose(
                ("The formula stops at 2 by 2. For anything larger, set the identity beside A to "
                 "make the block [A | I] and row reduce the whole block until the left half is the "
                 "identity. The right half is then the inverse. It works because every row "
                 "operation you apply to A is applied to I at the same moment, so the right half "
                 "keeps a running record of everything it took to turn A into I, and that record is "
                 "exactly what undoes A. If the left half produces a row of zeros along the way, "
                 "stop. It can never become the identity, and you have shown that A is singular.",
                 "lec08"),
                summary="For larger matrices, row reduce [A | I] until the left half is I. A zero "
                        "row on the left means there is no inverse.",
                at="deep",
            ),
            b.prose(
                "It helps to know what a singular matrix has lost. An invertible matrix sends "
                "different vectors to different results, so each result can be traced back to where "
                "it came from. A singular matrix sends some nonzero vector to zero, and once two "
                "inputs give the same output nothing can tell them apart again, which is why no "
                "matrix can undo it. The matrix with rows (1, 2) and (2, 4) is an example: its "
                "second row is twice its first, ad - bc is 4 - 4, and it flattens the whole plane "
                "onto a single line. In a problem, a row or column that is a multiple of another is "
                "a sign to stop and test ad - bc before computing anything else.",
                summary="A singular matrix sends some nonzero vector to zero, so its action cannot "
                        "be undone. A row that is a multiple of another is the warning sign.",
                at="deep",
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
                ("The **determinant** is a single number computed from a square matrix. For the 2 by "
                 "2 matrix with rows (a, b) and (c, d) it is ad - bc: multiply down the main "
                 "diagonal, then subtract the product of the other diagonal. The number has a "
                 "meaning you can picture. It measures how the matrix scales area, so a determinant "
                 "of 3 means every region comes out three times as large.", "lec10"),
                ("The value that matters most is 0. A matrix is invertible exactly when its "
                 "determinant is not 0, so this one number answers a question that otherwise takes a "
                 "full row reduction. A zero determinant means the matrix squashes area down to "
                 "nothing, and a shape that has been flattened cannot be restored, which is the "
                 "picture behind having no inverse.", "lec10"),
                summary="The determinant of a 2 by 2 matrix is ad - bc. It measures how area is "
                        "scaled, and it is 0 exactly when the matrix has no inverse.",
            ),
            b.formula(
                "Determinant of a 2 by 2 matrix",
                r"\det\begin{pmatrix} a & b \\ c & d \end{pmatrix} = ad - bc",
                "The determinant of the matrix a b c d is a d minus b c.",
                "lec10",
            ),
            b.prose(
                "Take the area picture one step further, because it explains the rules and saves "
                "you memorising them. The matrix sends the unit square to a parallelogram whose "
                "sides are its two columns, and ad - bc is the area of that parallelogram, with a "
                "sign. The sign records whether the square was flipped over on the way, which is "
                "why swapping two rows, a flip, changes the sign and not the size. And if one "
                "column is a multiple of the other, the parallelogram has collapsed onto a line and "
                "its area is 0. Dependent columns, zero area and a zero determinant are one event "
                "seen three ways.",
                summary="ad - bc is the signed area of the parallelogram made by the columns. "
                        "Dependent columns flatten it, so the determinant is 0.",
                at="deep",
            ),
            b.prose(
                ("Larger determinants are built from 2 by 2 ones. To expand a 3 by 3 determinant "
                 "along its first row, take each entry in turn, cross out its row and its column, "
                 "and multiply the entry by the determinant of the 2 by 2 matrix that is left. Then "
                 "combine the three products with alternating signs: plus, minus, plus. The middle "
                 "minus is the step that gets lost, and it is one of the two slips your quizzes "
                 "show. Write the three signs above the row before you start, so that the sign is "
                 "on the page before the arithmetic is.", "lec10"),
                summary="Expand a 3 by 3 along a row: each entry times the 2 by 2 determinant left "
                        "over, with signs plus, minus, plus.",
                at="standard",
            ),
            b.mistakes(
                (0, "Dropping the minus sign on the middle cofactor",
                 "Write the signs + - + above the row before you expand, then copy them down."),
                (1, "Splitting a determinant over a sum",
                 "det(A + B) is not det A + det B. Only products split: det(AB) = det A det B."),
            ),
            b.prose(
                "A small case makes the expansion concrete. Take the matrix with rows (1, 2, 0), "
                "(0, 3, 1) and (2, 0, 1) and expand along the first row. The first entry is 1, and "
                "crossing out its row and column leaves rows (3, 1) and (0, 1), with determinant 3. "
                "The second entry is 2, and it leaves rows (0, 1) and (2, 1), with determinant -2. "
                "The third entry is 0, so its term vanishes whatever is left. With the signs, the "
                "total is 1 times 3, minus 2 times -2, plus 0, which is 7. The zero in the row "
                "saved a third of the work, so when you may choose the row, choose the one with the "
                "most zeros.",
                summary="Rows (1, 2, 0), (0, 3, 1), (2, 0, 1) expand along the first row to "
                        "3 + 4 + 0 = 7. Pick the row with the most zeros.",
                at="deep",
            ),
            b.prose(
                ("The second slip is to treat the determinant as if it respected addition. It does "
                 "not: the determinant of A + B is not the sum of the two determinants. What it "
                 "respects is multiplication. The determinant of a product is the product of the "
                 "determinants, and swapping two rows flips the sign. Those rules often let you "
                 "answer without expanding anything. If one factor of a product has determinant 0, "
                 "so does the product, and the product has no inverse. The table collects what a "
                 "zero or nonzero determinant tells you, and its first row is the one the others "
                 "follow from.", "lec10"),
                summary="Determinants split over products, not sums: det(AB) = det A det B. Swapping "
                        "two rows flips the sign.",
                at="standard",
            ),
            b.compare(
                "What the determinant tells you", ("det A is not 0", "det A is 0"),
                ("Inverse", "Exists", "Does not exist"),
                ("Solutions of Ax = b", "Exactly one", "None or infinitely many"),
                ("Columns of A", "Linearly independent", "Linearly dependent"),
                emphasis=0,
            ),
            b.prose(
                "Read down the table and you will see one fact said three ways. A matrix with a "
                "nonzero determinant has an inverse, gives exactly one solution to Ax = b, and has "
                "independent columns, and a matrix with a zero determinant fails all three "
                "together. The map shows where this is heading. Finding eigenvalues means asking "
                "for which numbers t the matrix A - tI has determinant 0, so the test you are "
                "practising here becomes an equation to solve there.",
                summary="An inverse, exactly one solution and independent columns all go with a "
                        "nonzero determinant. Eigenvalues reuse the zero test.",
                at="standard",
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
                ("A **linear combination** of vectors adds scalar multiples of them. A set of "
                 "vectors is **linearly independent** when the only combination that gives the zero "
                 "vector is the one with every coefficient 0. If some other combination also "
                 "reaches zero, the set is dependent, and that means one of its vectors is a "
                 "combination of the others and adds nothing new.", "lec12"),
                ("You rarely decide this by staring. The test is mechanical: put the vectors in the "
                 "columns of a matrix and row reduce. A pivot in every column means the set is "
                 "independent. A column without a pivot gives a free variable, the free variable "
                 "gives a combination that reaches zero without all zero coefficients, and the set "
                 "is dependent.", "lec12"),
                summary="Independent means only the all-zero combination gives the zero vector. Put "
                        "the vectors in columns, row reduce and look for a pivot in every column.",
            ),
            b.terms(_C["independence"],
                    ("Linear combination", "A sum of scalar multiples of vectors."),
                    ("Dependent", "Not independent: some vector in the set is a combination of the others.")),
            b.prose(
                "A picture helps. Two independent vectors in the plane point in different "
                "directions, and between them they can reach every point of it. Two dependent "
                "vectors lie along the same line through the origin, so the second takes you "
                "nowhere the first could not. In space, three vectors are dependent when all three "
                "lie in one plane through the origin. In every case the dependent set has wasted a "
                "vector: it has more members than it has directions. That is the idea to hold on "
                "to, because the next topic, a basis, is a set that reaches a whole space with no "
                "vector wasted.",
                summary="Dependent vectors waste a direction: two on one line, or three in one "
                        "plane. An independent set has no vector to spare.",
                at="deep",
            ),
            b.prose(
                "The two ways of saying it are worth connecting, since questions use both. Suppose "
                "a combination with nonzero coefficients gives zero. Pick a vector whose "
                "coefficient is not 0, move everything else to the other side and divide, and you "
                "have written that vector in terms of the rest. So a set is dependent exactly when "
                "some vector in it is redundant. For two vectors you can see this by eye: they are "
                "dependent when one is a multiple of the other, which is the case the example works "
                "through. With three or more a quick look is not enough, and you row reduce.",
                summary="A set is dependent exactly when one vector can be written from the others. "
                        "Two vectors are dependent when one is a multiple of the other.",
                at="standard",
            ),
            b.example(
                "Are these independent?",
                "Are (1, 2) and (2, 4) linearly independent?",
                ("Look for a multiple", "(2, 4) = 2 (1, 2)", "The second vector is twice the first."),
                ("Write the combination", "2 (1, 2) - (2, 4) = (0, 0)", "A combination with nonzero coefficients gives zero."),
                ("Answer", "Dependent", "Both vectors lie on the same line through the origin."),
                source="lec12",
            ),
            b.prose(
                "Three special cases come up often enough to learn. Any set that contains the zero "
                "vector is dependent, because you can put a nonzero coefficient on the zero vector "
                "and 0 on everything else. A single nonzero vector on its own is independent. And "
                "adding a vector to a dependent set never repairs it, since the old combination "
                "that reached zero still works with a coefficient of 0 on the newcomer. When a row "
                "reduction does find a free variable, it also tells you which vector is the spare "
                "one: the column without a pivot is a combination of the pivot columns before it.",
                summary="A set containing the zero vector is dependent, and adding vectors never "
                        "fixes dependence. The column with no pivot is the spare vector.",
                at="deep",
            ),
            b.prose(
                ("Counting can settle the question before any arithmetic. A matrix has at most one "
                 "pivot in each row. So four vectors in R^3, placed in the columns of a matrix with "
                 "3 rows, have at most 3 pivots between them, and one column is left without. Such "
                 "a set is dependent whatever the vectors are. The reverse does not hold. Having "
                 "few vectors promises nothing, and a set of the right size still has to be tested "
                 "with the row reduction from lecture.", "lec12"),
                summary="A matrix has at most one pivot per row, so more vectors than rows are "
                        "always dependent. Fewer vectors still have to be tested.",
                at="standard",
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
                ("The **span** of a set of vectors is every linear combination of them: everything "
                 "you can reach by scaling the vectors and adding the results. One nonzero vector "
                 "spans the line through the origin in its direction. Two vectors that point in "
                 "different directions span a whole plane. Adding a vector enlarges the span only "
                 "when the new vector was not already inside it.", "lec12"),
                ("A **basis** of a space is a set that does two jobs at once: it spans the space, "
                 "and it is linearly independent, so no vector in it is redundant. Every basis of "
                 "the same space has the same number of vectors. That number is the **dimension** "
                 "of the space, which is why a line has dimension 1 and a plane has dimension 2.",
                 "lec14"),
                summary="The span is every combination of a set. A basis spans a space with no "
                        "redundant vector, and the size of any basis is the dimension.",
            ),
            b.prose(
                "The two jobs pull in opposite directions, and that is the easiest way to remember "
                "them. Spanning asks for enough vectors: too few and some part of the space cannot "
                "be reached. Independence asks for no more than enough: too many and one of them is "
                "a combination of the rest. A basis is the set that sits exactly between. So "
                "testing a basis always takes two checks, and passing one says nothing about the "
                "other. Stopping after the first check, usually the spanning one, is the slip your "
                "quiz history shows.",
                summary="Spanning needs enough vectors and independence needs no spare ones. A basis "
                        "passes both tests, so always run both.",
                at="standard",
            ),
            b.mistakes(
                (0, "Calling a spanning set a basis",
                 "A basis has two jobs. After checking that the set spans, also check that it is independent."),
            ),
            b.prose(
                "A common task is to find the dimension of a span, and it is the same reduction "
                "read once more. Suppose you are given four vectors and asked for the dimension of "
                "what they span. Put them in columns, reduce, and count the pivots. Each pivot "
                "column is a vector that added a new direction. Each column without a pivot was "
                "already a combination of the ones before it, and it can be thrown out without "
                "shrinking the span. The pivot columns of the original matrix are then a basis of "
                "the span, and their number is its dimension. So four vectors with two pivots span "
                "a plane, however many of them you were handed.",
                summary="The dimension of a span is the number of pivots. The pivot columns of the "
                        "original matrix form a basis of it.",
                at="deep",
            ),
            b.prose(
                ("In practice one row reduction answers both questions. Put the vectors in the "
                 "columns of a matrix and reduce. A pivot in every row means the columns reach "
                 "every right-hand side, so they span the space. A pivot in every column means they "
                 "are independent. A basis of R^n needs both, and that forces exactly n vectors. So "
                 "count first: a set of the wrong size is ruled out with no arithmetic, and a set "
                 "of the right size still has to be tested. The table keeps the three words "
                 "apart.", "lec12"),
                summary="Row reduce with the vectors as columns: a pivot in every row means they "
                        "span, and a pivot in every column means they are independent.",
                at="standard",
            ),
            b.compare(
                "Three words that get mixed up", ("Means", "In the plane"),
                ("Span", "Every combination of the set", "(1, 0) and (0, 1) span all of it"),
                ("Basis", "Spans and is independent", "Any two independent vectors"),
                ("Dimension", "The size of any basis", "2"),
                emphasis=1,
            ),
            b.prose(
                "There is a second way to say what a basis is, and it explains why both jobs are "
                "needed. A set is a basis exactly when every vector in the space can be written as "
                "a combination of it in one way and only one. Spanning says there is at least one "
                "way. Independence says there is at most one, because two different ways of writing "
                "the same vector would subtract to a combination that reaches zero without all zero "
                "coefficients. The coefficients in that single way are the coordinates of the "
                "vector. With the usual basis (1, 0) and (0, 1) they are the entries you already "
                "know, and with another basis they are different numbers for the same point.",
                summary="With a basis, every vector is a combination in exactly one way. Spanning "
                        "gives a way and independence makes it the only one.",
                at="deep",
            ),
            b.prose(
                ("Dimension is the payoff. Because every basis of a space has the same size, the "
                 "dimension is a property of the space and not of the vectors you happened to pick. "
                 "It tells you how many numbers you need to name a point in it: one along a line, "
                 "two in a plane. The map shows the order these ideas build in. Independence came "
                 "first, span and basis join it to the idea of a space, and subspaces, which come "
                 "next, are the spaces whose bases and dimensions you will be asked to find.",
                 "lec14"),
                summary="Every basis of a space has the same size, so dimension belongs to the "
                        "space. It counts the numbers needed to name a point.",
                at="standard",
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
                ("A **subspace** of R^n is a set of vectors that passes three tests. It contains the "
                 "zero vector. It is closed under addition: add any two vectors in the set and the "
                 "sum is still in the set. And it is closed under scalar multiplication: multiply "
                 "any vector in the set by any number and the result is still in the set.", "lec14"),
                ("A line through the origin is a subspace, and a line that misses the origin is not. "
                 "That pair is the picture to keep. A subspace is a flat piece of the space that "
                 "passes through the origin and goes on forever in its own directions: the origin "
                 "alone, a line, a plane, or the whole space. Nothing curved, bounded or shifted "
                 "qualifies.", "lec14"),
                summary="A subspace contains zero and is closed under addition and under scaling. "
                        "Think of a line or plane through the origin.",
            ),
            b.terms(_C["subspaces"],
                    ("Null space", "Every vector x with Ax = 0. It is always a subspace."),
                    ("Column space", "The span of the columns of A. It is always a subspace.")),
            b.prose(
                ("The two subspaces named above are the ones you will meet most, and you never have "
                 "to test them. The column space of A is the span of its columns, and a span is "
                 "always a subspace, since combinations of combinations are still combinations. The "
                 "null space is every x with Ax = 0. It holds zero because A times zero is zero. If "
                 "Ax = 0 and Ay = 0 then A(x + y) = 0, and A(cx) is c times Ax, which is 0, so sums "
                 "and multiples stay inside. Notice where they live. For a matrix with 2 rows and 3 "
                 "columns, the column space sits in R^2 and the null space in R^3.", "lec14"),
                summary="A span is always a subspace, and so is the null space, every x with Ax = 0. "
                        "The two can sit in different spaces.",
                at="deep",
            ),
            b.prose(
                "To show that a set is not a subspace you need only one failure, so look for the "
                "cheapest. Try the zero vector first: put zeros into the condition that defines the "
                "set and see whether it holds. A set defined by an equation with a nonzero constant "
                "on the right fails here at once. If zero is in the set, try scaling next, and "
                "multiply a vector of the set by -1 or by a large number. Sets with an edge, such "
                "as a disc around the origin, fail this test. Only when both pass is it worth "
                "adding two general vectors. The example needs just the first test.",
                summary="One failed test is enough. Check the zero vector first, then scaling, and "
                        "only then sums.",
                at="standard",
            ),
            b.example(
                "Run the three tests",
                "Is the set of vectors (x, y) with x + y = 1 a subspace of the plane?",
                ("Zero test", "0 + 0 = 0, not 1", "The zero vector is not in the set."),
                ("Stop here", "Not a subspace", "One failed test is enough."),
                ("Compare", "x + y = 0 passes all three", "Moving the line through the origin fixes it."),
            ),
            b.prose(
                "Showing that a set is a subspace is the harder direction, because examples prove "
                "nothing: the tests must hold for every vector in the set. Work with letters. Take "
                "two general vectors that satisfy the defining condition, add them, and show that "
                "the sum satisfies it too. Then scale a general vector by a general number c and do "
                "the same. For the line x + y = 0 this takes two lines. If x + y = 0 and u + v = 0, "
                "then (x + u) + (y + v) = 0, and cx + cy is c times (x + y), which is 0. That is "
                "the line the example's last step points at.",
                summary="To prove a set is a subspace, add two general members and scale one by a "
                        "general number, and show the condition still holds.",
                at="standard",
            ),
            b.prose(
                "One near miss deserves a warning, because it looks so much like a subspace. The "
                "solutions of Ax = b, when b is not zero, do not form one. Zero is not a solution, "
                "since A times zero is zero and not b, so the first test already fails. What you "
                "have is the null space moved off the origin: the same shape, shifted. The line "
                "x + y = 1 in the example is exactly this, a copy of the line x + y = 0 pushed "
                "sideways. So being flat is not enough. A subspace has to pass through the origin, "
                "and of all the solution sets you will meet, only those of Ax = 0 do.",
                summary="The solutions of Ax = b with b not zero are a shifted copy of the null "
                        "space, and not a subspace, because zero is not among them.",
                at="deep",
            ),
            b.prose(
                ("Once a set is known to be a subspace, the natural questions are its basis and its "
                 "dimension, and row reduction answers both. For a null space, reduce A and solve "
                 "Ax = 0: each free variable gives one basis vector, so the dimension of the null "
                 "space is the number of free variables. For a column space, the pivot columns of A "
                 "form a basis, so its dimension is the number of pivots. Every column is one kind "
                 "or the other, which is why the two dimensions always add up to the number of "
                 "columns. That check costs nothing and catches a miscounted pivot.", "lec14"),
                summary="The null space has one basis vector per free variable and the column space "
                        "one per pivot. The two counts add up to the number of columns.",
                at="deep",
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
                ("A **linear transformation** is a rule T that turns vectors into vectors and "
                 "respects the two vector operations. It respects addition: T(u + v) = T(u) + T(v). "
                 "It respects scaling: T(cv) = cT(v). In words, you may add or scale before applying "
                 "T or after, and the result is the same. One consequence is immediate: every "
                 "linear transformation sends the zero vector to the zero vector.", "reading"),
                ("The second fact is what makes the idea usable. Every linear transformation from "
                 "R^n to R^m is multiplication by a matrix, and you can read that matrix off "
                 "directly: its columns are the images of the **standard basis vectors**. So to "
                 "find the matrix of a transformation of the plane, ask only where (1, 0) and "
                 "(0, 1) go, and write the two answers down as columns.", "reading"),
                summary="A linear transformation respects addition and scaling, so it sends zero to "
                        "zero. Its matrix has the images of the standard basis vectors as columns.",
            ),
            b.formula(
                "Linearity in one line",
                r"T(a\mathbf{u} + b\mathbf{v}) = a\,T(\mathbf{u}) + b\,T(\mathbf{v})",
                "T of a u plus b v equals a times T of u plus b times T of v.",
                "reading",
            ),
            b.prose(
                "The formula packs both rules into one line, and it explains why two columns are "
                "enough. Any vector (x, y) is x times (1, 0) plus y times (0, 1). Apply T and use "
                "linearity: T of that vector is x times T(1, 0) plus y times T(0, 1). So once you "
                "know where the two basis vectors land, you know where everything lands, and that "
                "combination of two columns is exactly what multiplying the matrix by (x, y) "
                "computes. A transformation that is not linear offers no such shortcut. You would "
                "have to be told its value at every point separately.",
                summary="Every vector is a combination of the basis vectors, so their two images "
                        "decide where everything goes.",
                at="standard",
            ),
            b.prose(
                ("The reading's three examples in the plane are worth being able to produce on "
                 "demand. A rotation turns every vector by the same angle, a reflection flips "
                 "across a line, and a shear slides points parallel to an axis. For each, find the "
                 "matrix the same way: follow (1, 0), follow (0, 1), and write the results as "
                 "columns. Under a quarter turn, (1, 0) goes to (0, 1) and (0, 1) goes to (-1, 0), "
                 "and those are the columns of the rotation in the table. The table lists rows, so "
                 "read down it to see the columns.", "reading"),
                summary="Rotations, reflections and shears are all linear. Find each matrix by "
                        "following (1, 0) and (0, 1) and writing where they land as columns.",
                at="standard",
            ),
            b.compare(
                "Three maps of the plane", ("Matrix rows", "What it does"),
                ("Rotation by 90 degrees", "(0, -1) and (1, 0)", "Turns every vector a quarter turn"),
                ("Reflection in the x axis", "(1, 0) and (0, -1)", "Flips the sign of y"),
                ("Shear", "(1, 1) and (0, 1)", "Slides points sideways by their height"),
                emphasis=0,
            ),
            b.prose(
                "Showing that a map is not linear takes one counterexample, and the zero vector is "
                "the first place to look: if T moves zero, you are done. Passing that test proves "
                "nothing, though. The map that squares each entry sends zero to zero and still "
                "fails, because doubling the input (1, 1) should double the output, and it gives "
                "(4, 4) where twice the output is (2, 2). So when zero stays put, test scaling "
                "next, with a simple vector and the number 2 or -1. Anything with a constant added, "
                "an entry squared, or two entries multiplied together is a warning sign.",
                summary="A map that moves zero is not linear, but one that fixes zero can still "
                        "fail. Test scaling with a simple vector next.",
                at="deep",
            ),
            b.prose(
                "Transformations also give you a second way to think about matrix products. If S "
                "and T are linear with matrices A and B, then doing T first and S second is linear "
                "too, and its matrix is the product AB. The matrix on the right acts first, which "
                "is the same convention as in a product of matrices because it is the same thing. "
                "This makes the order rule easy to see. Shear the plane and then rotate it, and a "
                "square ends up somewhere different from where rotating and then shearing puts it, "
                "so the two products cannot be equal. Whenever a question chains transformations, "
                "write the matrices from right to left in the order the steps happen.",
                summary="Doing one linear map after another multiplies their matrices, with the "
                        "first step written on the right.",
                at="deep",
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
                ("Most vectors are turned when a matrix A acts on them. An **eigenvector** of A is a "
                 "nonzero vector that is not: A only stretches it, so Av is a multiple of v and "
                 "lies along the same line as v. The multiple is the **eigenvalue** that goes with "
                 "that eigenvector. An eigenvalue of 3 means the vector comes out three times as "
                 "long, pointing the same way.", "lec16"),
                ("Eigenvalues are found before eigenvectors. They are the solutions of "
                 "det(A - tI) = 0, where A - tI is A with t subtracted from each entry on its "
                 "diagonal. The left side works out to a polynomial in t, the **characteristic "
                 "polynomial**, so for a 2 by 2 matrix the whole job comes down to solving a "
                 "quadratic.", "lec16"),
                summary="An eigenvector is only stretched by A, and its eigenvalue is the stretch "
                        "factor. Find the eigenvalues by solving det(A - tI) = 0.",
            ),
            b.bridge(
                "Switch the chart to After A and compare the two arrows: one stays on its own line "
                "and the other leaves it.",
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
            b.prose(
                ("The equation is not arbitrary, and seeing where it comes from prevents the slip "
                 "your quizzes show. Av = tv can be rewritten as (A - tI)v = 0. That asks for a "
                 "nonzero vector that the matrix A - tI sends to zero, and a matrix does that "
                 "exactly when it has no inverse, which means its determinant is 0. So the "
                 "determinant you need is that of A - tI, with the t already subtracted on the "
                 "diagonal. Setting det(A) to 0 answers a different question, whether A itself is "
                 "invertible, and has no t in it to solve for.", "lec16"),
                summary="Av = tv means A - tI sends a nonzero vector to zero, so A - tI must have "
                        "determinant 0. Subtract t before taking the determinant.",
                at="standard",
            ),
            b.mistakes(
                (0, "Setting det(A) to zero",
                 "Subtract t from each diagonal entry first. The equation is det(A - tI) = 0."),
            ),
            b.prose(
                ("For a 2 by 2 matrix the routine has four moves, and the example goes through them "
                 "on the matrix from lecture. Subtract t from both diagonal entries. Take ad - bc "
                 "of the result. Multiply out to get a quadratic in t. Then factor it, or use the "
                 "quadratic formula. The lecture's matrix, with rows (2, 1) and (1, 2), gives "
                 "t^2 - 4t + 3 = 0. Two quick checks catch most errors: the eigenvalues should add "
                 "up to the sum of the diagonal entries of A, and multiply to its determinant.",
                 "lec16"),
                summary="Subtract t on the diagonal, take ad - bc, expand and solve the quadratic. "
                        "The eigenvalues add up to the diagonal sum of A.",
                at="standard",
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
            b.prose(
                ("Solving a polynomial is not the only way to reach an eigenvalue. The lecture's "
                 "power iteration demo starts from (1, 0) and multiplies by A again and again, and "
                 "each round the vector swings closer to the direction that A stretches most. The "
                 "estimate of the largest eigenvalue began at 2, reached 2.8 after one step and "
                 "2.98 after two, and settled on 3.0 by the fourth. Read the chart for its shape: a "
                 "fast climb, then a levelling off at the largest eigenvalue, the same 3 that the "
                 "quadratic gave.", "lec16"),
                summary="Multiplying by A over and over pulls a vector toward the most stretched "
                        "direction, and the estimate levels off at the largest eigenvalue.",
                at="standard",
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
