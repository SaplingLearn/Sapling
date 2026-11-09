"use client";

/**
 * The answer input for the three written formats, each shaped to what it
 * asks for rather than one free-text box for all three:
 *
 * - short_answer: one line of text. The key is a term or brief fact (at most
 *   eight words, `routes/quiz.py`), so a paragraph box invited the very
 *   sentences the grader can never match.
 * - numeric: one line, the decimal keypad on a phone, keys for what that pad
 *   lacks (− / % and ×10ⁿ), its notation typeset in the field (3e8 shows as
 *   3×10⁸, the session keeps 3e8), and a live "Reads as 0.75" at the field's
 *   right end so a student sees their fraction or percentage parsed before
 *   they submit it.
 * - symbolic: one monospace line, keys for powers, brackets and operators,
 *   typeset IN the field as it is typed (2x^2 shows as 2x², while the session
 *   keeps the ASCII the grader reads), plus a plain warning for what the
 *   grammar refuses (functions, equations, an unclosed bracket).
 *
 * All three are the app's standard `.field`; what differs is the face (the
 * reading serif for a term, monospace for a number or an expression) and the
 * keys and read-back underneath.
 *
 * Enter submits from all three. The screen's own Enter handler skips typing
 * targets (it would steal a textarea's newline), so the input forwards Enter
 * itself — a single-line answer has no newline to lose.
 */

import React from "react";
import { Check, X } from "lucide-react";
import type { QuestionType } from "@/lib/quiz/types";
import {
  asciiExpression,
  asciiNumber,
  formatNumber,
  numericValue,
  prettyExpression,
  prettyNumber,
  symbolicProblem,
} from "@/lib/quiz/answerFormats";

export type WrittenType = Exclude<QuestionType, "multiple_choice">;

/** A key on the format's symbol row. `caret` is where the cursor lands,
 *  counted from the start of the inserted text (default: after it). */
interface Key {
  id: string;
  label: string;
  insert: string;
  caret?: number;
  ariaLabel: string;
}

// The keys cover what each format's grader accepts that a phone keyboard
// hides: the decimal pad has digits and a point but no minus, slash, percent,
// exponent or space; the text keyboard puts + ^ ( ) and every digit behind a
// layer switch. (Grammar: services/quiz_grading.py::numeric_value and
// services/quiz_algebra.py.)

const NUMERIC_KEYS: Key[] = [
  { id: "minus", label: "−", insert: "-", ariaLabel: "Insert minus sign" },
  { id: "fraction", label: "/", insert: "/", ariaLabel: "Insert fraction bar" },
  { id: "percent", label: "%", insert: "%", ariaLabel: "Insert percent sign" },
  { id: "exponent", label: "×10ⁿ", insert: "e", ariaLabel: "Insert times ten to the power (e notation)" },
  // A mixed number (1 1/2) needs a space, which the decimal pad doesn't have.
  { id: "space", label: "1 ½", insert: " ", ariaLabel: "Insert a space, for a mixed number such as 1 1/2" },
];

const SYMBOLIC_KEYS: Key[] = [
  { id: "squared", label: "x²", insert: "^2", ariaLabel: "Insert squared" },
  { id: "power", label: "xⁿ", insert: "^", ariaLabel: "Insert power" },
  { id: "brackets", label: "( )", insert: "()", caret: 1, ariaLabel: "Insert brackets" },
  { id: "plus", label: "+", insert: "+", ariaLabel: "Insert plus sign" },
  { id: "minus", label: "−", insert: "-", ariaLabel: "Insert minus sign" },
  { id: "times", label: "×", insert: "*", ariaLabel: "Insert multiplication sign" },
  { id: "divide", label: "÷", insert: "/", ariaLabel: "Insert division sign" },
];

/** Behind the "123" toggle: what the text keyboard keeps on another layer. */
const SYMBOLIC_MORE: Key[] = [
  ..."1234567890".split("").map(d => ({ id: `digit-${d}`, label: d, insert: d, ariaLabel: `Insert ${d}` })),
  { id: "point", label: ".", insert: ".", ariaLabel: "Insert decimal point" },
];

const PLACEHOLDER: Record<WrittenType, string> = {
  short_answer: "Type your answer",
  numeric: "e.g. 42, 3/4, 0.75, 75% or 3×10⁸",
  symbolic: "e.g. 2(x + 1) or x² − 1",
};

export interface WrittenAnswerProps {
  type: WrittenType;
  value: string;
  disabled: boolean;
  /** Set once the verdict is shown: the field itself says how it was marked. */
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
  /** Enter in the input — the screen's primary action, when it is enabled. */
  onSubmit: () => void;
  /** The visible format rules, for `aria-describedby`. */
  describedBy: string;
  /** "Your answer" plus the stem, so focusing the input reads the question. */
  labelledBy?: string;
}

export function WrittenAnswer({
  type,
  value,
  disabled,
  verdict = null,
  onChange,
  onSubmit,
  describedBy,
  labelledBy,
}: WrittenAnswerProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const keys = type === "numeric" ? NUMERIC_KEYS : type === "symbolic" ? SYMBOLIC_KEYS : [];
  const more = type === "symbolic" ? SYMBOLIC_MORE : [];
  const [moreOpen, setMoreOpen] = React.useState(false);

  // Algebra and numbers are typeset IN the field: the session holds the
  // ASCII the grader reads, the input shows it the way it will be read
  // (x^2 → x², 3e8 → 3×10⁸). A short answer is shown exactly as typed.
  const toShown = (plain: string) =>
    type === "symbolic" ? prettyExpression(plain) : type === "numeric" ? prettyNumber(plain) : plain;
  const toPlain = (shown: string) =>
    type === "symbolic" ? asciiExpression(shown) : type === "numeric" ? asciiNumber(shown) : shown;
  const shown = toShown(value);

  // Typesetting changes the text's length (^2 is two characters, ² is one),
  // so the browser's caret has to be put back where the student was typing.
  const pendingCaret = React.useRef<number | null>(null);
  React.useLayoutEffect(() => {
    const caret = pendingCaret.current;
    if (caret === null) return;
    pendingCaret.current = null;
    inputRef.current?.setSelectionRange(caret, caret);
  }, [shown]);

  /**
   * Store `next` (as typed into the field) and keep the caret after the same
   * character. Counted from the END: what follows the caret is what the
   * student has not touched, so its typeset length is stable even when the
   * character just typed joined an exponent (x² + 3 → x²³).
   */
  const commit = (next: string, caret: number) => {
    const plain = toPlain(next);
    const after = toShown(toPlain(next.slice(caret))).length;
    const target = Math.max(0, toShown(plain).length - after);
    if (plain === value) {
      // Nothing to re-render (the layout effect won't run): place it now.
      inputRef.current?.setSelectionRange(target, target);
      return;
    }
    pendingCaret.current = target;
    onChange(plain);
  };

  /** Put `key` in at the cursor (replacing any selection) and keep typing. */
  const insert = (key: Key) => {
    const input = inputRef.current;
    const start = input?.selectionStart ?? shown.length;
    const end = input?.selectionEnd ?? shown.length;
    // Focus first; the caret is placed by the layout effect, synchronously
    // after the re-render — never on a later frame, which would land after
    // the student's next keystroke and drag the caret back.
    input?.focus();
    commit(shown.slice(0, start) + key.insert + shown.slice(end), start + (key.caret ?? key.insert.length));
  };

  // What the grader will make of it. A good number is read back INSIDE the
  // field (its right end); a problem gets the line under the field. A good
  // expression needs neither — the field already shows it typeset.
  const reading = (() => {
    if (!value.trim()) return null;
    if (type === "numeric") {
      const n = numericValue(value);
      if (n === null) return { ok: false, node: "Not a number the grader can read yet." };
      // Read back in the field's own notation (6.02×10²³, not 6.02e+23), and
      // only when it says something the field doesn't: "15" reads as 15.
      const read = prettyNumber(formatNumber(n).replace("e+", "e"));
      if (read === shown.trim()) return null;
      return { ok: true, node: <>Reads as <span className="quiz-written__value">{read}</span></> };
    }
    if (type === "symbolic") {
      const problem = symbolicProblem(value);
      return problem ? { ok: false, node: problem } : null;
    }
    return null;
  })();

  const readBack = reading && (
    <span
      id="quiz-written-readback"
      className={reading.ok ? "quiz-written__reading" : "quiz-written__readback"}
      data-testid="quiz-written-readback"
      data-ok={reading.ok ? "true" : "false"}
      aria-live="polite"
    >
      {reading.node}
    </span>
  );

  const keyButton = (key: Key) => (
    <button
      key={key.id}
      type="button"
      className="quiz-written__key"
      data-testid={`quiz-key-${key.id}`}
      aria-label={key.ariaLabel}
      disabled={disabled}
      // Keep focus (and the cursor) in the input.
      onMouseDown={event => event.preventDefault()}
      onClick={() => insert(key)}
    >
      {key.label}
    </button>
  );

  return (
    <div className="quiz-written" data-format={type} data-verdict={verdict ?? undefined}>
      <div className="quiz-written__field">
        <input
          ref={inputRef}
          id="quiz-written-answer"
          data-testid="quiz-written-answer"
          type="text"
          className={`field quiz-question__written-input quiz-written__input--${type}`}
          aria-labelledby={labelledBy}
          aria-describedby={reading && !verdict ? `${describedBy} quiz-written-readback` : describedBy}
          aria-invalid={reading && !reading.ok ? true : undefined}
          inputMode={type === "numeric" ? "decimal" : "text"}
          placeholder={PLACEHOLDER[type]}
          maxLength={2000}
          value={shown}
          disabled={disabled}
          onChange={event => {
            const field = event.target;
            commit(field.value, field.selectionStart ?? field.value.length);
          }}
          onKeyDown={event => {
            if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
            event.preventDefault();
            onSubmit();
          }}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={type === "short_answer"}
        />
        {/* Once marked, the result takes the reading's place at the right end.
            Decorative: the verdict's live region announces it. */}
        {verdict ? (
          <span className="quiz-written__status" aria-hidden="true">
            {verdict === "correct" ? "Correct" : "Incorrect"}
            <span className="quiz-written__mark">
              {verdict === "correct" ? <Check size={12} strokeWidth={3} /> : <X size={12} strokeWidth={3} />}
            </span>
          </span>
        ) : reading?.ok && readBack}
      </div>

      {keys.length > 0 && (
        <div className="quiz-written__keys" role="group" aria-label="Insert a symbol">
          {keys.map(key => keyButton(key))}
          {more.length > 0 && (
            <button
              type="button"
              className="quiz-written__key quiz-written__key--toggle"
              data-testid="quiz-key-more"
              aria-expanded={moreOpen}
              aria-controls="quiz-written-more"
              aria-label={moreOpen ? "Hide number keys" : "Show number keys"}
              disabled={disabled}
              onMouseDown={event => event.preventDefault()}
              onClick={() => setMoreOpen(open => !open)}
            >
              123
            </button>
          )}
        </div>
      )}

      {more.length > 0 && moreOpen && (
        <div className="quiz-written__keys" id="quiz-written-more" role="group" aria-label="Insert a number">
          {more.map(key => keyButton(key))}
        </div>
      )}

      {/* A problem with what's typed goes UNDER the keys, so it appearing
          never pushes them out from under the cursor. */}
      {!verdict && reading && !reading.ok && <p className="quiz-written__problem">{readBack}</p>}
    </div>
  );
}
