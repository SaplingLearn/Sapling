"use client";
import React from "react";
import { Icon } from "@/components/Icon";

/**
 * SearchField — the one search input.
 *
 * An audit (Trov handoff #35) found 19 private copies: Library, Study Guides,
 * Quiz, Tree, Social, Notetaker ×2, five admin fields, three course pickers,
 * Learn, Wiki and News. They had 10 heights, 3 magnifier drawings, 6 focus
 * treatments (two of them invisible), and nine were named only by their
 * placeholder. This is the shared one: the framed look of the rebuilt
 * Library header, on tokens the way the Study Guides toolbar already was.
 *
 * The wrapper owns the chrome and the focus ring (`:focus-within`, so the
 * ring shows however the input got focus); the input is bare and fills it.
 * It is `type="search"` with the WebKit × hidden, because the field draws
 * its own clear button.
 *
 * Esc is two-step. With text in the field, Esc clears it and stops there:
 * `preventDefault` + `stopPropagation`, so a modal, a Sheet or onboarding's
 * window handler does not also close or go Back. With the field empty, Esc
 * is left alone and bubbles to whatever owns it.
 *
 * Presentational and controlled: `onChange` fires on every keystroke.
 * Fetching, race guards and matching stay with the caller; a server search
 * listens on `onDebouncedChange` instead. It is NOT a combobox — a picker
 * that needs one passes its `role`/`aria-*` through `inputProps`.
 */
export interface SearchFieldProps {
  value: string;
  /** Every keystroke, never debounced. Also called with "" on clear. */
  onChange: (value: string) => void;
  /** Required: the input's accessible name. The placeholder never is. */
  label: string;
  placeholder?: string;
  /** 32 / 40 / 50px. `sm` for toolbars and tables, `lg` for page heroes. */
  size?: "sm" | "md" | "lg";
  /** `bare` drops the border, fill and height so a host bar can draw them
   *  (style the host's `:focus-within`, or focus will be invisible). */
  variant?: "field" | "bare";
  /** Show the × while there is text. Default true. */
  clearable?: boolean;
  /** Esc clears when there is text (see above). Default true. */
  escapeClears?: boolean;
  /** "/" anywhere outside an editable field focuses this one; shows a hint. */
  shortcut?: "/";
  /** For server searches: fires `debounceMs` after typing stops, and at
   *  once when the field is cleared. Not on mount. */
  onDebouncedChange?: (value: string) => void;
  /** Default 200. */
  debounceMs?: number;
  /** Swaps the magnifier for a spinner and sets `aria-busy`. */
  loading?: boolean;
  /** A visually hidden polite live region, e.g. "4 guides found" or the
   *  no-results copy. Pass it from the first render (even as "") so the
   *  region exists before it first changes. */
  status?: string;
  /** Controls inside the field, before the × (the Library's Sort/Type). */
  trailing?: React.ReactNode;
  /** Wrap in `role="search"`: page-level fields only, one per page. */
  landmark?: boolean;
  autoFocus?: boolean;
  inputRef?: React.Ref<HTMLInputElement>;
  /** Runs before the built-in keys; `preventDefault()` skips them. */
  onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>;
  inputProps?: Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    "value" | "onChange" | "type" | "onKeyDown" | "placeholder" | "autoFocus"
  >;
  /** On the native <input> (tests fire change on it); the × is `${testid}-clear`. */
  testid?: string;
  /** Layout only — never the field's own look. It fills a flex row by
   *  default (`flex: 1 1 auto`); narrow it here (e.g. `flex: 0 1 354px`). */
  className?: string;
  style?: React.CSSProperties;
}

const ICON_SIZE = { sm: 14, md: 16, lg: 18 } as const;

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
}

function assignRef<T>(ref: React.Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") ref(value);
  else if (ref) (ref as React.MutableRefObject<T | null>).current = value;
}

/** Fires `onDebouncedChange` once typing settles; never for the mount value. */
function useDebouncedEmit(
  value: string,
  onDebouncedChange: ((value: string) => void) | undefined,
  debounceMs: number,
) {
  const latest = React.useRef(onDebouncedChange);
  // Declared before the timer effect, so it has run by the time that one does.
  React.useEffect(() => {
    latest.current = onDebouncedChange;
  });
  const emitted = React.useRef(value);
  const timer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  React.useEffect(() => {
    if (!latest.current || value === emitted.current) return;
    timer.current = setTimeout(() => {
      emitted.current = value;
      latest.current?.(value);
    }, debounceMs);
    return () => clearTimeout(timer.current);
  }, [value, debounceMs]);

  /** Clearing should not wait out the debounce. */
  return React.useCallback(() => {
    clearTimeout(timer.current);
    if (!latest.current || emitted.current === "") return;
    emitted.current = "";
    latest.current("");
  }, []);
}

export function SearchField({
  value,
  onChange,
  label,
  placeholder,
  size = "md",
  variant = "field",
  clearable = true,
  escapeClears = true,
  shortcut,
  onDebouncedChange,
  debounceMs = 200,
  loading = false,
  status,
  trailing,
  landmark = false,
  autoFocus,
  inputRef,
  onKeyDown,
  inputProps,
  testid,
  className,
  style,
}: SearchFieldProps) {
  const ownRef = React.useRef<HTMLInputElement | null>(null);
  const setRef = React.useCallback(
    (el: HTMLInputElement | null) => {
      ownRef.current = el;
      assignRef(inputRef, el);
    },
    [inputRef],
  );
  const emitCleared = useDebouncedEmit(value, onDebouncedChange, debounceMs);

  const clear = () => {
    onChange("");
    emitCleared();
  };

  React.useEffect(() => {
    if (shortcut !== "/") return;
    const onWindowKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.defaultPrevented || isEditable(e.target)) return;
      e.preventDefault();
      ownRef.current?.focus();
    };
    window.addEventListener("keydown", onWindowKey);
    return () => window.removeEventListener("keydown", onWindowKey);
  }, [shortcut]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    onKeyDown?.(e);
    if (e.defaultPrevented) return;
    if (e.key === "Escape" && escapeClears && value !== "") {
      e.preventDefault();
      e.stopPropagation();
      clear();
    }
  };

  // A press on the wrapper's own padding (not the input, not a trailing
  // control) focuses the input, as a <label> would — without being one,
  // since a label may not contain the trailing buttons.
  const onWrapperMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    e.preventDefault();
    ownRef.current?.focus();
  };

  const iconSize = ICON_SIZE[size];
  const classes = [
    "search-field",
    `search-field--${size}`,
    variant === "bare" ? "search-field--bare" : "",
    className ?? "",
  ].filter(Boolean).join(" ");
  const showClear = clearable && value !== "";

  return (
    <div
      className={classes}
      style={style}
      role={landmark ? "search" : undefined}
      onMouseDown={onWrapperMouseDown}
    >
      <span className="search-field__icon" aria-hidden="true">
        {loading ? (
          <span
            className="search-field__spinner"
            style={{ width: iconSize - 2, height: iconSize - 2 }}
          />
        ) : (
          <Icon name="search" size={iconSize} />
        )}
      </span>
      <input
        {...inputProps}
        ref={setRef}
        type="search"
        className="search-field__input"
        data-testid={testid}
        aria-label={label}
        aria-busy={loading || undefined}
        aria-keyshortcuts={shortcut}
        autoComplete={inputProps?.autoComplete ?? "off"}
        placeholder={placeholder}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
      />
      {trailing != null && <div className="search-field__trailing">{trailing}</div>}
      {showClear && (
        <button
          type="button"
          className="search-field__clear"
          aria-label="Clear search"
          data-testid={testid ? `${testid}-clear` : undefined}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            clear();
            ownRef.current?.focus();
          }}
        >
          <Icon name="x" size={size === "sm" ? 10 : 12} />
        </button>
      )}
      {shortcut && !showClear && (
        <kbd className="search-field__kbd" aria-hidden="true" title={`Press ${shortcut} to search`}>
          {shortcut}
        </kbd>
      )}
      {status !== undefined && (
        <span className="search-field__status" role="status">
          {status}
        </span>
      )}
    </div>
  );
}
