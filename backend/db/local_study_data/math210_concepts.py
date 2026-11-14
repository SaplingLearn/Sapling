"""MATH210's concept tree: the units and the concepts under them. Its own
module because the class's documents and coursework (``math210.py``) and its
study guides (``math210_guides.py``) both read it."""
from __future__ import annotations

from db.local_study_data.spec import Concept

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
