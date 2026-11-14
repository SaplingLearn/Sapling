"use client";
import { CustomSelect } from "@/components/CustomSelect";
import type { EnrolledCourse } from "@/lib/api";
import { courseSelectOptions } from "@/lib/courseSelectOptions";
import type { ScopeOption } from "@/lib/studyGuide/types";

import { Field } from "./Field";
import m from "./newGuide.module.css";
import { scopeKey, scopeNote } from "./newGuideModel";

const FULL_WIDTH = { display: "block" } as const;

/** Which class the guide is for: the student's courses in the active term. */
export function ClassField({
  courses, ready, failed, onRetry, value, onChange,
}: {
  courses: EnrolledCourse[];
  /** The course list has answered. */
  ready: boolean;
  /** The course list could not be read: the student may well have classes. */
  failed: boolean;
  onRetry: () => void;
  value: string;
  onChange: (courseId: string) => void;
}) {
  const none = ready && courses.length === 0;
  return (
    <Field label="Class" hint={none ? "Add a class first to make a guide." : undefined}>
      <CustomSelect
        value={value}
        options={courseSelectOptions(courses).map(option => ({ ...option, testId: `guide-new-class-option-${option.value}` }))}
        onChange={onChange}
        placeholder={failed ? "Not available" : ready ? "Choose a class" : "Loading…"}
        ariaLabel="Class"
        disabled={courses.length === 0}
        style={FULL_WIDTH}
        testId="guide-new-class"
      />
      {failed && (
        <p className={m.note} role="alert">
          Couldn&apos;t load your classes.{" "}
          <button type="button" className={m.pick} data-testid="guide-new-class-retry" onClick={onRetry}>Try again</button>
        </p>
      )}
    </Field>
  );
}

/** What the guide is for: the whole course, an exam or an assignment. */
export function ScopeField({
  scopes, placeholder, value, onChange,
}: {
  scopes: ScopeOption[];
  /** What the field says while the class has no scopes to offer. */
  placeholder: string;
  /** The chosen scope's key (`scopeKey`), "" when there is none. */
  value: string;
  onChange: (key: string) => void;
}) {
  const options = scopes.map(scope => ({
    value: scopeKey(scope),
    label: scope.title,
    description: scopeNote(scope),
    testId: `guide-new-scope-option-${scopeKey(scope)}`,
  }));
  return (
    <Field label="Studying for">
      <CustomSelect
        value={value}
        options={options}
        onChange={onChange}
        placeholder={placeholder}
        ariaLabel="Studying for"
        disabled={scopes.length === 0}
        style={FULL_WIDTH}
        testId="guide-new-scope"
      />
    </Field>
  );
}
