import { describe, expect, it } from 'vitest';
import {
  conceptOptionsForCourse,
  courseOptions,
  resolveInitialSelection,
  type QuizConcept,
  type QuizCourseInput,
} from './quizSelection';

const COURSES: QuizCourseInput[] = [
  { course_id: 'c-cs330', course_code: 'CAS CS 330', course_name: 'Introduction to Analysis of Algorithms' },
  { course_id: 'c-cm501', course_code: 'COM CM 501', course_name: 'Media Theory' },
  { course_id: 'c-ma123', course_code: 'CAS MA 123', course_name: 'Calculus I' },
  { course_id: 'c-empty', course_code: 'CAS PY 100', course_name: 'Intro Physics' },
];

// Two nodes share the same concept name across different courses — this is the
// exact data shape that made the old flat dropdown look like it had duplicates.
const CONCEPTS: QuizConcept[] = [
  { id: 'n1', name: 'Big-O Notation', course_id: 'c-cs330', course_code: 'CAS CS 330' },
  { id: 'n2', name: 'Dynamic Programming', course_id: 'c-cs330', course_code: 'CAS CS 330' },
  { id: 'n3', name: 'Framing', course_id: 'c-cm501', course_code: 'COM CM 501' },
  { id: 'n4', name: 'Derivatives', course_id: 'c-ma123', course_code: 'CAS MA 123' },
];

describe('courseOptions', () => {
  it('lists every enrolled course, including ones with no concepts', () => {
    const opts = courseOptions(COURSES);
    expect(opts.map(o => o.value)).toContain('c-empty');
    expect(opts).toHaveLength(4);
  });

  it('sorts by label and labels as "<code> — <name>"', () => {
    const opts = courseOptions(COURSES);
    expect(opts.map(o => o.label)).toEqual([
      'CAS CS 330 — Introduction to Analysis of Algorithms',
      'CAS MA 123 — Calculus I',
      'CAS PY 100 — Intro Physics',
      'COM CM 501 — Media Theory',
    ]);
  });

  it('prefers the nickname over the catalog name when present', () => {
    const [opt] = courseOptions([
      { course_id: 'c1', course_code: 'CAS CS 330', course_name: 'Introduction to Analysis of Algorithms', nickname: 'Algorithms' },
    ]);
    expect(opt.label).toBe('CAS CS 330 — Algorithms');
  });
});

describe('conceptOptionsForCourse', () => {
  it('returns only the selected course\'s concepts', () => {
    const opts = conceptOptionsForCourse(CONCEPTS, 'c-cs330');
    expect(opts.map(o => o.label)).toEqual(['Big-O Notation', 'Dynamic Programming']);
  });

  it('returns [] when no course is selected', () => {
    expect(conceptOptionsForCourse(CONCEPTS, null)).toEqual([]);
  });

  it('returns [] for a course that has no concepts', () => {
    expect(conceptOptionsForCourse(CONCEPTS, 'c-empty')).toEqual([]);
  });
});

describe('resolveInitialSelection', () => {
  it('preselects the concept and its course from a deep link', () => {
    expect(resolveInitialSelection(CONCEPTS, 'n3')).toEqual({
      courseId: 'c-cm501',
      conceptId: 'n3',
    });
  });

  it('leaves both unset when there is no deep link', () => {
    expect(resolveInitialSelection(CONCEPTS, null)).toEqual({
      courseId: null,
      conceptId: null,
    });
  });

  it('leaves both unset when the concept id is unknown', () => {
    expect(resolveInitialSelection(CONCEPTS, 'does-not-exist')).toEqual({
      courseId: null,
      conceptId: null,
    });
  });
});
