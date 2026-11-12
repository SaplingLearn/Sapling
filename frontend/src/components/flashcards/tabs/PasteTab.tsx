"use client";
import React from "react";
import { CustomSelect } from "../../CustomSelect";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCloze } from "@/lib/api";
import { detectDelimiters, splitByDelimiters, type ParsedCard } from "@/lib/flashcardParsers";
import { pastePlaceholder } from "../importModalModel";
import s from "../FlashcardImportModal.module.css";

interface Props {
  cards: ParsedCard[];
  onCards: (next: ParsedCard[]) => void;
  /** The textarea, so the modal can put focus there when it opens. */
  textareaRef?: React.Ref<HTMLTextAreaElement>;
}

const TERM_OPTIONS = [
  { value: "\t", label: "Tab" },
  { value: ",", label: "Comma" },
  { value: " - ", label: "Hyphen" },
  { value: "custom", label: "Custom…" },
];

const CARD_OPTIONS = [
  { value: "\n", label: "New line" },
  { value: "\n\n", label: "Blank line" },
  { value: ";", label: "Semicolon" },
  { value: "custom", label: "Custom…" },
];

const CLOZE_PLACEHOLDER =
  "Paste a paragraph. Claude will pick key terms to remove and generate fill-in-the-blank cards.";

interface SeparatorProps {
  /** The words before the select: the pairs read as one sentence. */
  label: string;
  /** The select's accessible name. */
  name: string;
  value: string;
  onChange: (next: string) => void;
  options: { value: string; label: string }[];
}

function SeparatorPair({ label, name, value, onChange, options }: SeparatorProps) {
  return (
    <span className={s.pair}>
      <span className={s.pairLabel} aria-hidden="true">{label}</span>
      <CustomSelect
        className={`${s.select} ${s.pairSelect}`}
        size="sm"
        ariaLabel={name}
        value={value}
        onChange={onChange}
        options={options}
      />
    </span>
  );
}

function CustomSeparator({ name, value, onChange }: { name: string; value: string; onChange: (next: string) => void }) {
  return (
    <input
      className={s.input}
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder="Custom separator"
      aria-label={`Custom separator ${name.toLowerCase()}`}
    />
  );
}

export function PasteTab({ cards, onCards, textareaRef }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [text, setText] = React.useState("");
  const [termSel, setTermSel] = React.useState<string>("\t");
  const [cardSel, setCardSel] = React.useState<string>("\n");
  const [termCustom, setTermCustom] = React.useState("");
  const [cardCustom, setCardCustom] = React.useState("");
  const [autoDetectedOnce, setAutoDetectedOnce] = React.useState(false);
  const [clozeMode, setClozeMode] = React.useState(false);
  const [clozing, setClozing] = React.useState(false);
  // True once the user has typed in THIS mount. The import tabs share one
  // deck via onCards, and the modal remounts tabs on every switch — without
  // this guard the live re-parse effect fires onCards([]) on a bare mount
  // (text starts empty) and wipes a deck built on another tab (#183).
  const dirtyRef = React.useRef(false);

  // Suppress unused warning — cards prop is available to parent via onCards
  void cards;

  const term = termSel === "custom" ? termCustom : termSel;
  const card = cardSel === "custom" ? cardCustom : cardSel;

  /** The text as last typed, for the re-parse that a separator change asks for. */
  const textRef = React.useRef("");
  const emit = React.useCallback((nextText: string, t: string, c: string) => {
    onCards(!nextText || !t || !c ? [] : splitByDelimiters(nextText, t, c));
  }, [onCards]);

  // Typing re-parses from the handler itself, in the same update as the text.
  // (It used to be an effect on `text`, which put a second, commit-phase
  // update behind every keystroke; a burst of input, such as a script typing
  // a deck out, piled those up until React stopped it with "Maximum update
  // depth exceeded" and a keystroke was lost.) The first 20 characters also
  // settle the separators, once.
  const typed = (next: string) => {
    dirtyRef.current = true;
    textRef.current = next;
    setText(next);
    let t = term;
    let c = card;
    if (!autoDetectedOnce && next.length >= 20) {
      const detected = detectDelimiters(next);
      setTermSel(detected.term);
      setCardSel(detected.card);
      setAutoDetectedOnce(true);
      t = detected.term;
      c = detected.card;
    }
    if (!clozeMode) emit(next, t, c);
  };

  // A separator or the mode changed: re-parse what is there. Only after the
  // user has typed here, so a bare (re)mount never clears the shared deck.
  React.useEffect(() => {
    if (clozeMode || !dirtyRef.current) return;
    emit(textRef.current, term, card);
  }, [term, card, clozeMode, emit]);

  const runCloze = async () => {
    if (!userId || !text.trim()) return;
    setClozing(true);
    try {
      const res = await importCloze(userId, text);
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Generated ${res.cards.length} cloze cards.`);
    } catch (err) {
      toast.error(`Cloze failed: ${String(err)}`);
    } finally {
      setClozing(false);
    }
  };

  const customTerm = !clozeMode && termSel === "custom";
  const customCard = !clozeMode && cardSel === "custom";

  return (
    <div className={s.tab}>
      <textarea
        ref={textareaRef}
        className={s.textarea}
        value={text}
        onChange={e => typed(e.target.value)}
        placeholder={clozeMode
          ? CLOZE_PLACEHOLDER
          : pastePlaceholder({ choice: termSel, custom: termCustom }, { choice: cardSel, custom: cardCustom })}
      />

      <div className={s.options}>
        <div className={`${s.seg} ${s.segInline}`} role="group" aria-label="Card format">
          <button type="button" className={s.segOpt} aria-pressed={!clozeMode} onClick={() => setClozeMode(false)}>
            Term / Definition
          </button>
          <button type="button" className={s.segOpt} aria-pressed={clozeMode} onClick={() => setClozeMode(true)}>
            Cloze deletion (AI)
          </button>
        </div>

        {clozeMode ? (
          <button type="button" className={`btn btn--primary ${s.go}`} onClick={runCloze} disabled={clozing || !text.trim()}>
            {clozing ? "Generating cloze cards…" : "Generate cloze cards"}
          </button>
        ) : (
          <div className={s.pairs}>
            <SeparatorPair
              label="Split terms by"
              name="Between term and definition"
              value={termSel}
              onChange={setTermSel}
              options={TERM_OPTIONS}
            />
            <SeparatorPair
              label="and cards by"
              name="Between cards"
              value={cardSel}
              onChange={setCardSel}
              options={CARD_OPTIONS}
            />
          </div>
        )}
      </div>

      {(customTerm || customCard) && (
        <div className={s.customs}>
          {customTerm && <CustomSeparator name="Between term and definition" value={termCustom} onChange={setTermCustom} />}
          {customCard && <CustomSeparator name="Between cards" value={cardCustom} onChange={setCardCustom} />}
        </div>
      )}
    </div>
  );
}
