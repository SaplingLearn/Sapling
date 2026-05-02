import Papa from "papaparse";

export interface ParsedCard {
  front: string;
  back: string;
  row: number;
  error?: string;
}

export type Delim = "\t" | "," | "\n" | ";" | string;

export interface DelimChoice {
  term: Delim;
  card: Delim;
}

const TERM_CANDIDATES: Delim[] = ["\t", ",", " - "];
const CARD_CANDIDATES: Delim[] = ["\n\n", "\n", ";"];

/** Sniff the most likely term/card separators. Picks the combo that yields
 *  the highest fraction of rows with exactly two non-empty fields. */
export function detectDelimiters(text: string): DelimChoice {
  const sample = text.trim();
  if (!sample) return { term: "\t", card: "\n" };

  let best: DelimChoice = { term: "\t", card: "\n" };
  let bestScore = -1;

  for (const card of CARD_CANDIDATES) {
    const lines = sample.split(card).map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) continue;
    for (const term of TERM_CANDIDATES) {
      const valid = lines.filter(l => {
        const parts = l.split(term);
        return parts.length >= 2 && parts[0].trim() && parts.slice(1).join(term).trim();
      }).length;
      const score = valid / lines.length;
      if (score > bestScore) {
        bestScore = score;
        best = { term, card };
      }
    }
  }
  return bestScore >= 0.8 ? best : { term: "\t", card: "\n" };
}

export function splitByDelimiters(text: string, term: Delim, card: Delim): ParsedCard[] {
  const out: ParsedCard[] = [];
  const lines = text.split(card).map(l => l.replace(/\r$/, ""));
  let row = 0;
  for (const line of lines) {
    if (!line.trim()) continue;
    row += 1;
    const idx = line.indexOf(term);
    if (idx === -1) {
      out.push({ front: line.trim(), back: "", row, error: "Missing definition" });
      continue;
    }
    const front = line.slice(0, idx).trim();
    const back = line.slice(idx + term.length).trim();
    if (!front || !back) {
      out.push({ front, back, row, error: "Front or back is empty" });
    } else {
      out.push({ front, back, row });
    }
  }
  return out;
}

export function parseCSV(text: string): ParsedCard[] {
  const result = Papa.parse<string[]>(text, { skipEmptyLines: true });
  return result.data.map((row, i) => {
    const front = (row[0] ?? "").trim();
    const back = (row[1] ?? "").trim();
    const error = front && back ? undefined : "CSV row needs at least 2 columns";
    return { front, back, row: i + 1, error };
  });
}

export function parseTSV(text: string): ParsedCard[] {
  const result = Papa.parse<string[]>(text, { delimiter: "\t", skipEmptyLines: true });
  return result.data.map((row, i) => {
    const front = (row[0] ?? "").trim();
    const back = (row[1] ?? "").trim();
    const error = front && back ? undefined : "TSV row needs at least 2 columns";
    return { front, back, row: i + 1, error };
  });
}

export function parseJSON(text: string): ParsedCard[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return [{ front: "", back: "", row: 1, error: "Invalid JSON" }];
  }
  if (!Array.isArray(data)) {
    return [{ front: "", back: "", row: 1, error: "Expected a JSON array" }];
  }
  return data.map((item, i) => {
    const obj = (item ?? {}) as Record<string, unknown>;
    const front = String(obj.front ?? obj.term ?? "").trim();
    const back = String(obj.back ?? obj.definition ?? "").trim();
    const error = front && back ? undefined : "Each item needs front+back or term+definition";
    return { front, back, row: i + 1, error };
  });
}

export function isValid(card: ParsedCard): boolean {
  return !card.error && !!card.front && !!card.back;
}
