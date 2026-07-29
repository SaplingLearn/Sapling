-- 0036: close the NULL-section gap in course_offerings uniqueness.
--
-- 0020's course_offerings_unique is a plain UNIQUE (course_id, term_id, section).
-- Plain UNIQUE treats NULLs as distinct, so two rows for the same
-- (course_id, term_id) with section IS NULL — exactly the shape
-- services/academics.py::resolve_offering(create=True) inserts — are BOTH
-- allowed. Two concurrent add_course calls could therefore each create an
-- offering for the same course+term and enroll against different rows,
-- defeating the no-retake invariant. This partial unique index makes the
-- NULL-section case unique too; sectioned rows stay governed by the existing
-- constraint. resolve_offering catches the resulting insert conflict and
-- re-selects the winner.
CREATE UNIQUE INDEX IF NOT EXISTS course_offerings_course_term_nullsec_uniq
    ON course_offerings (course_id, term_id)
    WHERE section IS NULL;
