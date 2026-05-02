"use client";
import React from "react";
import { CustomSelect } from "../../CustomSelect";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCloze } from "@/lib/api";
import { detectDelimiters, splitByDelimiters, type ParsedCard } from "@/lib/flashcardParsers";

interface Props {
  cards: ParsedCard[];
  onCards: (next: ParsedCard[]) => void;
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

export function PasteTab({ cards, onCards }: Props) {
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

  // Suppress unused warning — cards prop is available to parent via onCards
  void cards;

  const term = termSel === "custom" ? termCustom : termSel;
  const card = cardSel === "custom" ? cardCustom : cardSel;

  // Smart auto-detect on first paste
  React.useEffect(() => {
    if (!text || autoDetectedOnce) return;
    if (text.length < 20) return;
    const detected = detectDelimiters(text);
    setTermSel(detected.term);
    setCardSel(detected.card);
    setAutoDetectedOnce(true);
  }, [text, autoDetectedOnce]);

  // Live re-parse
  React.useEffect(() => {
    if (clozeMode) return;
    if (!text || !term || !card) { onCards([]); return; }
    const parsed = splitByDelimiters(text, term, card);
    onCards(parsed);
  }, [text, term, card, clozeMode, onCards]);

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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, fontSize: 12 }}>
        <button
          className="btn btn--sm"
          onClick={() => setClozeMode(false)}
          style={{ opacity: clozeMode ? 0.5 : 1, fontWeight: clozeMode ? 400 : 600 }}
        >Term / Definition</button>
        <button
          className="btn btn--sm"
          onClick={() => setClozeMode(true)}
          style={{ opacity: clozeMode ? 1 : 0.5, fontWeight: clozeMode ? 600 : 400 }}
        >Cloze deletion (AI)</button>
      </div>

      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={clozeMode
          ? "Paste a paragraph. Claude will pick key terms to remove and generate fill-in-the-blank cards."
          : "Paste your cards here. Use Tab between term and definition, Enter between cards."}
        style={{
          minHeight: 180, padding: 12, borderRadius: "var(--r-md)",
          background: "var(--bg-panel)", border: "1px solid var(--border)",
          color: "var(--text)", fontFamily: "inherit", fontSize: 13, resize: "vertical",
        }}
      />

      {!clozeMode && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 180 }}>
            <div className="label-micro">Between term and definition</div>
            <CustomSelect value={termSel} onChange={setTermSel} options={TERM_OPTIONS} />
            {termSel === "custom" && (
              <input
                value={termCustom}
                onChange={e => setTermCustom(e.target.value)}
                placeholder="Custom separator"
                style={{ marginTop: 4, padding: 6, fontSize: 12, width: "100%" }}
              />
            )}
          </div>
          <div style={{ minWidth: 180 }}>
            <div className="label-micro">Between cards</div>
            <CustomSelect value={cardSel} onChange={setCardSel} options={CARD_OPTIONS} />
            {cardSel === "custom" && (
              <input
                value={cardCustom}
                onChange={e => setCardCustom(e.target.value)}
                placeholder="Custom separator"
                style={{ marginTop: 4, padding: 6, fontSize: 12, width: "100%" }}
              />
            )}
          </div>
        </div>
      )}

      {clozeMode && (
        <button className="btn btn--sm btn--primary" onClick={runCloze} disabled={clozing || !text.trim()}>
          {clozing ? "Generating cloze cards…" : "Generate cloze cards"}
        </button>
      )}
    </div>
  );
}
