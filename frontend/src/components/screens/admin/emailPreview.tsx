import React from "react";

/**
 * Client-side preview of how a plain-text admin email renders: blank lines
 * split paragraphs, single newlines become line breaks, and http(s) URLs
 * become links. Everything is built from React elements, so the body's text
 * is always escaped — never `dangerouslySetInnerHTML`.
 *
 * Mirrors `backend/services/email_templates.py::render_plain_text_body`
 * (same URL pattern, trailing-punctuation trim and paren rule); the
 * server-side render is what actually goes out.
 */

const URL_RE = /https?:\/\/[^\s<>"']+/gi;
// Sentence punctuation that trails a URL in prose but is not part of it.
const TRAILING_PUNCT = ".,;:!?)]}'\"";

const count = (s: string, ch: string) => s.split(ch).length - 1;

/** Drop trailing punctuation, keeping a closing paren the URL itself opened. */
function trimUrl(raw: string): string {
  let url = raw;
  while (url && TRAILING_PUNCT.includes(url[url.length - 1])) {
    if (url.endsWith(")") && count(url, "(") >= count(url, ")")) break;
    url = url.slice(0, -1);
  }
  return url;
}

/** Split a plain-text body into paragraphs on blank lines (CRLF-tolerant). */
export function splitParagraphs(body: string): string[] {
  return body
    .replace(/\r\n?/g, "\n")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}

/** One line of text with its URLs turned into anchors. */
export function linkify(line: string, keyPrefix = "l"): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of line.matchAll(URL_RE)) {
    const start = m.index ?? 0;
    const url = trimUrl(m[0]);
    if (start > last) out.push(line.slice(last, start));
    out.push(
      <a key={`${keyPrefix}-${i++}`} href={url} target="_blank" rel="noopener noreferrer">
        {url}
      </a>,
    );
    last = start + url.length;
  }
  if (last < line.length) out.push(line.slice(last));
  return out;
}

export function EmailBodyPreview({ body }: { body: string }) {
  const paragraphs = splitParagraphs(body);
  if (paragraphs.length === 0) {
    return <p style={{ margin: 0, color: "var(--text-muted)" }}>Your message will appear here.</p>;
  }
  return (
    <>
      {paragraphs.map((para, pi) => {
        const lines = para.split("\n");
        return (
          <p key={pi} style={{ margin: "0 0 12px", lineHeight: 1.55, overflowWrap: "anywhere" }}>
            {lines.map((line, li) => (
              <React.Fragment key={li}>
                {li > 0 && <br />}
                {linkify(line, `${pi}-${li}`)}
              </React.Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}
