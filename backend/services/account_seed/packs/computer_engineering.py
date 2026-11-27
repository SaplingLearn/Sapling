"""Computer Engineering seed pack.

Five real BU courses, read off the catalog in November 2026: the four-credit
technical core (CAS MA 225, CAS CH 131, QST SI 480) stacked with the two
two-credit courses a BU CompE actually carries alongside them (ENG EK 131,
COM CO 540). That five-course shape is why ``MajorPack.courses`` allows five.

Student profile: fluent with vectors, partial derivatives and a breadboard —
EK 131's hardware bench is where this student is happiest. Solid but slowing
in MA 225 once integration leaves Cartesian coordinates, genuinely struggling
with CH 131 thermodynamics and electrochemistry, strong on the partner-facing
half of the MiSIP practicum and weak on measuring its impact, and comfortable
with SI 480 business models while financial statements stay opaque.

Note on COM CO 540: the catalog body is only "Topics vary each semester", so
the content here follows the Fall 2026 A1 section topic, Media Innovation &
Social Impact Practicum (MiSIP).
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
# CAS MA 225 — Multivariate Calculus
# ---------------------------------------------------------------------------

MA225 = Course(
    code="CAS MA 225",
    name="Multivariate Calculus",
    department="Mathematics & Statistics",
    credits=4,
    nickname="Multivariate",
    color="#7C3AED",
    concepts=[
        Concept(name="Vectors, Lines and Planes", mastery=0.92,
                description="Dot and cross products, projections, the parametric and symmetric forms of a "
                            "line, and the point-normal equation of a plane in space."),
        Concept(name="Partial Derivatives", mastery=0.86,
                description="Differentiating in one variable while the others are held fixed, higher-order "
                            "and mixed partials, Clairaut's theorem, and the multivariable chain rule."),
        Concept(name="Directional Derivatives", mastery=0.78,
                description="The rate of change of f along a unit vector u, computed as the dot product of "
                            "the gradient with u, and why u must be normalised first."),
        Concept(name="The Gradient", mastery=0.71,
                description="The vector of partials: it points in the direction of steepest increase, its "
                            "length is the maximum rate of change, and it is normal to level curves."),
        Concept(name="Multivariate Minimization", mastery=0.62,
                description="Critical points where the gradient vanishes, the second-derivative test with "
                            "the discriminant D, saddle points, and Lagrange multipliers for constraints."),
        Concept(name="Multiple Integration", mastery=0.55,
                description="Double and triple integrals as limits of Riemann sums, Fubini's theorem, and "
                            "choosing an order of integration for a general, non-rectangular region."),
        Concept(name="Cylindrical and Spherical Coordinates", mastery=0.38,
                description="Converting a triple integral into r dr dtheta dz or rho^2 sin(phi) drho dphi "
                            "dtheta, and reading the bounds off a cylinder, cone or sphere."),
        Concept(name="Scalar and Vector Fields", mastery=0.27,
                description="Functions assigning a number or a vector to each point of space, their flow "
                            "pictures, and the divergence and curl operators built from the gradient."),
        Concept(name="Potentials", mastery=0.12,
                description="Conservative vector fields written as the gradient of a scalar potential, path "
                            "independence of their line integrals, and the curl test for conservativeness."),
        Concept(name="Stokes's Theorem", mastery=0.04,
                description="Relating the circulation of a field around a closed curve to the flux of its "
                            "curl through any surface the curve bounds; Green's theorem is the flat case."),
    ],
    edges=[
        Edge(source="Vectors, Lines and Planes", target="Scalar and Vector Fields",
             relationship="prerequisite", strength=0.85),
        Edge(source="Partial Derivatives", target="Directional Derivatives",
             relationship="prerequisite", strength=0.9),
        Edge(source="Directional Derivatives", target="The Gradient",
             relationship="prerequisite", strength=0.9),
        Edge(source="The Gradient", target="Multivariate Minimization",
             relationship="prerequisite", strength=0.85),
        Edge(source="The Gradient", target="Potentials",
             relationship="prerequisite", strength=0.7),
        Edge(source="Multiple Integration", target="Cylindrical and Spherical Coordinates",
             relationship="prerequisite", strength=0.88),
        Edge(source="Scalar and Vector Fields", target="Stokes's Theorem",
             relationship="prerequisite", strength=0.8),
        Edge(source="Potentials", target="Stokes's Theorem",
             relationship="related", strength=0.6),
        Edge(source="Vectors, Lines and Planes", target="Multiple Integration",
             relationship="builds_on", strength=0.5),
    ],
    mastery_events=[
        MasteryEvent(concept="Partial Derivatives", delta=0.09, reason="HW 3 clean on mixed partials"),
        MasteryEvent(concept="The Gradient", delta=0.11, reason="Tutor session on level curves"),
        MasteryEvent(concept="Cylindrical and Spherical Coordinates", delta=-0.06,
                     reason="Dropped the Jacobian on Quiz 4"),
        MasteryEvent(concept="Multiple Integration", delta=0.05, reason="Fixed the HW 6 bounds"),
    ],
    categories=[
        Category(name="Homework", weight=0.2),
        Category(name="Discussion Quizzes", weight=0.15, drop_lowest=1),
        Category(name="Midterm Exams", weight=0.35),
        Category(name="Final Exam", weight=0.3),
    ],
    assignments=[
        Assignment(title="HW 1: Vectors, Lines and Planes", category="Homework", type="homework",
                   due_offset_days=9, points_possible=25, points_earned=25),
        Assignment(title="HW 3: Partial Derivatives and the Chain Rule", category="Homework",
                   type="homework", due_offset_days=28, points_possible=25, points_earned=23),
        Assignment(title="Quiz 2: Gradients and Directional Derivatives", category="Discussion Quizzes",
                   type="quiz", due_offset_days=37, points_possible=20, points_earned=17),
        Assignment(title="Midterm Exam 1", category="Midterm Exams", type="exam",
                   due_offset_days=49, points_possible=100, points_earned=88, is_midterm=True),
        Assignment(title="HW 6: Double Integrals over General Regions", category="Homework",
                   type="homework", due_offset_days=63, points_possible=25, points_earned=20),
        Assignment(title="Quiz 4: Cylindrical and Spherical Coordinates", category="Discussion Quizzes",
                   type="quiz", due_offset_days=75, points_possible=20),
        Assignment(title="Midterm Exam 2", category="Midterm Exams", type="exam",
                   due_offset_days=88, points_possible=100),
        Assignment(title="Final Exam", category="Final Exam", type="exam",
                   due_offset_days=110, points_possible=150),
    ],
    notes=[
        Note(
            title="Gradient, directional derivative, level curves — one picture",
            tags=["gradient", "midterm1", "ma225"],
            concepts=["The Gradient", "Directional Derivatives"],
            body=(
                "Three things that are actually one thing, which I kept treating as three.\n\n"
                "**The gradient** is just the vector of partials:\n"
                "```\n"
                "grad f = < f_x , f_y >\n"
                "```\n\n"
                "**The directional derivative** along a direction v is the gradient dotted with the "
                "UNIT vector:\n"
                "```\n"
                "D_u f = grad f . u ,   u = v / |v|\n"
                "```\n"
                "Normalising is the step I keep skipping. If v = <3, 4> then u = <3/5, 4/5>. Dotting with "
                "<3, 4> itself gives an answer 5x too big, and that was most of the Quiz 2 damage.\n\n"
                "**Why the gradient is special:** D_u f = |grad f| |u| cos(theta) = |grad f| cos(theta), "
                "since |u| = 1. That is largest when theta = 0 — when u points along grad f. So:\n\n"
                "- steepest increase: direction of grad f, rate |grad f|\n"
                "- steepest decrease: direction of -grad f, rate -|grad f|\n"
                "- no change at all: any u perpendicular to grad f\n\n"
                "**Level curves.** That last bullet is the whole reason grad f is normal to the level "
                "curve f(x, y) = c. Walking along a level curve, f does not change, so D_u f = 0, so u is "
                "perpendicular to grad f. Every contour-map picture in lecture is that one sentence.\n\n"
                "Worked check: f(x, y) = x^2 y + 3y^2 at (1, 2). f_x = 2xy = 4, f_y = x^2 + 6y = 13, so "
                "grad f = <4, 13>, steepest climb is along <4, 13>/sqrt(185), and that direction is the "
                "normal to the level curve through (1, 2)."
            ),
        ),
        Note(
            title="Bounds in polar, cylindrical and spherical (still shaky)",
            tags=["integration", "coordinates", "hw6"],
            concepts=["Cylindrical and Spherical Coordinates", "Multiple Integration"],
            body=(
                "I can do the integral once the bounds are written down. Writing them down is the problem, "
                "and Quiz 4 proved it. Collecting the three templates in one place.\n\n"
                "## The volume elements (memorise these, they are free points)\n"
                "```\n"
                "polar        dA = r dr dtheta\n"
                "cylindrical  dV = r dr dtheta dz\n"
                "spherical    dV = rho^2 sin(phi) drho dphi dtheta\n"
                "```\n"
                "The extra factors are Jacobians, not decoration. I dropped sin(phi) on the quiz and the "
                "answer came out off by a clean factor of 2 — which is exactly what integrating sin(phi) "
                "from 0 to pi gives you, so that error has a signature.\n\n"
                "## Spherical conventions in this class\n"
                "phi is measured DOWN from the positive z-axis, so phi runs 0 to pi; theta runs 0 to 2pi "
                "in the xy-plane.\n"
                "```\n"
                "x = rho sin(phi) cos(theta)\n"
                "y = rho sin(phi) sin(theta)\n"
                "z = rho cos(phi)\n"
                "```\n"
                "The one I get wrong under time pressure is z: it is rho cos(phi), NOT rho sin(phi).\n\n"
                "## Which coordinates for which solid\n"
                "- a cylinder, or anything with a fixed radius and a z-range -> cylindrical\n"
                "- a sphere, a ball, an ice-cream cone, anything with rho bounds -> spherical\n"
                "- the cone z = sqrt(x^2 + y^2) is just phi = pi/4 in spherical. That is a CONSTANT bound, "
                "which is the entire reason to switch.\n\n"
                "HW 6 example: inside x^2 + y^2 = 4, between z = 0 and z = 3. In cylindrical that is "
                "0 <= r <= 2, 0 <= theta <= 2pi, 0 <= z <= 3. Radius 2, not 4 — the equation gives r^2 = 4."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ma225-syllabus-fall.pdf",
            category="syllabus",
            summary="Syllabus for CAS MA 225 Multivariate Calculus: lecture MWF with a required discussion "
                    "section, weekly homework, discussion quizzes, two midterms and a cumulative final.",
            concept_notes=[
                ConceptNote(name="Vectors, Lines and Planes", description="Weeks 1-2, the geometry warm-up."),
                ConceptNote(name="Partial Derivatives",
                            description="Weeks 4-5, through the chain rule and Clairaut's theorem."),
                ConceptNote(name="Multiple Integration", description="Weeks 9-10, after Midterm 1."),
                ConceptNote(name="Stokes's Theorem",
                            description="Week 14, the last topic before the final."),
            ],
            extracted_text=(
                "CAS MA 225 Multivariate Calculus\n"
                "Boston University, Department of Mathematics and Statistics\n"
                "Lecture A1 MWF 10:10-11:00, CAS 224. Students registering for MA 225 A1 must also "
                "register for a discussion section A2-A6.\n\n"
                "Prerequisites: CAS MA 124 or CAS MA 129. This course cannot be taken for credit in "
                "addition to CAS MA 230.\n\n"
                "Course Description: Vectors, lines, planes. Multiple integration, cylindrical and "
                "spherical coordinates. Partial derivatives, directional derivatives, scalar and vector "
                "fields, the gradient, potentials, approximation, multivariate minimization, Stokes's and "
                "related theorems.\n\n"
                "Grading\n"
                "  Written homework (weekly)             20%\n"
                "  Discussion quizzes (lowest dropped)   15%\n"
                "  Midterm Exam 1                        17.5%\n"
                "  Midterm Exam 2                        17.5%\n"
                "  Final Exam                            30%\n\n"
                "Calculators are not permitted on exams. Collaboration on homework is encouraged; the "
                "write-up you hand in must be your own.\n\n"
                "Weekly schedule\n"
                "  1-2   Vectors, dot and cross products, lines and planes in space\n"
                "  3     Vector-valued functions, curves, velocity and acceleration\n"
                "  4-5   Partial derivatives, the chain rule, tangent planes and linear approximation\n"
                "  6     Directional derivatives and the gradient\n"
                "  7     Multivariate minimization: critical points and the second-derivative test\n"
                "  8     MIDTERM EXAM 1 (weeks 1-7); Lagrange multipliers\n"
                "  9-10  Double integrals, general regions, polar coordinates\n"
                "  11    Triple integrals; cylindrical and spherical coordinates\n"
                "  12    MIDTERM EXAM 2; scalar and vector fields, divergence and curl\n"
                "  13    Line integrals, conservative fields and potentials\n"
                "  14    Green's theorem; Stokes's theorem and the divergence theorem\n"
                "  15    Review, then the cumulative final exam\n"
            ),
        ),
        Document(
            file_name="ma225-lecture-gradient-and-tangent-planes.pdf",
            category="lecture_notes",
            summary="Lecture notes covering the gradient, directional derivatives, tangent planes and the "
                    "second-derivative test for classifying critical points of a surface.",
            concept_notes=[
                ConceptNote(name="The Gradient",
                            description="Defined, then shown to be normal to every level curve."),
                ConceptNote(name="Directional Derivatives",
                            description="Derived as the gradient dotted with a unit vector."),
                ConceptNote(name="Multivariate Minimization",
                            description="Critical points and the discriminant test."),
            ],
            extracted_text=(
                "MA 225 Lectures 14-16: The Gradient, Tangent Planes and Optimization\n\n"
                "Definition. For f(x, y) the gradient is grad f = < f_x, f_y >. For f(x, y, z) it is "
                "< f_x, f_y, f_z >. The gradient is a VECTOR field built out of a SCALAR field.\n\n"
                "Directional derivative. For a unit vector u, D_u f = grad f . u. The vector must be "
                "normalised: given a direction v, use u = v/|v| first. Since D_u f = |grad f| cos(theta), "
                "the derivative is maximal when u points along grad f, minimal when it points along "
                "-grad f, and zero when u is perpendicular to grad f.\n\n"
                "Consequence. grad f is normal to the level curve f(x, y) = c, and to the level surface "
                "f(x, y, z) = c. Walking along a level set leaves f unchanged, so the direction of travel "
                "has zero directional derivative and is therefore perpendicular to the gradient.\n\n"
                "Tangent plane. The surface z = f(x, y) has tangent plane at (a, b):\n"
                "  z = f(a, b) + f_x(a, b)(x - a) + f_y(a, b)(y - b)\n"
                "This is the linear approximation, and the same formula estimates f near (a, b).\n\n"
                "Optimization. Interior extrema occur at critical points, where grad f = 0. Classify them "
                "with the discriminant D = f_xx f_yy - (f_xy)^2 evaluated at the critical point:\n"
                "  D > 0 and f_xx > 0   local minimum\n"
                "  D > 0 and f_xx < 0   local maximum\n"
                "  D < 0                saddle point\n"
                "  D = 0                test inconclusive\n\n"
                "Constrained optimization. To extremise f subject to g = k, solve grad f = lambda grad g "
                "together with the constraint. Geometrically the level curves of f and g are tangent at "
                "the optimum, so their normal vectors are parallel.\n"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Directional derivative of f along a direction v",
                  back="D_u f = grad f . u where u = v/|v|. Normalise v first — forgetting to is the "
                       "classic factor-of-|v| error."),
        Flashcard(front="In what direction does f increase fastest, and how fast?",
                  back="Along grad f, at rate |grad f|. The fastest decrease is along -grad f."),
        Flashcard(front="Why is the gradient perpendicular to a level curve?",
                  back="Along a level curve f is constant, so D_u f = 0, so grad f . u = 0 — the gradient "
                       "is normal to the direction of travel."),
        Flashcard(front="Second-derivative test: the discriminant D",
                  back="D = f_xx f_yy - (f_xy)^2. D > 0 with f_xx > 0 is a minimum, D > 0 with f_xx < 0 is "
                       "a maximum, D < 0 is a saddle, D = 0 is inconclusive."),
        Flashcard(front="Volume element in cylindrical coordinates",
                  back="dV = r dr dtheta dz. The factor r is the Jacobian, and it is not optional."),
        Flashcard(front="Volume element in spherical coordinates",
                  back="dV = rho^2 sin(phi) drho dphi dtheta, with phi measured from the positive z-axis."),
        Flashcard(front="Spherical conversion formulas",
                  back="x = rho sin(phi) cos(theta), y = rho sin(phi) sin(theta), z = rho cos(phi). "
                       "The z-component uses the COSINE of phi."),
        Flashcard(front="When is a vector field F conservative?",
                  back="When F = grad f for some scalar potential f. Then line integrals are path "
                       "independent and curl F = 0; on a simply connected domain the converse holds too."),
        Flashcard(front="Lagrange multipliers",
                  back="To extremise f subject to g = k, solve grad f = lambda grad g alongside g = k."),
        Flashcard(front="Stokes's theorem",
                  back="The circulation of F around a closed curve C equals the flux of curl F through any "
                       "surface S bounded by C. Green's theorem is the flat, two-dimensional case."),
    ],
    study_guide=StudyGuide(
        overview=(
            "Midterm Exam 1 covers weeks 1-7: the geometry of space, partial derivatives, and everything "
            "built on the gradient up to the second-derivative test. No calculators. The gradient block is "
            "where the points are — roughly half the exam depends on knowing that D_u f = grad f . u with "
            "u normalised, and the last question is reliably an optimization problem."
        ),
        topics=[
            StudyGuideTopic(
                name="Vector geometry in space",
                importance="Two guaranteed opening questions, and every later topic is written in this "
                           "language. The cheapest points on the exam.",
                concepts=["Vectors, Lines and Planes"],
            ),
            StudyGuideTopic(
                name="Partial derivatives and the chain rule",
                importance="Mechanical once practised, but the multivariable chain rule with a tree "
                           "diagram has appeared on both of the last two Midterm 1s.",
                concepts=["Partial Derivatives"],
            ),
            StudyGuideTopic(
                name="The gradient and directional derivatives",
                importance="The core of the exam. Expect to compute a gradient, a directional derivative "
                           "along a non-unit vector, and the direction of steepest ascent.",
                concepts=["The Gradient", "Directional Derivatives"],
            ),
            StudyGuideTopic(
                name="Critical points and optimization",
                importance="The final long-form question. Find where the gradient vanishes, then classify "
                           "with the discriminant; Lagrange multipliers appear only if lecture reached "
                           "them before the exam.",
                concepts=["Multivariate Minimization"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Partial Derivatives", difficulty="easy", days_ago=22,
            questions=[
                QuizQuestion(
                    question="For f(x, y) = x^3 y^2, what is the partial derivative of f with respect to x?",
                    options=["3x^2 y^2", "2x^3 y", "3x^2 y", "x^3 y^2"],
                    correct_answer="3x^2 y^2",
                    explanation="Treat y as a constant. The derivative of x^3 is 3x^2, and the factor y^2 "
                                "rides along unchanged, giving 3x^2 y^2.",
                ),
                QuizQuestion(
                    question="Clairaut's theorem says that when the second partial derivatives are "
                             "continuous near a point, which equality holds there?",
                    options=["f_xy = f_yx", "f_xx = f_yy", "f_xy = 0", "f_x = f_y"],
                    correct_answer="f_xy = f_yx",
                    explanation="Mixed partials taken in either order agree when they are continuous, so "
                                "the order of differentiation does not matter.",
                ),
                QuizQuestion(
                    question="For f(x, y) = sin(xy), what is the partial derivative of f with respect to y?",
                    options=["x cos(xy)", "y cos(xy)", "cos(xy)", "xy cos(xy)"],
                    correct_answer="x cos(xy)",
                    explanation="By the chain rule the derivative of sin(xy) is cos(xy) times the partial "
                                "of xy with respect to y, which is x.",
                ),
            ],
            correct=[0, 1, 2],
        ),
        QuizAttempt(
            concept="The Gradient", difficulty="medium", days_ago=12,
            questions=[
                QuizQuestion(
                    question="For f(x, y) = x^2 y + 3y^2, what is the gradient at the point (1, 2)?",
                    options=["<4, 13>", "<2, 13>", "<4, 7>", "<13, 4>"],
                    correct_answer="<4, 13>",
                    explanation="f_x = 2xy = 2(1)(2) = 4 and f_y = x^2 + 6y = 1 + 12 = 13, so the gradient "
                                "is <4, 13>.",
                ),
                QuizQuestion(
                    question="The directional derivative of f at a point P, along a unit vector u, is "
                             "largest when u points which way?",
                    options=["In the direction of the gradient of f",
                             "Opposite to the gradient of f",
                             "Perpendicular to the gradient of f",
                             "Along the positive x-axis"],
                    correct_answer="In the direction of the gradient of f",
                    explanation="D_u f = |grad f| cos(theta), which is maximal at theta = 0 — that is, "
                                "when u is aligned with the gradient.",
                ),
                QuizQuestion(
                    question="What is the maximum rate of change of f at a point P?",
                    options=["|grad f(P)|", "grad f(P) . u for any unit vector u", "Zero", "f(P)"],
                    correct_answer="|grad f(P)|",
                    explanation="Taking u along the gradient gives D_u f = |grad f| cos(0) = |grad f|, the "
                                "length of the gradient vector.",
                ),
                QuizQuestion(
                    question="At a point where the gradient is nonzero, how is grad f oriented relative to "
                             "the level curve through that point?",
                    options=["Normal (perpendicular) to it", "Tangent to it", "Parallel to it",
                             "It is undefined on a level curve"],
                    correct_answer="Normal (perpendicular) to it",
                    explanation="Moving along a level curve leaves f unchanged, so the directional "
                                "derivative in that direction is zero and the gradient is perpendicular.",
                ),
            ],
            correct=[0, 1, 2],
        ),
        QuizAttempt(
            concept="Cylindrical and Spherical Coordinates", difficulty="hard", days_ago=5,
            questions=[
                QuizQuestion(
                    question="In spherical coordinates, what is the volume element dV?",
                    options=["rho^2 sin(phi) drho dphi dtheta", "rho sin(phi) drho dphi dtheta",
                             "rho^2 drho dphi dtheta", "r dr dtheta dz"],
                    correct_answer="rho^2 sin(phi) drho dphi dtheta",
                    explanation="The Jacobian of the spherical transformation is rho^2 sin(phi); dropping "
                                "the sin(phi) is the most common error on this question.",
                ),
                QuizQuestion(
                    question="In cylindrical coordinates, what is the volume element dV?",
                    options=["r dr dtheta dz", "dr dtheta dz", "r^2 dr dtheta dz",
                             "rho^2 sin(phi) drho dphi dtheta"],
                    correct_answer="r dr dtheta dz",
                    explanation="Cylindrical coordinates are polar coordinates in the xy-plane with z left "
                                "alone, so the polar factor r carries straight over.",
                ),
                QuizQuestion(
                    question="With phi measured from the positive z-axis, which spherical conversion is "
                             "correct?",
                    options=["z = rho cos(phi)", "z = rho sin(phi)", "z = rho sin(phi) cos(theta)",
                             "z = rho cos(theta)"],
                    correct_answer="z = rho cos(phi)",
                    explanation="Because phi is the angle down from the z-axis, the z-component is the "
                                "adjacent side, rho cos(phi). The sine of phi gives the distance to the "
                                "z-axis instead.",
                ),
                QuizQuestion(
                    question="Which cylindrical description matches the solid inside x^2 + y^2 = 4 between "
                             "z = 0 and z = 3?",
                    options=["0 <= r <= 2, 0 <= theta <= 2pi, 0 <= z <= 3",
                             "0 <= r <= 4, 0 <= theta <= 2pi, 0 <= z <= 3",
                             "0 <= r <= 2, 0 <= theta <= pi, 0 <= z <= 3",
                             "0 <= rho <= 2, 0 <= phi <= pi, 0 <= theta <= 2pi"],
                    correct_answer="0 <= r <= 2, 0 <= theta <= 2pi, 0 <= z <= 3",
                    explanation="x^2 + y^2 = 4 means r^2 = 4, so the radius is 2, not 4; a full cylinder "
                                "also needs theta to sweep all the way to 2pi.",
                ),
            ],
            correct=[1],
        ),
    ],
    session=TutorSession(
        name="Why the gradient is perpendicular to level curves",
        topic="The Gradient",
        mode="socratic",
        summary_bullets=[
            "Derived D_u f = |grad f| cos(theta) and read all three special directions off it.",
            "Connected a zero directional derivative along a level curve to perpendicularity.",
            "Caught the habit of dotting with a non-unit vector, which cost points on Quiz 2.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I can compute gradients fine but I don't get why the gradient is always perpendicular to "
                "the level curve. It feels like a fact I'm supposed to memorize."
            )),
            ChatMessage(role="assistant", content=(
                "Then let's not memorize it. Start from the directional derivative: D_u f = grad f . u, "
                "with u a unit vector. Write that dot product using the angle theta between grad f and u. "
                "What do you get?"
            )),
            ChatMessage(role="user", content=(
                "D_u f = |grad f| |u| cos(theta), and |u| = 1, so it's just |grad f| cos(theta)."
            )),
            ChatMessage(role="assistant", content=(
                "Good — and notice everything now hinges on theta, because |grad f| is fixed once you fix "
                "the point. Now: a level curve is where f stays constant. If you walk along one, what is "
                "the rate of change of f in that direction?"
            )),
            ChatMessage(role="user", content=(
                "Zero, because f isn't changing. So |grad f| cos(theta) = 0, and since |grad f| isn't "
                "zero, cos(theta) has to be zero, so theta is 90 degrees."
            )),
            ChatMessage(role="assistant", content=(
                "That is the whole proof, and you just did it. The gradient is perpendicular to the level "
                "curve because the level curve is exactly the direction in which f does not change. The "
                "same formula hands you the other two cases free: theta = 0 is steepest ascent at rate "
                "|grad f|, theta = 180 degrees is steepest descent."
            )),
            ChatMessage(role="user", content=(
                "That also explains my Quiz 2 mistake — I dotted with <3, 4> instead of <3/5, 4/5>, so my "
                "answer came out 5 times too big."
            )),
            ChatMessage(role="assistant", content=(
                "Exactly, and now you know why normalising is not a formality: the cos(theta) reading of "
                "the dot product only holds when |u| = 1. Here is a cheap check — if a directional "
                "derivative ever comes out larger than |grad f|, you forgot to normalise."
            )),
        ],
    ),
)


# ---------------------------------------------------------------------------
# ENG EK 131 — Introduction to Engineering: Hands On
# ---------------------------------------------------------------------------

EK131 = Course(
    code="ENG EK 131",
    name="Introduction to Engineering: Hands On",
    department="Engineering Core",
    credits=2,
    nickname="Hands On",
    color="#0EA5E9",
    concepts=[
        Concept(name="3D Visualization and CAD", mastery=0.9,
                description="Reading and producing solid models: sketch-then-extrude workflow, datum "
                            "planes, revolves and fillets, and exporting a watertight mesh for printing."),
        Concept(name="Breadboarding and Circuit Wiring", mastery=0.84,
                description="Laying a circuit out on a solderless breadboard: which holes are tied "
                            "together, the power rails, and translating a schematic into wired hardware."),
        Concept(name="Shop Safety and Hand Tools", mastery=0.8,
                description="Eye protection, securing work, and the correct use of the drill press, band "
                            "saw, files and calipers before any machine is switched on."),
        Concept(name="Prototyping and Fabrication", mastery=0.68,
                description="Turning a model into a physical part with the laser cutter and 3D printer, "
                            "and choosing stock, material and process for the job at hand."),
        Concept(name="Instrumentation and Measurement", mastery=0.6,
                description="Using a digital multimeter and calipers correctly: voltage in parallel, "
                            "current in series, zeroing an instrument, and recording units and precision."),
        Concept(name="Structural Design and Load Paths", mastery=0.5,
                description="Tracing how a load travels from where it is applied to where it is reacted, "
                            "and the stiffness difference between a triangulated frame and a square one."),
        Concept(name="Design Documentation", mastery=0.36,
                description="Keeping a dated engineering notebook: labelled sketches, dimensions, the "
                            "reason for each change, and test results another student could reproduce."),
        Concept(name="Tolerances and Fit", mastery=0.24,
                description="Nominal size versus tolerance band, clearance against interference (press) "
                            "fits, and allowing for the shrinkage a printed or cut part actually shows."),
        Concept(name="Team Design Process", mastery=0.14,
                description="Dividing a device into subsystems, agreeing on interfaces early, and running "
                            "a design review that produces decisions rather than status updates."),
        Concept(name="Subsystem Integration", mastery=0.05,
                description="Assembling independently built substructures into one functional device, "
                            "where mismatched interfaces and stacked tolerances surface for the first "
                            "time."),
    ],
    edges=[
        Edge(source="3D Visualization and CAD", target="Prototyping and Fabrication",
             relationship="prerequisite", strength=0.85),
        Edge(source="Shop Safety and Hand Tools", target="Prototyping and Fabrication",
             relationship="prerequisite", strength=0.9),
        Edge(source="Breadboarding and Circuit Wiring", target="Instrumentation and Measurement",
             relationship="prerequisite", strength=0.8),
        Edge(source="3D Visualization and CAD", target="Tolerances and Fit",
             relationship="prerequisite", strength=0.7),
        Edge(source="Prototyping and Fabrication", target="Subsystem Integration",
             relationship="prerequisite", strength=0.8),
        Edge(source="Structural Design and Load Paths", target="Subsystem Integration",
             relationship="builds_on", strength=0.75),
        Edge(source="Tolerances and Fit", target="Subsystem Integration",
             relationship="prerequisite", strength=0.65),
        Edge(source="Design Documentation", target="Team Design Process",
             relationship="related", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="3D Visualization and CAD", delta=0.1, reason="CAD check-off passed first try"),
        MasteryEvent(concept="Instrumentation and Measurement", delta=0.08,
                     reason="Multimeter lab written up cleanly"),
        MasteryEvent(concept="Tolerances and Fit", delta=-0.07, reason="Press-fit hole printed undersized"),
    ],
    categories=[
        Category(name="Studio Check-offs", weight=0.4),
        Category(name="Design Notebook", weight=0.2),
        Category(name="Final Device", weight=0.4),
    ],
    assignments=[
        Assignment(title="Check-off 1: CAD Model of the Base Plate", category="Studio Check-offs",
                   type="project", due_offset_days=14, points_possible=20, points_earned=20),
        Assignment(title="Check-off 2: Wire and Test an LED Driver Circuit", category="Studio Check-offs",
                   type="project", due_offset_days=28, points_possible=20, points_earned=19),
        Assignment(title="Notebook Review 1", category="Design Notebook", type="homework",
                   due_offset_days=35, points_possible=15, points_earned=11),
        Assignment(title="Midterm Design Review", category="Studio Check-offs", type="exam",
                   due_offset_days=49, points_possible=50, points_earned=44, is_midterm=True),
        Assignment(title="Check-off 3: 3D-Printed Bracket with a Press Fit", category="Studio Check-offs",
                   type="project", due_offset_days=70, points_possible=20),
        Assignment(title="Notebook Review 2", category="Design Notebook", type="homework",
                   due_offset_days=84, points_possible=15),
        Assignment(title="Final Device: Integration and Demo", category="Final Device", type="project",
                   due_offset_days=98, points_possible=100),
    ],
    notes=[
        Note(
            title="Breadboard rails, and why my LED circuit didn't light",
            tags=["breadboard", "circuits", "checkoff2"],
            concepts=["Breadboarding and Circuit Wiring", "Instrumentation and Measurement"],
            body=(
                "Lost twenty minutes of studio on a circuit that was wired exactly right except for one "
                "thing. Writing down the layout so I stop guessing.\n\n"
                "## What is connected to what\n"
                "- The long strips along the top and bottom edges are the POWER RAILS. Each rail is one "
                "continuous node running the length of the board.\n"
                "- In the middle, groups of five holes on the same side of the center channel are tied "
                "together. The channel itself breaks the connection, which is the whole point — a DIP "
                "chip straddles it so each pin lands on its own node.\n"
                "- Nothing crosses the channel on its own. If you want it crossed, you wire it.\n\n"
                "## My actual bug\n"
                "The rails on this board are SPLIT in the middle — there is a tiny break in the red and "
                "blue lines halfway along. I had the supply on the left half and the LED on the right "
                "half, so the right half of the rail was floating. The fix is a jumper bridging the two "
                "halves, which is why every finished board in the room had those two short wires.\n\n"
                "## Sizing the series resistor\n"
                "An LED needs a resistor or it draws current until it dies.\n"
                "```\n"
                "R = (V_supply - V_forward) / I_target\n"
                "R = (5 V - 2 V) / 0.020 A = 150 ohms\n"
                "```\n"
                "Red LEDs drop about 2 V; blue and white are closer to 3 V, so the same 150 ohms gives a "
                "dimmer result there. Nearest standard value above the computed one is the safe pick.\n\n"
                "## Multimeter, from the TA\n"
                "Voltage is measured ACROSS a component, so the meter goes in parallel. Current goes "
                "THROUGH it, so the meter goes in series and the circuit has to be broken to insert it. "
                "Leaving the leads in the current jacks and then probing a voltage is how you blow the "
                "meter's fuse — the jacks are a near short."
            ),
        ),
        Note(
            title="Press fits, clearance, and printer shrinkage",
            tags=["tolerances", "3d printing", "checkoff3"],
            concepts=["Tolerances and Fit", "Prototyping and Fabrication"],
            body=(
                "Check-off 3 printed fine and then would not go together. The CAD was right; my "
                "understanding of what the printer would do with it was wrong.\n\n"
                "## Two kinds of fit\n"
                "- **Clearance fit** — hole bigger than shaft, parts slide. Use for anything that moves "
                "or that has to be assembled by hand.\n"
                "- **Interference (press) fit** — shaft slightly BIGGER than the hole, held by friction. "
                "Use for a bearing or a dowel pin that must not move.\n\n"
                "The mistake was modelling a 6.00 mm hole for a 6.00 mm rod and expecting it to slide. "
                "Same number means no fit at all.\n\n"
                "## What the printer actually does\n"
                "Holes come out UNDERSIZED on this printer, by roughly 0.2 mm on diameter. Two reasons "
                "the TA gave: the plastic shrinks as it cools, and the nozzle cuts the corner slightly on "
                "a concave curve, so the inside of a hole creeps inward.\n\n"
                "Working numbers from the test coupon I printed:\n"
                "```\n"
                "modelled 6.0 mm  ->  measured 5.79 mm\n"
                "modelled 6.2 mm  ->  measured 6.02 mm   slides, slight friction\n"
                "modelled 6.4 mm  ->  measured 6.21 mm   free sliding fit\n"
                "```\n"
                "So: for a sliding fit on a 6 mm rod, model 6.3-6.4 mm. For a press fit, model about "
                "6.1 mm and expect to need the arbor press.\n\n"
                "## Reading a tolerance\n"
                "`10.0 +/- 0.1 mm` means anything from 9.9 to 10.1 mm is an acceptable part. The notebook "
                "should record the measured value, not the modelled one — that is the half I keep losing "
                "notebook points on."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ek131-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for ENG EK 131 Introduction to Engineering: Hands On — a two-credit studio "
                    "of weekly check-offs, an engineering notebook, and a team-built final device.",
            concept_notes=[
                ConceptNote(name="Shop Safety and Hand Tools",
                            description="Week 1 and a prerequisite for every later studio."),
                ConceptNote(name="3D Visualization and CAD", description="Weeks 2-3, before any printing."),
                ConceptNote(name="Breadboarding and Circuit Wiring",
                            description="Weeks 5-6, the electrical half of the course."),
                ConceptNote(name="Subsystem Integration",
                            description="Weeks 12-14, where the team substructures become one device."),
            ],
            extracted_text=(
                "ENG EK 131 Introduction to Engineering: Hands On\n"
                "Boston University College of Engineering — 2 units\n"
                "Section A1, EPC 102, Mondays 10:10-11:55.\n\n"
                "Course Description: This course introduces freshmen to a set of design-oriented "
                "engineering skills through a hands-on experience using engineering tools (software and "
                "hardware) for design and prototyping. Students will be exposed to a number of mechanical "
                "and electrical engineering tools applicable to 3D visualization, building structures, "
                "designing and wiring circuits, prototyping and instrumentation. Students will work "
                "individually and in teams to build substructures that can be integrated into a "
                "functional device (final product).\n\n"
                "Format: this is a studio course. There is no lecture and no written final exam. Each "
                "session is spent at the bench, and credit for a skill is earned by demonstrating it to a "
                "staff member at a check-off.\n\n"
                "Grading\n"
                "  Studio check-offs       40%\n"
                "  Engineering notebook    20%\n"
                "  Final device and demo   40%\n\n"
                "Safety: closed-toe shoes and eye protection are required in the shop at all times. A "
                "student who has not completed the week 1 safety check-off may not operate any machine.\n\n"
                "Notebook policy: entries are dated, written in ink, and made as the work happens rather "
                "than afterwards. A good entry lets another student repeat what you did and get the same "
                "result. Measured values are recorded alongside the intended ones.\n\n"
                "Schedule\n"
                "  1      Shop safety, hand tools, calipers; safety check-off\n"
                "  2-3    Solid modelling: sketch, extrude, revolve, fillet; exporting for print\n"
                "  4      Laser cutter and 3D printer workflow; CHECK-OFF 1\n"
                "  5-6    Schematics, breadboards, resistors and LEDs; CHECK-OFF 2\n"
                "  7      Multimeters and measurement practice; notebook review\n"
                "  8      MIDTERM DESIGN REVIEW: subsystem proposal and interface drawing\n"
                "  9-10   Structures, load paths and triangulation\n"
                "  11     Tolerances, clearance and press fits; CHECK-OFF 3\n"
                "  12-14  Team integration of substructures; final device demo\n"
            ),
        ),
        Document(
            file_name="ek131-studio5-circuit-handout.pdf",
            category="lecture_notes",
            summary="Studio handout for the breadboard session: board topology, reading a schematic, "
                    "sizing an LED series resistor, and safe multimeter technique.",
            concept_notes=[
                ConceptNote(name="Breadboarding and Circuit Wiring",
                            description="Board topology and schematic-to-hardware translation."),
                ConceptNote(name="Instrumentation and Measurement",
                            description="Meter in parallel for volts, in series for amps."),
            ],
            extracted_text=(
                "EK 131 Studio 5: Circuits on a Solderless Breadboard\n\n"
                "Board topology. The two long strips at each edge are power rails, each a single "
                "electrical node. On many boards, including the ones in EPC 102, each rail is split at "
                "the midpoint: check for the break in the printed line and bridge it with a jumper if "
                "you need the whole length. In the field of the board, groups of five holes on the same "
                "side of the center channel are connected together. The channel breaks the connection so "
                "that a dual-in-line package can straddle it with each pin on its own node.\n\n"
                "From schematic to board. A schematic shows connectivity, not position. Two points joined "
                "by a line in the schematic must end up on the same node of the board; where you place "
                "them is up to you. Build the power connections first, then work left to right through "
                "the signal path.\n\n"
                "Sizing a series resistor. An LED is a diode: above its forward voltage, current rises "
                "very steeply, so it must never be connected directly across a supply. Choose the "
                "resistor from the voltage left over after the LED's drop:\n"
                "  R = (V_supply - V_forward) / I_target\n"
                "For a red LED on 5 V at 20 mA: R = (5 - 2)/0.020 = 150 ohms. Round up to the nearest "
                "standard value. Typical forward drops: red about 2.0 V, green about 2.2 V, blue and "
                "white about 3.0 V.\n\n"
                "Resistor color code. The first two bands are digits, the third is the number of zeros. "
                "Brown-black-red is 1, 0, then two zeros: 1000 ohms, or 1 k. The fourth band is "
                "tolerance: gold is 5 percent.\n\n"
                "Multimeter technique. Voltage is a difference between two points, so the meter goes in "
                "PARALLEL, across the component. Current flows through, so the meter goes in SERIES and "
                "you must break the circuit to insert it. The current jacks are close to a short circuit: "
                "probing a voltage with the leads still in them blows the meter's fuse. Return the leads "
                "to the voltage jacks as soon as a current measurement is finished.\n"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="On a solderless breadboard, which holes are connected?",
                  back="Groups of five holes on the same side of the center channel share a node; the "
                       "edge rails are each one long node. Nothing crosses the channel unless you wire it."),
        Flashcard(front="Series resistor for an LED",
                  back="R = (V_supply - V_forward) / I_target. Red LED on 5 V at 20 mA: "
                       "(5 - 2)/0.020 = 150 ohms."),
        Flashcard(front="Measuring voltage vs current with a multimeter",
                  back="Voltage: meter in PARALLEL, across the component. Current: meter in SERIES, "
                       "circuit broken to insert it."),
        Flashcard(front="Resistor bands brown-black-red",
                  back="1, 0, then two zeros = 1000 ohms (1 k). First two bands are digits, the third is "
                       "the multiplier."),
        Flashcard(front="Clearance fit vs interference (press) fit",
                  back="Clearance: hole larger than shaft, parts slide. Interference: shaft slightly "
                       "larger than the hole, held by friction."),
        Flashcard(front="Why do printed holes come out undersized?",
                  back="The plastic shrinks as it cools and the nozzle cuts inside corners, so model a "
                       "hole roughly 0.2-0.4 mm oversize for a sliding fit."),
        Flashcard(front="What does 10.0 +/- 0.1 mm mean?",
                  back="Any part measuring between 9.9 and 10.1 mm is acceptable. 10.0 is the nominal "
                       "size; 0.1 is the tolerance band."),
        Flashcard(front="Why triangulate a frame?",
                  back="A triangle cannot change shape without changing a member's length, so a "
                       "triangulated frame carries load axially instead of bending at the joints."),
        Flashcard(front="What is a load path?",
                  back="The route a force takes from where it is applied to where it is reacted. Every "
                       "member on that route carries load; members off it are carrying nothing."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The Midterm Design Review is not a written exam — it is a fifteen-minute bench presentation "
            "of your subsystem to the staff. You bring the CAD model, a dimensioned interface drawing, a "
            "working breadboard demonstration of its electrical half, and the notebook pages that show "
            "how you got there. Points come off for interfaces that are not dimensioned and for notebook "
            "entries written after the fact."
        ),
        topics=[
            StudyGuideTopic(
                name="The CAD model and its interfaces",
                importance="The heaviest single item. Every face where your subsystem meets someone "
                           "else's must carry a dimension and a tolerance, not just a shape.",
                concepts=["3D Visualization and CAD", "Tolerances and Fit"],
            ),
            StudyGuideTopic(
                name="Live circuit demonstration",
                importance="You wire it at the bench while they watch. Know your board's rail splits and "
                           "be able to justify the series resistor value out loud.",
                concepts=["Breadboarding and Circuit Wiring", "Instrumentation and Measurement"],
            ),
            StudyGuideTopic(
                name="Load path of the structure",
                importance="Expect to be asked where the force goes. Trace it from the applied load to "
                           "the mounting points, naming the members that carry it.",
                concepts=["Structural Design and Load Paths"],
            ),
            StudyGuideTopic(
                name="Notebook evidence",
                importance="Dated entries, measured values beside intended ones, and a written reason for "
                           "each design change. This is where the easy points were lost last review.",
                concepts=["Design Documentation", "Team Design Process"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Breadboarding and Circuit Wiring", difficulty="easy", days_ago=19,
            questions=[
                QuizQuestion(
                    question="On a standard solderless breadboard, which holes are electrically connected "
                             "to each other?",
                    options=["Groups of five holes on the same side of the center channel",
                             "All holes in a line straight across the center channel",
                             "Every hole in the same row across the entire board",
                             "Only the two outer power rails"],
                    correct_answer="Groups of five holes on the same side of the center channel",
                    explanation="The center channel breaks the connection so a DIP package can straddle "
                                "it with every pin on its own node; the five-hole groups either side are "
                                "the terminal strips.",
                ),
                QuizQuestion(
                    question="A red LED with a 2 V forward drop is run from a 5 V supply at 20 mA. What "
                             "series resistor is required?",
                    options=["150 ohms", "250 ohms", "100 ohms", "350 ohms"],
                    correct_answer="150 ohms",
                    explanation="The resistor drops the leftover voltage: (5 - 2) V / 0.020 A = 150 ohms.",
                ),
                QuizQuestion(
                    question="A resistor is banded brown, black, red. What is its nominal resistance?",
                    options=["1 kilohm", "10 kilohms", "100 ohms", "12 ohms"],
                    correct_answer="1 kilohm",
                    explanation="Brown is 1 and black is 0, giving 10; red as the multiplier adds two "
                                "zeros, so 1000 ohms.",
                ),
                QuizQuestion(
                    question="To measure the current flowing through a component, how must the multimeter "
                             "be connected?",
                    options=["In series with the component, breaking the circuit to insert it",
                             "In parallel with the component",
                             "Across the power supply terminals",
                             "Between ground and the component's case"],
                    correct_answer="In series with the component, breaking the circuit to insert it",
                    explanation="Current must flow through the meter to be measured. Voltage, being a "
                                "difference between two points, is the one measured in parallel.",
                ),
            ],
            correct=[0, 1, 2, 3],
        ),
        QuizAttempt(
            concept="Tolerances and Fit", difficulty="medium", days_ago=4,
            questions=[
                QuizQuestion(
                    question="In an interference (press) fit, how do the shaft and hole compare?",
                    options=["The shaft is slightly larger than the hole",
                             "The shaft is slightly smaller than the hole",
                             "They are exactly the same size",
                             "Either, because adhesive does the holding"],
                    correct_answer="The shaft is slightly larger than the hole",
                    explanation="The oversize is what creates the friction that holds the parts; the "
                                "assembly needs a press or a thermal trick to go together.",
                ),
                QuizQuestion(
                    question="Why do holes printed on an FDM 3D printer usually measure undersized?",
                    options=["The plastic shrinks as it cools and the nozzle cuts inside corners",
                             "The slicer deliberately adds a safety margin to every hole",
                             "Infill material expands into the opening",
                             "The build plate is not level"],
                    correct_answer="The plastic shrinks as it cools and the nozzle cuts inside corners",
                    explanation="Both effects pull material inward on a concave curve, so a modelled "
                                "hole comes out a few tenths of a millimetre small.",
                ),
                QuizQuestion(
                    question="A printed bracket must slide freely over a 6.0 mm rod. Which modelled hole "
                             "diameter is the best starting point?",
                    options=["6.3 mm", "6.0 mm", "5.8 mm", "7.5 mm"],
                    correct_answer="6.3 mm",
                    explanation="Allowing roughly 0.2-0.3 mm for shrinkage lands near 6.0 mm actual, "
                                "which slides. Modelling 6.0 mm prints tight and 5.8 mm will not go on.",
                ),
                QuizQuestion(
                    question="A drawing calls out 10.0 +/- 0.1 mm. Which parts are acceptable?",
                    options=["Any measuring between 9.9 and 10.1 mm",
                             "Only those measuring exactly 10.0 mm",
                             "Any measuring between 10.0 and 10.1 mm",
                             "Any measuring between 9.0 and 11.0 mm"],
                    correct_answer="Any measuring between 9.9 and 10.1 mm",
                    explanation="The tolerance is a symmetric band about the nominal size, so it runs one "
                                "tenth of a millimetre either side of 10.0.",
                ),
            ],
            correct=[0, 3],
        ),
    ],
    session=TutorSession(
        name="Where does the load actually go?",
        topic="Structural Design and Load Paths",
        mode="socratic",
        summary_bullets=[
            "Traced the load from the demo mass through the arm to the two base mounting points.",
            "Found the square bay that was bending at the joints, and triangulated it with one member.",
            "Noticed that two members were on no load path at all and could be deleted.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "My team's frame holds the 2 kg demo mass but it sags a lot and wobbles. We were going to "
                "just print everything thicker. Is that the right fix?"
            )),
            ChatMessage(role="assistant", content=(
                "Maybe, but thicker everywhere is expensive in print time and mass, and it treats every "
                "member as equally guilty. Before changing anything: start at the mass and tell me which "
                "members the force passes through on its way to the base mounting points."
            )),
            ChatMessage(role="user", content=(
                "It hangs off the end of the arm, so the arm, then the vertical post, then into the base "
                "plate at the two bolts. The two diagonal pieces at the back aren't really in the way of "
                "that."
            )),
            ChatMessage(role="assistant", content=(
                "Then those two diagonals are carrying nothing, and thickening them buys you nothing. "
                "Now look at the arm-to-post joint. Is that corner part of a triangle, or part of a "
                "four-sided bay?"
            )),
            ChatMessage(role="user", content=(
                "It's a square bay. Four members, four corners. So it can collapse into a parallelogram — "
                "that's probably the wobble."
            )),
            ChatMessage(role="assistant", content=(
                "That is exactly the wobble. A four-bar shape changes form with no member changing "
                "length, so all the resistance has to come from the stiffness of the joints themselves, "
                "which on printed parts is very little. What single part would stop the shape changing?"
            )),
            ChatMessage(role="user", content=(
                "A diagonal across that bay — then it would have to stretch or compress for the shape to "
                "move. So one brace in the right place instead of thickening six members."
            )),
            ChatMessage(role="assistant", content=(
                "Right, and now the load path runs axially through that brace instead of bending the "
                "joints, which is the stiffest thing a slender member can do. For the review, bring the "
                "before-and-after sag measurement — a number from the calipers will make the argument for "
                "you faster than the drawing will."
            )),
        ],
    ),
)


# ---------------------------------------------------------------------------
# CAS CH 131 — General Chemistry for the Engineering Sciences
# ---------------------------------------------------------------------------

CH131 = Course(
    code="CAS CH 131",
    name="General Chemistry for the Engineering Sciences",
    department="Chemistry",
    credits=4,
    nickname="Gen Chem",
    color="#059669",
    concepts=[
        Concept(name="Stoichiometry", mastery=0.88,
                description="Moles as the bridge between mass and particles, balancing equations, "
                            "limiting reagents, and percent yield in a real reaction."),
        Concept(name="Atomic and Molecular Structure", mastery=0.81,
                description="Electron configurations and orbitals, periodic trends in size and "
                            "electronegativity, Lewis structures and VSEPR shapes."),
        Concept(name="Theories of Bonding", mastery=0.76,
                description="Ionic, covalent and metallic bonding, bond polarity, and the valence-bond "
                            "and molecular-orbital pictures of why a bond forms at all."),
        Concept(name="Gases, Liquids and Solids", mastery=0.64,
                description="The ideal gas law and when it fails, intermolecular forces, phase diagrams, "
                            "and the lattice types that give a solid its properties."),
        Concept(name="Properties of Solutions", mastery=0.57,
                description="Molarity and dilution, solubility and the like-dissolves-like rule, and "
                            "colligative properties such as boiling-point elevation."),
        Concept(name="Titrations and Lab Technique", mastery=0.49,
                description="Standardising a solution, reading a burette, finding an equivalence point "
                            "with an indicator or a pH meter, and reporting a result with its uncertainty."),
        Concept(name="Chemical Equilibrium", mastery=0.34,
                description="The equilibrium constant and reaction quotient, ICE tables, and Le "
                            "Chatelier's principle for predicting the direction of a shift."),
        Concept(name="Acids and Bases", mastery=0.28,
                description="Strong versus weak acids, pH and pOH, Ka and Kb, buffers, and the "
                            "Henderson-Hasselbalch equation for a conjugate pair."),
        Concept(name="Chemical Thermodynamics", mastery=0.17,
                description="Enthalpy, entropy and Gibbs free energy, Hess's law, and what the sign of "
                            "delta G says about whether a reaction is spontaneous."),
        Concept(name="Electrochemistry", mastery=0.06,
                description="Oxidation and reduction half-reactions, galvanic cells and cell potential, "
                            "the Nernst equation, and the link between cell potential and free energy."),
    ],
    edges=[
        Edge(source="Atomic and Molecular Structure", target="Theories of Bonding",
             relationship="prerequisite", strength=0.9),
        Edge(source="Theories of Bonding", target="Gases, Liquids and Solids",
             relationship="prerequisite", strength=0.75),
        Edge(source="Stoichiometry", target="Properties of Solutions",
             relationship="prerequisite", strength=0.8),
        Edge(source="Stoichiometry", target="Titrations and Lab Technique",
             relationship="prerequisite", strength=0.85),
        Edge(source="Chemical Equilibrium", target="Acids and Bases",
             relationship="prerequisite", strength=0.9),
        Edge(source="Acids and Bases", target="Titrations and Lab Technique",
             relationship="related", strength=0.7),
        Edge(source="Chemical Thermodynamics", target="Chemical Equilibrium",
             relationship="prerequisite", strength=0.8),
        Edge(source="Chemical Thermodynamics", target="Electrochemistry",
             relationship="prerequisite", strength=0.75),
        Edge(source="Chemical Equilibrium", target="Electrochemistry",
             relationship="builds_on", strength=0.6),
    ],
    mastery_events=[
        MasteryEvent(concept="Stoichiometry", delta=0.1, reason="Limiting-reagent set full marks"),
        MasteryEvent(concept="Titrations and Lab Technique", delta=0.07,
                     reason="Lab 5 result within tolerance"),
        MasteryEvent(concept="Chemical Equilibrium", delta=-0.08, reason="ICE table wrong on Exam 2"),
        MasteryEvent(concept="Acids and Bases", delta=-0.05, reason="Confused Ka with pKa on the quiz"),
    ],
    categories=[
        Category(name="Lecture Exams", weight=0.45),
        Category(name="Problem Sets", weight=0.15, drop_lowest=1),
        Category(name="Laboratory", weight=0.25),
        Category(name="Final Exam", weight=0.15),
    ],
    assignments=[
        Assignment(title="Problem Set 2: Stoichiometry and Limiting Reagents", category="Problem Sets",
                   type="homework", due_offset_days=16, points_possible=30, points_earned=29),
        Assignment(title="Lab 2: Solution Preparation and Dilution", category="Laboratory",
                   type="project", due_offset_days=23, points_possible=25, points_earned=23),
        Assignment(title="Lecture Exam 1", category="Lecture Exams", type="exam",
                   due_offset_days=37, points_possible=100, points_earned=86, is_midterm=True),
        Assignment(title="Problem Set 5: Gas Laws and Intermolecular Forces", category="Problem Sets",
                   type="homework", due_offset_days=51, points_possible=30, points_earned=25),
        Assignment(title="Lab 5: Acid-Base Titration", category="Laboratory", type="project",
                   due_offset_days=65, points_possible=25, points_earned=21),
        Assignment(title="Lecture Exam 2", category="Lecture Exams", type="exam",
                   due_offset_days=79, points_possible=100),
        Assignment(title="Lab 8: Electrochemical Cells and the Voltmeter", category="Laboratory",
                   type="project", due_offset_days=93, points_possible=25),
        Assignment(title="Final Exam", category="Final Exam", type="exam",
                   due_offset_days=108, points_possible=150),
    ],
    notes=[
        Note(
            title="ICE tables — the part I keep getting wrong",
            tags=["equilibrium", "ice table", "exam2"],
            concepts=["Chemical Equilibrium", "Acids and Bases"],
            body=(
                "I lost most of the equilibrium section on Exam 2 and it was the same error three times, "
                "so writing it out properly.\n\n"
                "## The table\n"
                "For `N2 + 3 H2 <-> 2 NH3`, starting from 1.00 M N2 and 2.00 M H2:\n"
                "```\n"
                "            N2        H2         NH3\n"
                "I         1.00      2.00        0\n"
                "C          -x       -3x        +2x\n"
                "E       1.00-x    2.00-3x       2x\n"
                "```\n\n"
                "**The error:** I wrote `-x`, `-x`, `+x`. The Change row is the ONLY row where the "
                "balanced coefficients appear, and they must appear. Three moles of hydrogen disappear "
                "for every mole of nitrogen, so it is `-3x`. Initial and Equilibrium rows are just "
                "concentrations and carry no coefficients.\n\n"
                "## Where the coefficients go in K\n"
                "They show up again as EXPONENTS, not multipliers:\n"
                "```\n"
                "K = [NH3]^2 / ( [N2] [H2]^3 )\n"
                "```\n"
                "Products over reactants, each raised to its coefficient. Pure solids and pure liquids "
                "are left out entirely — their concentration does not change.\n\n"
                "## Q vs K\n"
                "Same expression, but Q uses whatever concentrations you have right now.\n"
                "- Q < K: not enough product yet, shifts RIGHT\n"
                "- Q > K: too much product, shifts LEFT\n"
                "- Q = K: already at equilibrium\n\n"
                "## Le Chatelier, stated so I actually believe it\n"
                "Adding a reactant pushes toward products. Removing a product pulls toward products. "
                "Temperature is the different one: it is the only change that alters K itself. Treat heat "
                "as a product for an exothermic reaction, so heating an exothermic reaction shifts it "
                "LEFT and lowers K. Adding a catalyst changes nothing at equilibrium — it reaches the "
                "same place sooner."
            ),
        ),
        Note(
            title="Titration technique and where my Lab 5 error came from",
            tags=["lab", "titration", "uncertainty"],
            concepts=["Titrations and Lab Technique", "Properties of Solutions"],
            body=(
                "Lab 5 came in a few percent high and the TA's comment was that it was technique, not "
                "arithmetic. Working back through it.\n\n"
                "## The calculation\n"
                "At the equivalence point the moles of acid and base have reacted in the balanced ratio:\n"
                "```\n"
                "M_acid V_acid = M_base V_base      (for a 1:1 reaction)\n"
                "```\n"
                "For a diprotic acid it is NOT 1:1 — two moles of base per mole of acid — and that factor "
                "is the first thing to check before blaming the glassware.\n\n"
                "## The four technique errors on the handout\n"
                "1. **Air bubble in the burette tip.** It fills with titrant partway through, so the "
                "volume read off is larger than the volume delivered. Result reads HIGH. This is almost "
                "certainly mine; I did not run the tip through before starting.\n"
                "2. **Reading the meniscus from the wrong height.** Read at eye level, bottom of the "
                "meniscus. Parallax one way or the other.\n"
                "3. **Overshooting the endpoint.** The indicator should turn on a half drop and STAY. A "
                "faint pink that fades is not the endpoint yet; a strong pink has gone past it.\n"
                "4. **Rinsing the flask with distilled water.** This one is fine — extra water changes "
                "the concentration but not the moles of analyte, so the endpoint is unaffected. Rinsing "
                "the BURETTE with water is the one that ruins the run.\n\n"
                "## Reporting\n"
                "Three trials, report the mean and the standard deviation, and keep significant figures "
                "consistent with the burette's 0.05 mL precision. Dropping the uncertainty entirely cost "
                "two points even where the number was right."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="ch131-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for CAS CH 131 General Chemistry for the Engineering Sciences: a one-semester "
                    "terminal sequence with lecture, discussion, pre-lab and laboratory sections.",
            concept_notes=[
                ConceptNote(name="Stoichiometry", description="Weeks 1-2, assumed afterwards."),
                ConceptNote(name="Theories of Bonding", description="Weeks 4-5, before Lecture Exam 1."),
                ConceptNote(name="Chemical Equilibrium",
                            description="Weeks 9-10, the hinge of the second half."),
                ConceptNote(name="Electrochemistry",
                            description="Weeks 13-14, the last unit and the final lab."),
            ],
            extracted_text=(
                "CAS CH 131 General Chemistry for the Engineering Sciences\n"
                "Boston University, Department of Chemistry — 4 units\n"
                "Lecture A1, MOR 101, TR 9:30-10:45. Students registering for CAS CH 131 must register "
                "for four sections: lecture, discussion, laboratory and pre-lab.\n\n"
                "Corequisite: CAS MA 123.\n\n"
                "Course Description: A one-semester, terminal general chemistry course for engineering "
                "students who do not require a two-semester general chemistry sequence. Lecture topics "
                "include stoichiometry; atomic and molecular structure; theories of bonding; chemistry of "
                "the solid, liquid, and gaseous states; properties of solutions; chemical thermodynamics; "
                "equilibrium; acids and bases; electrochemistry. Laboratory includes training in basic "
                "laboratory techniques such as data collection and recording, statistical interpretation "
                "of data, solution preparation, titrations, conducting chemical reactions, use of "
                "spectrophotometers, pH and voltmeters. Carries natural science divisional credit (with "
                "lab) in CAS.\n\n"
                "Grading\n"
                "  Lecture Exam 1 and Lecture Exam 2   45%\n"
                "  Problem sets (lowest dropped)       15%\n"
                "  Laboratory and pre-lab              25%\n"
                "  Final Exam                          15%\n\n"
                "Laboratory policy: the pre-lab assignment must be submitted before the session begins, "
                "and a student who arrives without it is not admitted to the bench. Safety goggles are "
                "required at all times. A missed laboratory cannot be made up.\n\n"
                "Lecture schedule\n"
                "  1-2    Matter and measurement; stoichiometry, limiting reagents, percent yield\n"
                "  3      Aqueous reactions; molarity and dilution\n"
                "  4-5    Atomic structure, periodic trends, Lewis structures and VSEPR\n"
                "  6      Bonding theories: valence bond and molecular orbital\n"
                "  7      LECTURE EXAM 1 (weeks 1-6)\n"
                "  8      Gases and the ideal gas law; real-gas deviations\n"
                "  9      Intermolecular forces, liquids, solids and phase diagrams\n"
                "  10-11  Chemical equilibrium; the equilibrium constant and Le Chatelier's principle\n"
                "  12     Acids and bases; pH, weak-acid equilibria and buffers\n"
                "  13     LECTURE EXAM 2; thermodynamics: enthalpy, entropy and free energy\n"
                "  14     Electrochemistry: half-reactions, galvanic cells and the Nernst equation\n"
                "  15     Review and cumulative final exam\n"
            ),
        ),
        Document(
            file_name="ch131-lab5-titration-handout.pdf",
            category="reading",
            summary="Pre-lab reading for the acid-base titration: standardisation, burette technique, "
                    "identifying the equivalence point, and the statistical treatment of three trials.",
            concept_notes=[
                ConceptNote(name="Titrations and Lab Technique",
                            description="Burette handling and endpoint determination."),
                ConceptNote(name="Acids and Bases",
                            description="Why the equivalence point of a weak acid is above pH 7."),
                ConceptNote(name="Properties of Solutions",
                            description="Molarity, standardisation and dilution arithmetic."),
            ],
            extracted_text=(
                "CH 131 Laboratory 5: Acid-Base Titration\n\n"
                "Objective. Determine the concentration of an unknown acid by titration against a "
                "standardised sodium hydroxide solution, and report the result with an uncertainty "
                "derived from three independent trials.\n\n"
                "Standardisation. Sodium hydroxide absorbs water and carbon dioxide from the air, so its "
                "concentration cannot be trusted from the label. Standardise it first against a primary "
                "standard, potassium hydrogen phthalate, which is dry, pure and of accurately known molar "
                "mass. Every later calculation depends on this number.\n\n"
                "Burette technique. Rinse the burette with the titrant it will hold, never with distilled "
                "water: a water film dilutes the titrant and biases every reading. Run titrant through "
                "the tip until no air bubble remains below the stopcock; a bubble that fills during the "
                "titration makes the delivered volume smaller than the volume read, and the calculated "
                "concentration of the analyte comes out high. Read the bottom of the meniscus at eye "
                "level, estimating to 0.01 mL on a burette graduated in 0.05 mL.\n\n"
                "The equivalence point is where the moles of titrant added equal the moles of analyte "
                "present, in the ratio of the balanced equation. The endpoint is where the indicator "
                "changes, and a well-chosen indicator puts the two close together. For a strong acid "
                "titrated with a strong base the equivalence point is at pH 7; for a WEAK acid with a "
                "strong base it lies above pH 7, because the conjugate base left in solution is itself "
                "basic. Phenolphthalein, changing around pH 8.2, is the right choice for the weak-acid "
                "case and the wrong instinct to apply everywhere.\n\n"
                "Data treatment. Perform three trials. Report the mean concentration and the sample "
                "standard deviation; discard a trial only with a stated statistical reason, and record "
                "that you did so. A result quoted without an uncertainty is incomplete and will not "
                "receive full credit.\n"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="How do you find the limiting reagent?",
                  back="Convert each reactant to moles, divide by its coefficient, and the smallest "
                       "quotient is the limiting reagent. Comparing raw masses is the classic trap."),
        Flashcard(front="Equilibrium constant for N2 + 3 H2 <-> 2 NH3",
                  back="K = [NH3]^2 / ([N2][H2]^3). Products over reactants, each raised to its "
                       "coefficient; pure solids and liquids are omitted."),
        Flashcard(front="Where do stoichiometric coefficients appear in an ICE table?",
                  back="Only in the Change row, as multipliers of x (-x, -3x, +2x). The Initial and "
                       "Equilibrium rows carry plain concentrations."),
        Flashcard(front="Q versus K",
                  back="Q uses current concentrations in the K expression. Q < K shifts right, Q > K "
                       "shifts left, Q = K means equilibrium."),
        Flashcard(front="What is the only change that alters K itself?",
                  back="Temperature. Concentration and pressure changes shift the position of "
                       "equilibrium; a catalyst only changes how fast it is reached."),
        Flashcard(front="pH of 0.010 M HCl",
                  back="HCl is a strong acid, so [H+] = 0.010 M and pH = -log(0.010) = 2.00."),
        Flashcard(front="Henderson-Hasselbalch equation",
                  back="pH = pKa + log([A-]/[HA]). When the conjugate base and weak acid are equal in "
                       "concentration, pH = pKa."),
        Flashcard(front="Sign of delta G and spontaneity",
                  back="delta G = delta H - T delta S. Negative delta G means spontaneous as written; "
                       "zero means the system is at equilibrium."),
        Flashcard(front="Oxidation versus reduction",
                  back="Oxidation is loss of electrons and happens at the anode; reduction is gain of "
                       "electrons and happens at the cathode."),
        Flashcard(front="Why rinse a burette with titrant, not water?",
                  back="A film of distilled water dilutes the titrant, so every delivered volume is "
                       "weaker than assumed. Rinsing the flask with water is harmless by comparison."),
    ],
    study_guide=StudyGuide(
        overview=(
            "Lecture Exam 1 covers weeks 1-6: stoichiometry, aqueous reactions and solution "
            "concentration, atomic structure and periodic trends, Lewis structures and VSEPR, and the "
            "bonding theories. Equilibrium and thermodynamics are NOT on this exam. A periodic table is "
            "provided; a formula sheet is not. The front half of the exam is calculation and is where "
            "the reliable points are."
        ),
        topics=[
            StudyGuideTopic(
                name="Stoichiometry and limiting reagents",
                importance="Roughly a quarter of the exam and the most mechanical part of it. Divide "
                           "moles by coefficient to find the limiting reagent rather than comparing "
                           "masses.",
                concepts=["Stoichiometry"],
            ),
            StudyGuideTopic(
                name="Solution concentration and dilution",
                importance="Short calculation questions, and the same arithmetic the titration lab "
                           "depends on. Know molarity and the dilution relation cold.",
                concepts=["Properties of Solutions", "Titrations and Lab Technique"],
            ),
            StudyGuideTopic(
                name="Atomic structure and periodic trends",
                importance="Conceptual multiple choice. Be able to justify a trend in atomic radius or "
                           "electronegativity, not just recite its direction.",
                concepts=["Atomic and Molecular Structure"],
            ),
            StudyGuideTopic(
                name="Lewis structures, VSEPR and bonding",
                importance="The long-form question at the end: draw the structure, count electron "
                           "domains, name the shape, then decide polarity from the shape and the bonds.",
                concepts=["Theories of Bonding", "Atomic and Molecular Structure"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Stoichiometry", difficulty="easy", days_ago=26,
            questions=[
                QuizQuestion(
                    question="How many moles are in 36.0 g of water, given a molar mass of 18.0 g/mol?",
                    options=["2.00 mol", "1.00 mol", "0.500 mol", "18.0 mol"],
                    correct_answer="2.00 mol",
                    explanation="Moles are mass divided by molar mass: 36.0 g / 18.0 g per mol = 2.00 mol.",
                ),
                QuizQuestion(
                    question="For 2 H2 + O2 -> 2 H2O, 4.0 mol of hydrogen is mixed with 1.0 mol of "
                             "oxygen. Which reactant is limiting?",
                    options=["Oxygen, because it runs out first",
                             "Hydrogen, because there is more of it",
                             "Neither; the mixture is exactly stoichiometric",
                             "Water, because it is the product"],
                    correct_answer="Oxygen, because it runs out first",
                    explanation="Dividing by coefficients gives 4.0/2 = 2.0 for hydrogen and 1.0/1 = 1.0 "
                                "for oxygen. The smaller quotient is the limiting reagent.",
                ),
                QuizQuestion(
                    question="In that same reaction, how much water can form?",
                    options=["2.0 mol", "4.0 mol", "1.0 mol", "3.0 mol"],
                    correct_answer="2.0 mol",
                    explanation="Yield is set by the limiting reagent: 1.0 mol of oxygen produces 2.0 mol "
                                "of water by the 1:2 ratio in the balanced equation.",
                ),
                QuizQuestion(
                    question="The coefficients in a balanced chemical equation give the ratio of what?",
                    options=["Moles of each species", "Masses of each species",
                             "Volumes of each solid", "Densities of each species"],
                    correct_answer="Moles of each species",
                    explanation="Balancing conserves atoms, so the coefficients are a particle ratio and "
                                "therefore a mole ratio. Masses only follow after multiplying by molar "
                                "masses.",
                ),
            ],
            correct=[0, 1, 2, 3],
        ),
        QuizAttempt(
            concept="Acids and Bases", difficulty="medium", days_ago=14,
            questions=[
                QuizQuestion(
                    question="What is the pH of a 0.010 M solution of hydrochloric acid?",
                    options=["2.00", "1.00", "12.00", "0.010"],
                    correct_answer="2.00",
                    explanation="HCl is a strong acid and dissociates completely, so [H+] = 0.010 M and "
                                "pH = -log(0.010) = 2.00.",
                ),
                QuizQuestion(
                    question="At 25 degrees Celsius, what does pH + pOH equal?",
                    options=["14.00", "7.00", "1.00", "Zero"],
                    correct_answer="14.00",
                    explanation="The ion product of water is 1.0 x 10^-14 at this temperature, and taking "
                                "negative logarithms of both sides gives pH + pOH = 14.00.",
                ),
                QuizQuestion(
                    question="What makes a solution act as a buffer?",
                    options=["It contains a weak acid and its conjugate base in comparable amounts",
                             "It contains a strong acid and a strong base",
                             "It contains only a concentrated strong acid",
                             "It contains water and the salt of a strong acid and a strong base"],
                    correct_answer="It contains a weak acid and its conjugate base in comparable amounts",
                    explanation="The pair consumes added base and added acid respectively, so the ratio "
                                "in the Henderson-Hasselbalch equation moves only slightly.",
                ),
                QuizQuestion(
                    question="In a buffer where the conjugate base and the weak acid are at equal "
                             "concentrations, what is the pH?",
                    options=["Equal to the pKa", "Always 7.00", "Equal to 14 minus the pKa", "Zero"],
                    correct_answer="Equal to the pKa",
                    explanation="Henderson-Hasselbalch gives pH = pKa + log(1), and the logarithm of one "
                                "is zero, so the pH sits exactly at the pKa.",
                ),
            ],
            correct=[0, 1],
        ),
        QuizAttempt(
            concept="Chemical Equilibrium", difficulty="hard", days_ago=7,
            questions=[
                QuizQuestion(
                    question="What is the equilibrium constant expression for N2 + 3 H2 <-> 2 NH3?",
                    options=["[NH3]^2 / ([N2] [H2]^3)", "([N2] [H2]^3) / [NH3]^2",
                             "[NH3] / ([N2] [H2])", "2[NH3] / ([N2] + 3[H2])"],
                    correct_answer="[NH3]^2 / ([N2] [H2]^3)",
                    explanation="Products over reactants, each concentration raised to its stoichiometric "
                                "coefficient as an exponent rather than a multiplier.",
                ),
                QuizQuestion(
                    question="More nitrogen is added to the system at constant temperature. Which way "
                             "does the equilibrium shift?",
                    options=["Toward the products", "Toward the reactants", "It does not shift",
                             "It shifts toward the products and increases K"],
                    correct_answer="Toward the products",
                    explanation="Adding a reactant makes Q smaller than K, so the system consumes the "
                                "added nitrogen and shifts right. K itself is unchanged.",
                ),
                QuizQuestion(
                    question="An exothermic reaction at equilibrium is heated. What happens?",
                    options=["It shifts toward the reactants and K decreases",
                             "It shifts toward the products and K increases",
                             "It shifts toward the products but K is unchanged",
                             "The rate falls but nothing else changes"],
                    correct_answer="It shifts toward the reactants and K decreases",
                    explanation="Treat heat as a product of an exothermic reaction: adding heat pushes "
                                "the system left. Temperature is the one change that alters K.",
                ),
                QuizQuestion(
                    question="The entries in the Change row of an ICE table must be what?",
                    options=["In the stoichiometric ratio of the balanced equation",
                             "All equal to x", "Always positive",
                             "The equilibrium concentrations themselves"],
                    correct_answer="In the stoichiometric ratio of the balanced equation",
                    explanation="Three moles of hydrogen are consumed per mole of nitrogen, so the row "
                                "reads -x, -3x, +2x. The coefficients appear nowhere else in the table.",
                ),
            ],
            correct=[0],
        ),
    ],
    session=TutorSession(
        name="Le Chatelier without memorising the cases",
        topic="Chemical Equilibrium",
        mode="expository",
        summary_bullets=[
            "Replaced four memorised Le Chatelier cases with one comparison of Q against K.",
            "Separated shifting the position of equilibrium from changing K itself.",
            "Pinned down why heating an exothermic reaction lowers K.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "Le Chatelier is four separate rules in my notes and I mix them up under time pressure. "
                "Is there a way to think about it that isn't memorisation?"
            )),
            ChatMessage(role="assistant", content=(
                "There is, and it collapses three of your four cases into one. Write the equilibrium "
                "expression, then evaluate it with whatever concentrations are in the flask right now. "
                "That number is Q. Equilibrium is the state where Q has reached K, so every "
                "concentration or pressure change is really just one question: did that change make Q "
                "bigger or smaller than K? If Q is below K the system runs forward to raise it; if Q is "
                "above K it runs backward."
            )),
            ChatMessage(role="assistant", content=(
                "Try it on your ammonia system. K = [NH3]^2 / ([N2][H2]^3). You inject extra nitrogen. "
                "Nitrogen sits in the denominator, so Q drops below K, and the system moves forward to "
                "build it back up — it shifts toward products. You did not have to recall a rule about "
                "adding reactants; you read it off the expression."
            )),
            ChatMessage(role="user", content=(
                "That does cover adding and removing things. But temperature is in my notes as a separate "
                "case, and I never understood why."
            )),
            ChatMessage(role="assistant", content=(
                "Because it genuinely is different, and this is the distinction worth keeping. "
                "Concentration and pressure changes move the system along a fixed target: K does not "
                "move, only your position relative to it. Temperature moves the target itself. K is a "
                "function of temperature, so changing it gives the system a different number to chase."
            )),
            ChatMessage(role="assistant", content=(
                "The trick for the direction: write heat into the equation as if it were a species. An "
                "exothermic reaction releases heat, so heat belongs on the product side. Heating the "
                "flask is then 'adding a product', which pushes the reaction left — and because the "
                "target has genuinely moved, K is now smaller, not merely unmet."
            )),
            ChatMessage(role="user", content=(
                "So the exam question about heating an exothermic reaction is really asking whether I "
                "know K changed, not just which way it shifted."
            )),
            ChatMessage(role="assistant", content=(
                "Precisely — and the matching trap is the catalyst question. A catalyst lowers the "
                "barrier in both directions equally, so it changes neither Q at equilibrium nor K. It "
                "gets you to the same place sooner. If an answer choice says a catalyst shifts an "
                "equilibrium, it is wrong every time."
            )),
        ],
    ),
)


# ---------------------------------------------------------------------------
# COM CO 540 — COM Core Special Topics
# Fall 2026 section A1 topic: Media Innovation & Social Impact Practicum (MiSIP)
# ---------------------------------------------------------------------------

CO540 = Course(
    code="COM CO 540",
    name="COM Core Special Topics",
    department="Communication",
    credits=2,
    nickname="MiSIP",
    color="#DB2777",
    concepts=[
        Concept(name="Community Partner Collaboration", mastery=0.87,
                description="Working inside a partner organisation rather than studying it: showing up "
                            "to their meetings, learning their constraints, and taking direction."),
        Concept(name="Stakeholder Interviewing", mastery=0.8,
                description="Open questions, silence as a tool, following the answer rather than the "
                            "script, and capturing field notes that survive contact with a deadline."),
        Concept(name="Media Production for Advocacy", mastery=0.76,
                description="Making a short video, photo essay or written piece that serves a partner's "
                            "campaign goal rather than the maker's portfolio ambitions."),
        Concept(name="Scoping a Deliverable", mastery=0.63,
                description="Turning a partner's broad wish into a specific artifact with an owner, a "
                            "due date and an explicit definition of done, written down and agreed."),
        Concept(name="Professional Communication", mastery=0.55,
                description="Status updates a busy partner can read in thirty seconds, raising a problem "
                            "early, and the difference between a question and a request."),
        Concept(name="Audience and Channel Strategy", mastery=0.47,
                description="Choosing who a piece is actually for and where it will reach them, and "
                            "letting that decision drive length, format and tone."),
        Concept(name="Ethics of Representation", mastery=0.4,
                description="Informed consent, asset framing over deficit framing, participant review, "
                            "and who holds editorial control over a community's own story."),
        Concept(name="Portfolio Documentation", mastery=0.3,
                description="Recording process as well as product: the brief, the drafts, the partner's "
                            "feedback, and a clear account of what you personally contributed."),
        Concept(name="Impact Measurement", mastery=0.15,
                description="Separating outputs from outcomes, choosing an indicator a partner can "
                            "actually collect, and establishing a baseline before the work starts."),
        Concept(name="Theory of Change", mastery=0.05,
                description="The explicit chain from inputs through activities and outputs to outcomes "
                            "and long-term impact, with the assumptions between each link named."),
    ],
    edges=[
        Edge(source="Stakeholder Interviewing", target="Community Partner Collaboration",
             relationship="prerequisite", strength=0.85),
        Edge(source="Professional Communication", target="Community Partner Collaboration",
             relationship="builds_on", strength=0.7),
        Edge(source="Community Partner Collaboration", target="Scoping a Deliverable",
             relationship="prerequisite", strength=0.8),
        Edge(source="Audience and Channel Strategy", target="Media Production for Advocacy",
             relationship="prerequisite", strength=0.75),
        Edge(source="Ethics of Representation", target="Media Production for Advocacy",
             relationship="prerequisite", strength=0.8),
        Edge(source="Theory of Change", target="Impact Measurement",
             relationship="prerequisite", strength=0.9),
        Edge(source="Scoping a Deliverable", target="Portfolio Documentation",
             relationship="related", strength=0.6),
        Edge(source="Impact Measurement", target="Portfolio Documentation",
             relationship="related", strength=0.55),
    ],
    mastery_events=[
        MasteryEvent(concept="Community Partner Collaboration", delta=0.09,
                     reason="Partner kickoff meeting went well"),
        MasteryEvent(concept="Stakeholder Interviewing", delta=0.08,
                     reason="Second interview round, sharper questions"),
        MasteryEvent(concept="Impact Measurement", delta=-0.06,
                     reason="Could not name a baseline indicator"),
    ],
    categories=[
        Category(name="Partner Work", weight=0.4),
        Category(name="Reflection Memos", weight=0.25),
        Category(name="Final Portfolio", weight=0.35),
    ],
    assignments=[
        Assignment(title="Partner Brief and Scope Agreement", category="Partner Work", type="project",
                   due_offset_days=17, points_possible=25, points_earned=24),
        Assignment(title="Reflection Memo 1: Entering the Partnership", category="Reflection Memos",
                   type="homework", due_offset_days=30, points_possible=15, points_earned=14),
        Assignment(title="Midterm Partner Check-in", category="Partner Work", type="exam",
                   due_offset_days=45, points_possible=50, points_earned=41, is_midterm=True),
        Assignment(title="Interview Round and Field Notes", category="Partner Work", type="homework",
                   due_offset_days=58, points_possible=25, points_earned=22),
        Assignment(title="Reflection Memo 2: Ethics in the Field", category="Reflection Memos",
                   type="homework", due_offset_days=72, points_possible=15),
        Assignment(title="Draft Deliverable for Partner Review", category="Partner Work", type="project",
                   due_offset_days=88, points_possible=30),
        Assignment(title="Final Portfolio and Public Presentation", category="Final Portfolio",
                   type="project", due_offset_days=102, points_possible=100),
    ],
    notes=[
        Note(
            title="Scope agreement with the partner — what I'd do differently",
            tags=["partner", "scoping", "misip"],
            concepts=["Scoping a Deliverable", "Community Partner Collaboration"],
            body=(
                "Kickoff with the partner went well right up to the point where we tried to write down "
                "what we were actually making. Notes from the second meeting, where it finally worked.\n\n"
                "## What they said first\n"
                "\"We'd love help telling our story better.\" That is a direction, not a deliverable. "
                "Three of us left the first meeting with three different pictures in our heads, which is "
                "exactly the failure mode the seminar reading warned about.\n\n"
                "## The four questions that unstuck it\n"
                "1. **Who is this for?** Not \"the public\" — the answer turned out to be prospective "
                "volunteers aged roughly 20-35.\n"
                "2. **Where will they see it?** Instagram and the volunteer signup page. That single "
                "answer killed the eight-minute documentary idea on the spot.\n"
                "3. **What should they do after seeing it?** Click through to the signup form. Having a "
                "specific action made every later editing decision easier.\n"
                "4. **What does done look like?** Three vertical videos, 45-60 seconds, captioned, "
                "delivered as files they own, by the second week of November.\n\n"
                "## The written agreement\n"
                "One page, and we both have a copy: the artifact, the owner on each side, the review "
                "dates, and — the part I would have skipped — what is explicitly NOT in scope. We wrote "
                "down that we are not rebuilding their website. That sentence has already saved one "
                "awkward conversation.\n\n"
                "## Lesson\n"
                "The partner is not being vague on purpose. They live inside the problem and I asked them "
                "to describe it from outside. Specific questions are the service here, not an imposition."
            ),
        ),
        Note(
            title="Outputs vs outcomes — the thing I still can't do",
            tags=["impact", "measurement", "memo2"],
            concepts=["Impact Measurement", "Theory of Change"],
            body=(
                "Half marks on the impact section of the midterm check-in. I can describe what we made; "
                "I cannot say what changed because of it. Trying to fix that here.\n\n"
                "## The ladder from the reading\n"
                "```\n"
                "inputs      what we put in         staff hours, equipment, our time\n"
                "activities  what we did            shot and edited three videos\n"
                "outputs     what exists now        three captioned videos, published\n"
                "outcomes    what changed           volunteer signups went from 4 to 11 a month\n"
                "impact      the long-run goal      the program runs at full staffing\n"
                "```\n"
                "Everything I wrote in the check-in was in the first three rows. Views, likes and "
                "follower counts are all OUTPUTS — they describe the artifact's reach, not anyone's "
                "changed behaviour.\n\n"
                "## Why this is hard and not just pedantic\n"
                "An outcome needs something measured BEFORE we started. We have no baseline for signups "
                "because nobody wrote the number down in September. Without it, even a real improvement "
                "is unattributable — the partner could reasonably say it was the season.\n\n"
                "## What I asked the partner for\n"
                "- monthly volunteer signups for the last twelve months (they have this in the CRM)\n"
                "- the signup-page click-through rate before the campaign\n"
                "- one qualitative measure: are new volunteers mentioning the videos at intake?\n\n"
                "## Leading vs lagging\n"
                "Signups are a lagging indicator — by the time they move, the work is long done. "
                "Click-through on the signup link is a leading one; it moves within days and predicts "
                "the signups. For a semester-length project, the leading indicator is the one we can "
                "actually report on in the final portfolio."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="co540-misip-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for the Fall section of COM CO 540, COM Core Special Topics, whose topic "
                    "this term is the Media Innovation and Social Impact Practicum (MiSIP).",
            concept_notes=[
                ConceptNote(name="Community Partner Collaboration",
                            description="The spine of the course; partners are assigned in week 2."),
                ConceptNote(name="Ethics of Representation",
                            description="Weeks 5-6 seminar, before any filming in the field."),
                ConceptNote(name="Impact Measurement",
                            description="Weeks 9-10, and a required section of the final portfolio."),
                ConceptNote(name="Portfolio Documentation",
                            description="Assembled continuously, presented publicly in week 14."),
            ],
            extracted_text=(
                "COM CO 540 COM Core Special Topics — 2 units\n"
                "Boston University College of Communication\n"
                "Section A1, COM 206, Tuesdays 11:00-12:15. Instructor: Gordon.\n"
                "Topics vary each semester. This semester's topic: Media Innovation and Social Impact "
                "Practicum.\n\n"
                "Course Description: Media Innovation & Social Impact Practicum (MiSIP) is a "
                "practice-oriented course that bridges academic study and real-world engagement by "
                "placing students directly alongside community partners. Rather than examining media's "
                "role in social change from a distance, students gain hands-on experience navigating the "
                "challenges and opportunities of impact-driven media work in collaboration with "
                "practitioners already doing it. Through this embedded partnership model, students "
                "develop professional skills, build meaningful relationships across sectors, and "
                "contribute substantively to ongoing initiatives, leaving the course not only with a "
                "deeper understanding of how media can advance social good, but with the experience and "
                "portfolio to prove it.\n\n"
                "Format: one seminar meeting a week, plus field hours with your assigned partner "
                "organisation. Expect roughly four field hours a week. The seminar exists to support the "
                "field work, not the other way round.\n\n"
                "Grading\n"
                "  Partner work (brief, check-in, field notes, draft)   40%\n"
                "  Reflection memos                                     25%\n"
                "  Final portfolio and public presentation              35%\n\n"
                "A note on partners: these are real organisations with real deadlines. Missing a partner "
                "meeting is not equivalent to missing a class. If something goes wrong, tell the "
                "instructor and the partner early; the course is far more forgiving of a problem raised "
                "in week six than of one discovered in week thirteen.\n\n"
                "Schedule\n"
                "  1      What impact-driven media work actually involves\n"
                "  2      Partner assignments; the embedded partnership model\n"
                "  3-4    Scoping: turning a wish into a deliverable; writing the scope agreement\n"
                "  5-6    Ethics of representation: consent, framing, participant review\n"
                "  7      Interviewing and field notes\n"
                "  8      MIDTERM PARTNER CHECK-IN (partner attends)\n"
                "  9-10   Theory of change; outputs, outcomes and indicators\n"
                "  11-12  Audience and channel strategy; production work\n"
                "  13     Partner review of drafts\n"
                "  14     Final portfolio and public presentation\n"
            ),
        ),
        Document(
            file_name="co540-scope-agreement-template.pdf",
            category="reading",
            summary="The one-page scope agreement template the practicum requires every student team to "
                    "complete with its partner organisation before production begins.",
            concept_notes=[
                ConceptNote(name="Scoping a Deliverable",
                            description="The template's required fields, including what is out of scope."),
                ConceptNote(name="Professional Communication",
                            description="Named owners and review dates on both sides."),
            ],
            extracted_text=(
                "MiSIP Scope Agreement — one page, signed by both sides before production begins\n\n"
                "Why this exists. Most practicum partnerships that go badly go badly for the same "
                "reason: the student and the partner each held a reasonable but different picture of "
                "what was being made, and neither discovered the gap until the deliverable arrived. The "
                "agreement is not a contract. It is a forcing function for a conversation.\n\n"
                "Required fields\n"
                "  1. The artifact. What physically exists at the end? Name a format, a quantity and a "
                "length. 'Three vertical videos, 45-60 seconds, captioned' is a deliverable; 'social "
                "media support' is not.\n"
                "  2. The audience. Who is this for, specifically enough to exclude someone? If the "
                "answer is 'the general public', keep asking.\n"
                "  3. The desired action. What should a member of that audience do after encountering "
                "it? This decides length, platform and tone more than any aesthetic preference will.\n"
                "  4. Owners. One named person on the student side and one on the partner side. Not a "
                "team, a person.\n"
                "  5. Review dates. At minimum a draft review and a final review, as calendar dates.\n"
                "  6. Out of scope. The field students most want to skip and most need. Write down the "
                "adjacent work you are NOT doing: the website, the annual report, the ongoing posting "
                "schedule.\n"
                "  7. Assets and access. Who provides footage, logos, interviewees and permissions, and "
                "by when.\n"
                "  8. Ownership. Who holds the files and the usage rights at the end. The default in "
                "this practicum is that the partner owns the deliverable and the student retains the "
                "right to show it in a portfolio.\n\n"
                "Revising the agreement is normal and expected. Scope changes are fine; silent scope "
                "changes are the failure. If the work moves, update the page and have both owners "
                "initial it.\n"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="Output versus outcome",
                  back="An output is what now exists because of the work (three published videos). An "
                       "outcome is what changed in someone's behaviour or situation because of it."),
        Flashcard(front="Why does a baseline matter?",
                  back="Without the indicator's value before the work began, any later change cannot be "
                       "attributed to the work. Collect the baseline before production starts."),
        Flashcard(front="Leading versus lagging indicator",
                  back="A leading indicator moves early and predicts later change (link click-through); "
                       "a lagging one confirms it after the fact (volunteer signups)."),
        Flashcard(front="The theory-of-change chain",
                  back="Inputs, then activities, then outputs, then outcomes, then long-run impact — "
                       "with the assumption between each pair of links stated explicitly."),
        Flashcard(front="Asset framing versus deficit framing",
                  back="Deficit framing defines a community by what it lacks; asset framing leads with "
                       "its existing strengths, expertise and relationships."),
        Flashcard(front="What does informed consent require?",
                  back="The participant understands how the material will be used, where it will "
                       "appear, and that they can decline or withdraw without penalty."),
        Flashcard(front="Four questions that turn a wish into a deliverable",
                  back="Who is it for? Where will they see it? What should they do next? What does done "
                       "look like, as a format, quantity and date?"),
        Flashcard(front="Why does the scope agreement list what is OUT of scope?",
                  back="Adjacent work expands silently otherwise. Naming the website or the posting "
                       "schedule as excluded prevents the awkward later conversation."),
        Flashcard(front="What belongs in a practicum portfolio besides the finished piece?",
                  back="The brief, the drafts, the partner's feedback, and a clear statement of what you "
                       "personally contributed — process is assessed alongside product."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The Midterm Partner Check-in is a joint meeting: your partner is in the room, and the "
            "instructor is assessing whether the partnership is actually working, not whether you can "
            "recite the seminar readings. Bring the signed scope agreement, evidence of field hours, and "
            "an honest account of what is behind. The impact section is the one most students lose "
            "points on, because they describe what they made instead of what they expect to change."
        ),
        topics=[
            StudyGuideTopic(
                name="The scope agreement, as signed",
                importance="The first thing asked for. Be able to state the artifact, the audience and "
                           "the desired action in one sentence each, and point to what is out of scope.",
                concepts=["Scoping a Deliverable", "Community Partner Collaboration"],
            ),
            StudyGuideTopic(
                name="Evidence from the field",
                importance="Field notes and interview records, not a summary written the night before. "
                           "Dated notes showing how the plan changed on contact are what earn credit.",
                concepts=["Stakeholder Interviewing", "Professional Communication"],
            ),
            StudyGuideTopic(
                name="Ethics decisions already made",
                importance="Expect to be asked who consented to what, and whether anyone portrayed in "
                           "the work has seen it. Have an answer about framing ready.",
                concepts=["Ethics of Representation"],
            ),
            StudyGuideTopic(
                name="How this work will be measured",
                importance="The weakest section last time. Name one indicator, its baseline value, and "
                           "who collects it — and be able to say which outcome it stands in for.",
                concepts=["Impact Measurement", "Theory of Change"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Ethics of Representation", difficulty="medium", days_ago=16,
            questions=[
                QuizQuestion(
                    question="In community-engaged media practice, what does the principle \"nothing "
                             "about us without us\" require?",
                    options=["People affected by a story take part in deciding how it is told",
                             "Stories should avoid naming the communities they describe",
                             "Only community members may operate cameras",
                             "Journalists should not collaborate with nonprofit organisations"],
                    correct_answer="People affected by a story take part in deciding how it is told",
                    explanation="The principle is about shared editorial authority, not about avoiding "
                                "the subject or restricting who holds the equipment.",
                ),
                QuizQuestion(
                    question="What characterises a deficit framing of a community?",
                    options=["It defines the community primarily by its problems and what it lacks",
                             "It leads with the community's existing strengths and expertise",
                             "It relies exclusively on statistics",
                             "It avoids interviewing residents"],
                    correct_answer="It defines the community primarily by its problems and what it lacks",
                    explanation="Asset framing is the alternative: it opens from capability and "
                                "relationships rather than from need.",
                ),
                QuizQuestion(
                    question="For a filmed interview, informed consent requires that the participant "
                             "understands what?",
                    options=["How the footage will be used, where it will appear, and that they may "
                             "withdraw",
                             "Only that a camera is present and recording",
                             "The full production budget",
                             "The names of every other participant"],
                    correct_answer="How the footage will be used, where it will appear, and that they "
                                   "may withdraw",
                    explanation="Consent is to a specific use, in a specific place, revocably. Merely "
                                "noticing the camera is not consent to publication.",
                ),
                QuizQuestion(
                    question="What is the main purpose of letting a partner organisation review a draft "
                             "before publication?",
                    options=["To check accuracy and context with the people closest to the work",
                             "To transfer editorial control to the partner permanently",
                             "To satisfy a legal requirement that applies to all media",
                             "To shorten the production timeline"],
                    correct_answer="To check accuracy and context with the people closest to the work",
                    explanation="Participant review catches factual and contextual errors an outsider "
                                "cannot see; it is a practice norm here rather than a legal mandate.",
                ),
            ],
            correct=[0, 1, 2],
        ),
        QuizAttempt(
            concept="Impact Measurement", difficulty="hard", days_ago=6,
            questions=[
                QuizQuestion(
                    question="In a theory of change, which ordering is correct?",
                    options=["Outputs come before outcomes, which come before long-run impact",
                             "Impact comes before outcomes",
                             "Outcomes and outputs describe the same thing",
                             "Inputs come after outputs"],
                    correct_answer="Outputs come before outcomes, which come before long-run impact",
                    explanation="The chain runs inputs, activities, outputs, outcomes, impact — each "
                                "link depending on an assumption about the one before it.",
                ),
                QuizQuestion(
                    question="A campaign video records 2,400 views. What is that figure best classified "
                             "as?",
                    options=["An output", "An outcome", "An impact", "A theory of change"],
                    correct_answer="An output",
                    explanation="Views measure the artifact's reach. Only a change in what someone does "
                                "or experiences would count as an outcome.",
                ),
                QuizQuestion(
                    question="What is a baseline measurement?",
                    options=["The indicator's value before the work begins, so later change can be "
                             "attributed",
                             "The minimum result considered acceptable",
                             "The average across all partner organisations",
                             "The lowest budget the project can run on"],
                    correct_answer="The indicator's value before the work begins, so later change can be "
                                   "attributed",
                    explanation="Without a before-value, an improvement cannot be distinguished from "
                                "seasonality or any other coincident cause.",
                ),
                QuizQuestion(
                    question="How does a leading indicator differ from a lagging one?",
                    options=["It moves early and predicts later change",
                             "It can only be measured once the project has ended",
                             "It is always qualitative rather than numerical",
                             "It requires a randomised control group"],
                    correct_answer="It moves early and predicts later change",
                    explanation="Click-through on a signup link moves within days; the signups it "
                                "predicts arrive much later, which is why short projects report the "
                                "leading measure.",
                ),
            ],
            correct=[0],
        ),
    ],
    session=TutorSession(
        name="Turning the partner's wish into a deliverable",
        topic="Scoping a Deliverable",
        mode="socratic",
        summary_bullets=[
            "Converted \"tell our story better\" into three captioned vertical videos with a date.",
            "Used audience and desired action to rule out the long-documentary approach.",
            "Added an explicit out-of-scope line to the agreement before signing it.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "Our partner said they want help telling their story better. Everyone on my team heard "
                "something different. How do I get from that to something we can actually build?"
            )),
            ChatMessage(role="assistant", content=(
                "You narrow it with questions rather than guesses, and the order matters. Start with "
                "audience, because it constrains everything downstream. When they picture someone "
                "encountering this and it working, who is that person?"
            )),
            ChatMessage(role="user", content=(
                "I asked and at first they said 'the public'. When I pushed, it turned out they mean "
                "people who might volunteer — roughly twenties to mid-thirties."
            )),
            ChatMessage(role="assistant", content=(
                "That is a real audience, and pushing was the right move. Now the second question, which "
                "does most of the work: where will those people actually encounter it? Not where it "
                "could theoretically live — where this partner already reaches them."
            )),
            ChatMessage(role="user", content=(
                "Instagram, and the volunteer signup page on their site. Which... kills the eight-minute "
                "documentary we'd been sketching, doesn't it."
            )),
            ChatMessage(role="assistant", content=(
                "It does, and better now than in week twelve. Those two channels imply short, vertical "
                "and captioned, because most of that audience watches without sound. Third question: "
                "after someone watches, what do you want them to do? Name one action."
            )),
            ChatMessage(role="user", content=(
                "Click through and fill in the volunteer form. So the piece has to end on that, and it "
                "has to be short enough that they still have the attention to click."
            )),
            ChatMessage(role="assistant", content=(
                "Now you have a deliverable: three vertical videos, 45 to 60 seconds, captioned, each "
                "ending on the signup call to action, delivered as files the partner owns, by a named "
                "date. Write that on the scope page — and add the line most teams skip: what you are NOT "
                "doing. If their website is out of scope, say so now, while it is an easy sentence "
                "rather than an awkward conversation."
            )),
        ],
    ),
)


# ---------------------------------------------------------------------------
# QST SI 480 — The Business of Technology Innovation
# ---------------------------------------------------------------------------

SI480 = Course(
    code="QST SI 480",
    name="The Business of Technology Innovation",
    department="Strategy & Innovation",
    credits=4,
    nickname="Tech Business",
    color="#EA580C",
    concepts=[
        Concept(name="Finding Business Ideas", mastery=0.85,
                description="Where opportunities actually come from: a problem you have lived with, a "
                            "shift in cost or regulation, or a technology that just became affordable."),
        Concept(name="Evaluating an Opportunity", mastery=0.79,
                description="Telling a good idea from a bad one before building it — is the problem "
                            "painful, frequent, and held by someone with a budget to solve it?"),
        Concept(name="Business Model Design", mastery=0.76,
                description="How a business creates, delivers and captures value: the canvas blocks and "
                            "why the same technology can succeed under one model and fail under another."),
        Concept(name="Customer Discovery", mastery=0.66,
                description="Structured interviews that test a problem hypothesis without pitching, and "
                            "listening for what people already do rather than what they say they want."),
        Concept(name="Pricing and Go-to-Market", mastery=0.58,
                description="What to sell and how to sell it: pricing to the value delivered, and "
                            "choosing a sales motion that matches the price and the buyer."),
        Concept(name="The Role of Engineering in a Business", mastery=0.5,
                description="Why the engineering organisation is a cost centre on the income statement "
                            "and the source of the moat in the strategy, and how to argue in both terms."),
        Concept(name="Unit Economics", mastery=0.35,
                description="The profitability of a single customer: contribution margin, cost to "
                            "acquire, lifetime value, and the payback period that ties them together."),
        Concept(name="Business Financial Statements", mastery=0.2,
                description="Reading the balance sheet, income statement and cash flow statement, and "
                            "why a profitable company can still run out of money."),
        Concept(name="Venture Capital and Fundraising", mastery=0.13,
                description="How rounds are priced, what investors underwrite, and the difference "
                            "between a priced equity round and a convertible instrument."),
        Concept(name="Cap Tables and Equity", mastery=0.04,
                description="Who owns what after each round, how the option pool and dilution work, and "
                            "what a founder or an early engineer actually holds."),
    ],
    edges=[
        Edge(source="Finding Business Ideas", target="Evaluating an Opportunity",
             relationship="prerequisite", strength=0.85),
        Edge(source="Customer Discovery", target="Evaluating an Opportunity",
             relationship="prerequisite", strength=0.85),
        Edge(source="Evaluating an Opportunity", target="Business Model Design",
             relationship="prerequisite", strength=0.8),
        Edge(source="Business Model Design", target="Pricing and Go-to-Market",
             relationship="prerequisite", strength=0.8),
        Edge(source="The Role of Engineering in a Business", target="Business Model Design",
             relationship="related", strength=0.6),
        Edge(source="Pricing and Go-to-Market", target="Unit Economics",
             relationship="prerequisite", strength=0.85),
        Edge(source="Unit Economics", target="Business Financial Statements",
             relationship="builds_on", strength=0.7),
        Edge(source="Business Financial Statements", target="Venture Capital and Fundraising",
             relationship="prerequisite", strength=0.75),
        Edge(source="Venture Capital and Fundraising", target="Cap Tables and Equity",
             relationship="prerequisite", strength=0.9),
    ],
    mastery_events=[
        MasteryEvent(concept="Business Model Design", delta=0.1, reason="Canvas presentation went well"),
        MasteryEvent(concept="Customer Discovery", delta=0.08, reason="Ten discovery interviews done"),
        MasteryEvent(concept="Business Financial Statements", delta=-0.07,
                     reason="Confused net income with cash"),
    ],
    categories=[
        Category(name="Case Write-ups", weight=0.25, drop_lowest=1),
        Category(name="Team Venture Project", weight=0.4),
        Category(name="Exams", weight=0.35),
    ],
    assignments=[
        Assignment(title="Case Write-up 1: Finding and Screening Ideas", category="Case Write-ups",
                   type="homework", due_offset_days=12, points_possible=30, points_earned=28),
        Assignment(title="Customer Discovery: Ten Interviews and Findings", category="Team Venture Project",
                   type="project", due_offset_days=26, points_possible=40, points_earned=37),
        Assignment(title="Business Model Canvas Presentation", category="Team Venture Project",
                   type="project", due_offset_days=40, points_possible=50, points_earned=46),
        Assignment(title="Midterm Exam", category="Exams", type="exam",
                   due_offset_days=54, points_possible=100, points_earned=79, is_midterm=True),
        Assignment(title="Case Write-up 2: Reading a Startup's Financials", category="Case Write-ups",
                   type="homework", due_offset_days=68, points_possible=30, points_earned=20),
        Assignment(title="Pricing and Go-to-Market Memo", category="Team Venture Project",
                   type="homework", due_offset_days=82, points_possible=30),
        Assignment(title="Final Venture Pitch", category="Team Venture Project", type="project",
                   due_offset_days=96, points_possible=100),
        Assignment(title="Final Exam", category="Exams", type="exam",
                   due_offset_days=109, points_possible=100),
    ],
    notes=[
        Note(
            title="Customer discovery — the questions that actually worked",
            tags=["discovery", "interviews", "venture project"],
            concepts=["Customer Discovery", "Evaluating an Opportunity"],
            body=(
                "Ten interviews done for the venture project. The first three were nearly useless and "
                "the last four were good, so recording what changed.\n\n"
                "## What went wrong early\n"
                "I described our idea and asked whether they would use it. Everyone was polite and said "
                "yes. That told me nothing — people say yes to a friendly engineering student describing "
                "a free hypothetical. The lecture phrase for this is that you cannot learn about the "
                "problem by pitching the solution.\n\n"
                "## The questions that worked\n"
                "- \"Walk me through the last time this came up.\" Specific and in the past, so they "
                "recall rather than speculate.\n"
                "- \"What did you do about it?\" If the answer is 'nothing', the pain is not real pain.\n"
                "- \"What does it cost you when it happens?\" Hours, dollars or a missed deadline — this "
                "is where a budget shows up or fails to.\n"
                "- \"What have you already tried?\" Existing workarounds are the real competition, and "
                "they are usually a spreadsheet.\n"
                "- Then silence. Three of the most useful things I heard came after I stopped talking.\n\n"
                "## The screening test from lecture\n"
                "A good opportunity needs all three: the problem is PAINFUL, it is FREQUENT, and the "
                "person who has it has a BUDGET. Ours is painful and has a budget but happens maybe "
                "twice a year, which is why the willingness-to-pay answers were soft. Frequency is the "
                "one we talked ourselves out of checking.\n\n"
                "## What I would tell past me\n"
                "Interviews are not validation, they are disconfirmation attempts. If no interview could "
                "possibly have made us drop the idea, the interviews were theatre."
            ),
        ),
        Note(
            title="Three statements, and why profit is not cash",
            tags=["financials", "case2", "struggling"],
            concepts=["Business Financial Statements", "Unit Economics"],
            body=(
                "Case Write-up 2 was my worst grade of the semester. The whole thing turned on one "
                "distinction I did not have, so writing it down properly.\n\n"
                "## What each statement is for\n"
                "```\n"
                "balance sheet       a SNAPSHOT at one instant   what you own and owe\n"
                "income statement    a PERIOD                    revenue minus expenses -> profit\n"
                "cash flow statement a PERIOD                    cash actually in and out\n"
                "```\n"
                "The accounting equation holds on the balance sheet at every instant:\n"
                "```\n"
                "Assets = Liabilities + Shareholders' Equity\n"
                "```\n\n"
                "## The part I got wrong\n"
                "I read a positive net income and concluded the company was fine. It was running out of "
                "money. Revenue is recognised when it is EARNED, not when it is COLLECTED, so a company "
                "can book a sale, show profit, and be waiting ninety days for the customer to pay. "
                "Meanwhile it has already paid its suppliers and its staff. The gap sits in accounts "
                "receivable and inventory on the balance sheet, and only the cash flow statement shows "
                "the squeeze.\n\n"
                "The mirror image: depreciation is an expense on the income statement that moves no cash "
                "at all. That is why the cash flow statement starts from net income and adds it back.\n\n"
                "## Margins, which I also fumbled\n"
                "```\n"
                "gross margin      = (Revenue - COGS) / Revenue        can the product pay for itself\n"
                "contribution margin per unit = price - variable cost  what one more sale contributes\n"
                "net margin        = Net Income / Revenue              after everything\n"
                "```\n"
                "For the venture project: a high gross margin is what makes software fundable, because "
                "every additional customer carries almost no extra cost of goods. A hardware venture "
                "with a 20 percent gross margin needs a completely different plan for the same idea."
            ),
        ),
    ],
    documents=[
        Document(
            file_name="si480-syllabus.pdf",
            category="syllabus",
            summary="Syllabus for QST SI 480 The Business of Technology Innovation: an entrepreneurship "
                    "course for engineering students, built around cases and a semester venture project.",
            concept_notes=[
                ConceptNote(name="Finding Business Ideas", description="Weeks 1-2, with the first case."),
                ConceptNote(name="Business Model Design",
                            description="Weeks 5-6; the canvas presentation is graded here."),
                ConceptNote(name="Business Financial Statements",
                            description="Weeks 9-10, the hardest unit for engineering students."),
                ConceptNote(name="Venture Capital and Fundraising",
                            description="Weeks 12-13, leading into the final pitch."),
            ],
            extracted_text=(
                "QST SI 480 The Business of Technology Innovation — 4 units\n"
                "Boston University Questrom School of Business, Strategy and Innovation\n"
                "Section A1, HAR 322, Mondays 6:30-9:15 pm.\n"
                "Enrollment: open to ENG sophomores, juniors and seniors only.\n\n"
                "Course Description: Provides an introduction to entrepreneurship and business for the "
                "engineer. Topics include finding business ideas; recognizing good from bad; "
                "understanding the importance of business model; turning technology into a business, "
                "including what to sell and how to sell it; the role of engineering within a business; "
                "business financial statements; and startups and venture capital, including starting a "
                "company or joining a startup.\n\n"
                "A note on the audience: this course assumes you can build things and assumes you have "
                "never read a balance sheet. No prior business coursework is expected, and none of the "
                "finance material is as hard as the mathematics you already do. The difficulty is "
                "vocabulary and judgement, not technique.\n\n"
                "Grading\n"
                "  Case write-ups (lowest dropped)   25%\n"
                "  Team venture project              40%\n"
                "  Midterm and final exams           35%\n\n"
                "The venture project runs all semester in teams of four. You will pick a technology, "
                "interview at least ten potential customers, build and defend a business model, price "
                "it, and pitch it to a panel in the final session. Teams may not change after week 4.\n\n"
                "Schedule\n"
                "  1-2    Where ideas come from; screening good opportunities from bad ones\n"
                "  3-4    Customer discovery; interviewing without pitching\n"
                "  5-6    Business models; the canvas; why the model can matter more than the technology\n"
                "  7      What to sell and how to sell it: pricing and the sales motion\n"
                "  8      MIDTERM EXAM; the role of engineering within a business\n"
                "  9-10   Business financial statements: balance sheet, income statement, cash flow\n"
                "  11     Unit economics: contribution margin, cost to acquire, lifetime value\n"
                "  12-13  Startups and venture capital; rounds, dilution and cap tables\n"
                "  14     Final venture pitch to the panel; joining a startup versus starting one\n"
            ),
        ),
        Document(
            file_name="si480-financial-statements-primer.pdf",
            category="reading",
            summary="Primer handed out before the financial statements unit: the three statements, how "
                    "they connect, and the engineer's usual misreading of profit as cash.",
            concept_notes=[
                ConceptNote(name="Business Financial Statements",
                            description="The three statements and the links between them."),
                ConceptNote(name="Unit Economics",
                            description="Gross versus contribution margin, and why the difference bites."),
            ],
            extracted_text=(
                "SI 480 Primer: Reading a Company's Financial Statements\n\n"
                "Three statements, three questions. The BALANCE SHEET answers 'what does the company own "
                "and owe, right now?' It is a snapshot at a single instant, and it always balances: "
                "Assets = Liabilities + Shareholders' Equity. The INCOME STATEMENT answers 'did the "
                "company make a profit over this period?' It runs from revenue down through costs to net "
                "income. The CASH FLOW STATEMENT answers 'where did the money actually go over this "
                "period?' and separates operating, investing and financing activity.\n\n"
                "Profit is not cash, and this is the single most important idea in the unit. Under "
                "accrual accounting, revenue is recorded when it is EARNED, not when the customer pays. "
                "A company that ships in March and gets paid in June books March revenue and March "
                "profit while its bank balance falls. The difference accumulates in accounts receivable "
                "and in inventory. A growing company with real profits can fail purely on timing, which "
                "is why the cash flow statement exists as a separate document rather than a footnote.\n\n"
                "The reconciliation. The cash flow statement begins at net income and adjusts it back "
                "toward cash: it adds back non-cash expenses such as depreciation and amortisation, then "
                "corrects for changes in working capital. An increase in receivables is a use of cash; an "
                "increase in payables is a source of it.\n\n"
                "Margins. Gross margin is (Revenue minus Cost of Goods Sold) divided by Revenue, and it "
                "tells you whether the product can ever pay for the company around it. Contribution "
                "margin per unit is price minus variable cost, and it tells you what one additional sale "
                "is worth. Net margin is net income over revenue, after everything. Software ventures "
                "typically show high gross margins because an additional customer costs almost nothing "
                "to serve; hardware ventures rarely do, and the business plans that follow from the two "
                "cases look nothing alike.\n\n"
                "What this means for an engineer. Your engineering organisation appears as an expense on "
                "the income statement and as the company's defensibility in its strategy. Learning to "
                "make both arguments about the same work is most of what this unit is for.\n"
            ),
        ),
    ],
    flashcards=[
        Flashcard(front="The three financial statements, and what each answers",
                  back="Balance sheet: what is owned and owed at an instant. Income statement: profit "
                       "over a period. Cash flow statement: cash in and out over a period."),
        Flashcard(front="The accounting equation",
                  back="Assets = Liabilities + Shareholders' Equity. It holds on the balance sheet at "
                       "every instant."),
        Flashcard(front="How can a profitable company run out of cash?",
                  back="Revenue is booked when earned, not collected. Receivables and inventory tie up "
                       "cash while the income statement already shows the profit."),
        Flashcard(front="Gross margin",
                  back="(Revenue - COGS) / Revenue. It says whether the product can pay for the company "
                       "around it — the reason software and hardware ventures need different plans."),
        Flashcard(front="Three screens for a good opportunity",
                  back="The problem is painful, it is frequent, and whoever has it holds a budget. "
                       "Failing any one of the three usually sinks the idea."),
        Flashcard(front="Why not pitch during a discovery interview?",
                  back="People agree politely with hypotheticals. Ask what they did last time the "
                       "problem came up and what it cost them — past behaviour, not predicted behaviour."),
        Flashcard(front="Pre-money versus post-money valuation",
                  back="Pre-money is the company's value before the new investment; post-money is "
                       "pre-money plus the amount raised. Investor ownership = raise / post-money."),
        Flashcard(front="What is dilution?",
                  back="Issuing new shares means existing shareholders own a smaller percentage of a "
                       "company that is, if the round went well, worth more in total."),
        Flashcard(front="SAFE or convertible note versus a priced round",
                  back="It defers setting a valuation until a later priced round, converting then — "
                       "faster and cheaper to paper, at the cost of uncertain final ownership."),
    ],
    study_guide=StudyGuide(
        overview=(
            "The Midterm covers weeks 1-7: where ideas come from, screening them, customer discovery, "
            "the business model canvas, and pricing and go-to-market. Financial statements and venture "
            "capital are NOT on it — those are the second half. The exam is short-answer and case-based "
            "rather than quantitative: you will be handed a one-paragraph venture and asked to screen "
            "it, model it and price it, with reasoning carrying the marks rather than the verdict."
        ),
        topics=[
            StudyGuideTopic(
                name="Screening an opportunity",
                importance="The opening question almost every year. Apply painful, frequent and "
                           "budget-holding to the case given, and say which screen it fails.",
                concepts=["Finding Business Ideas", "Evaluating an Opportunity"],
            ),
            StudyGuideTopic(
                name="Customer discovery method",
                importance="Expect to be asked to write interview questions, or to say why a given set "
                           "is bad. Leading questions and pitching are the errors being tested.",
                concepts=["Customer Discovery"],
            ),
            StudyGuideTopic(
                name="The business model canvas",
                importance="The heaviest block. Know all nine blocks, and be ready to argue that the "
                           "same technology succeeds under one model and fails under another.",
                concepts=["Business Model Design"],
            ),
            StudyGuideTopic(
                name="Pricing and the sales motion",
                importance="Price to the value delivered, not to cost plus a margin, and match the sales "
                           "motion to the price point — a cheap product cannot carry a field sales team.",
                concepts=["Pricing and Go-to-Market", "The Role of Engineering in a Business"],
            ),
        ],
    ),
    quizzes=[
        QuizAttempt(
            concept="Business Model Design", difficulty="easy", days_ago=20,
            questions=[
                QuizQuestion(
                    question="In the Business Model Canvas, which block describes who you create value "
                             "for?",
                    options=["Customer Segments", "Key Activities", "Cost Structure", "Channels"],
                    correct_answer="Customer Segments",
                    explanation="Channels describe how you reach them and Key Activities what you do; "
                                "the segments block names the groups themselves.",
                ),
                QuizQuestion(
                    question="Beyond what the technology does, what question does a business model "
                             "answer?",
                    options=["How the business creates, delivers and captures value",
                             "Which programming language the product should use",
                             "How many engineers the company should hire",
                             "What the patent claims cover"],
                    correct_answer="How the business creates, delivers and captures value",
                    explanation="Capture is the part engineers most often leave out: a model that "
                                "creates value but cannot capture any of it is not a business.",
                ),
                QuizQuestion(
                    question="In this course, what does telling a good idea from a bad one mainly test?",
                    options=["Whether a real customer has a problem they will pay to solve",
                             "Whether the underlying technology is novel",
                             "Whether the founder is sufficiently passionate",
                             "Whether any competitor already exists"],
                    correct_answer="Whether a real customer has a problem they will pay to solve",
                    explanation="Novelty and passion are neither necessary nor sufficient, and "
                                "competitors are usually evidence that a market exists.",
                ),
                QuizQuestion(
                    question="How does a value proposition differ from the product?",
                    options=["The value proposition is the customer's gain; the product is how it is "
                             "delivered",
                             "They are two names for the same thing",
                             "The value proposition is the price charged",
                             "The product is the size of the addressable market"],
                    correct_answer="The value proposition is the customer's gain; the product is how it "
                                   "is delivered",
                    explanation="Stating the proposition in the customer's terms is what allows the same "
                                "value to be delivered by a different product later.",
                ),
            ],
            correct=[0, 1, 2, 3],
        ),
        QuizAttempt(
            concept="Business Financial Statements", difficulty="hard", days_ago=8,
            questions=[
                QuizQuestion(
                    question="Which statement shows a company's financial position at a single point in "
                             "time?",
                    options=["The balance sheet", "The income statement", "The cash flow statement",
                             "The statement of retained earnings"],
                    correct_answer="The balance sheet",
                    explanation="The other statements cover a period. The balance sheet is a snapshot, "
                                "which is why it balances at that instant.",
                ),
                QuizQuestion(
                    question="What is the fundamental accounting equation?",
                    options=["Assets = Liabilities + Shareholders' Equity",
                             "Assets = Liabilities - Shareholders' Equity",
                             "Revenue - Expenses = Assets",
                             "Cash = Assets + Liabilities"],
                    correct_answer="Assets = Liabilities + Shareholders' Equity",
                    explanation="Everything the company owns was funded either by someone it owes or by "
                                "its owners, so the two sides must agree.",
                ),
                QuizQuestion(
                    question="Why can a profitable company still run out of cash?",
                    options=["Revenue is recognised when earned rather than collected, so receivables "
                             "and inventory tie up cash",
                             "Net income is always negative in a company's first year",
                             "Depreciation is a large cash outflow",
                             "Raising equity financing reduces the cash balance"],
                    correct_answer="Revenue is recognised when earned rather than collected, so "
                                   "receivables and inventory tie up cash",
                    explanation="Accrual accounting books the sale before the money arrives, while "
                                "suppliers and payroll have already been paid. Depreciation is the "
                                "opposite case: an expense that moves no cash.",
                ),
                QuizQuestion(
                    question="How is gross margin calculated?",
                    options=["(Revenue - COGS) / Revenue", "Revenue - Operating Expenses",
                             "Net Income / Revenue", "Revenue / COGS"],
                    correct_answer="(Revenue - COGS) / Revenue",
                    explanation="It is the share of each revenue dollar left after the direct cost of "
                                "delivering the product. Net income over revenue is net margin instead.",
                ),
            ],
            correct=[0, 1],
        ),
        QuizAttempt(
            concept="Venture Capital and Fundraising", difficulty="medium", days_ago=3,
            questions=[
                QuizQuestion(
                    question="In a priced equity round, what does the pre-money valuation refer to?",
                    options=["The company's value before the new investment is added",
                             "The company's value once the round has closed",
                             "The total amount the investors are putting in",
                             "The founders' combined salary budget"],
                    correct_answer="The company's value before the new investment is added",
                    explanation="Post-money is pre-money plus the amount raised, and the distinction "
                                "decides exactly how much of the company the investors receive.",
                ),
                QuizQuestion(
                    question="A startup raises 2 million dollars on an 8 million dollar pre-money "
                             "valuation. What are the post-money valuation and the investors' stake?",
                    options=["10 million dollars and 20 percent", "10 million dollars and 25 percent",
                             "8 million dollars and 25 percent", "12 million dollars and 16.7 percent"],
                    correct_answer="10 million dollars and 20 percent",
                    explanation="Post-money is 8 + 2 = 10 million, and the investors' share is the raise "
                                "over post-money: 2/10, or 20 percent.",
                ),
                QuizQuestion(
                    question="What does dilution mean for existing shareholders?",
                    options=["They own a smaller percentage after new shares are issued",
                             "The company's valuation has fallen",
                             "They lose their liquidation preference",
                             "The employee option pool is cancelled"],
                    correct_answer="They own a smaller percentage after new shares are issued",
                    explanation="A smaller slice is not automatically worse: in a good round it is a "
                                "smaller percentage of a substantially more valuable company.",
                ),
                QuizQuestion(
                    question="How does a SAFE or convertible note differ from a priced round?",
                    options=["It defers setting a valuation until a later priced round",
                             "It gives the investor a board seat immediately",
                             "It is debt that must be repaid in cash on a fixed date",
                             "It can only be used once the company has revenue"],
                    correct_answer="It defers setting a valuation until a later priced round",
                    explanation="Postponing the valuation makes the instrument fast and cheap to paper, "
                                "at the cost of founders not knowing their final dilution yet.",
                ),
            ],
            correct=[0, 2],
        ),
    ],
    session=TutorSession(
        name="Why the profitable company in Case 2 was running out of money",
        topic="Business Financial Statements",
        mode="expository",
        summary_bullets=[
            "Separated accrual profit from cash, and located the gap in receivables and inventory.",
            "Traced the cash flow statement's walk from net income back to the change in cash.",
            "Reframed depreciation as the mirror case: an expense that moves no cash at all.",
        ],
        messages=[
            ChatMessage(role="user", content=(
                "I got Case 2 badly wrong. Net income was positive and growing, so I said the company "
                "was healthy. The answer key says it was about to run out of money. How are both true?"
            )),
            ChatMessage(role="assistant", content=(
                "They are both true because profit and cash are measured by different clocks, and this "
                "is the central idea of the unit rather than a trick in the case. Under accrual "
                "accounting, revenue is recorded when it is EARNED — when you ship, when you deliver — "
                "not when the customer's payment lands. Net income is a statement about what you have "
                "earned. It is not a statement about what you have."
            )),
            ChatMessage(role="assistant", content=(
                "Follow the company in the case through one order. It buys components in January and "
                "pays for them. It pays engineers and assembly staff in February. It ships in March, and "
                "the income statement records the sale and a healthy profit in March. The customer's "
                "terms are net 90, so the money arrives in June. For three months the company has paid "
                "out everything and received nothing, while its income statement looks excellent."
            )),
            ChatMessage(role="user", content=(
                "So where is that gap visible? It has to show up somewhere, or the balance sheet "
                "wouldn't balance."
            )),
            ChatMessage(role="assistant", content=(
                "Exactly the right instinct. It sits in two asset accounts: ACCOUNTS RECEIVABLE, which "
                "is revenue earned but not collected, and INVENTORY, which is cash converted into goods "
                "not yet sold. Both are assets, so the balance sheet balances perfectly while the bank "
                "account drains. And notice what growth does here — the faster the company grows, the "
                "more orders it is funding in advance, so growth makes the squeeze worse, not better."
            )),
            ChatMessage(role="assistant", content=(
                "That is why the cash flow statement exists as its own document. It starts at net "
                "income and walks back to reality: add back non-cash expenses, then subtract the "
                "increase in receivables and inventory. In the case, that walk turns a positive net "
                "income into negative operating cash flow, and the number at the bottom is the one that "
                "tells you how many months are left."
            )),
            ChatMessage(role="user", content=(
                "You said add back non-cash expenses — is depreciation the main one? That's the opposite "
                "problem, right? An expense where no money actually moves."
            )),
            ChatMessage(role="assistant", content=(
                "It is the mirror image, and holding both cases together is how you know you have this. "
                "Depreciation spreads the cost of equipment bought years ago across the periods that "
                "use it, so it reduces profit this year without any cash leaving this year. Receivables "
                "are cash leaving without reducing profit; depreciation is profit falling without cash "
                "leaving. For the exam, read all three statements before judging a company — and if you "
                "can only read one, make it the cash flow statement."
            )),
        ],
    ),
)


# ---------------------------------------------------------------------------
# The pack
# ---------------------------------------------------------------------------

PACK = MajorPack(
    key="computer_engineering",
    label="Computer Engineering",
    year="Sophomore",
    courses=[MA225, EK131, CH131, CO540, SI480],
    total_xp=1420,
    streak_days=7,
)
