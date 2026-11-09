import katex from "katex";
import "katex/dist/katex.min.css";
import "katex/contrib/mhchem";
import "./quizMath.css";

const MATH = /\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]/g;

export function QuizMath({ text }: { text: string }) {
  const parts = [];
  let cursor = 0;

  for (const match of text.matchAll(MATH)) {
    const index = match.index;
    parts.push(text.slice(cursor, index));
    cursor = index + match[0].length;
    const displayMode = match[2] !== undefined;

    let html: string;
    try {
      html = katex.renderToString(match[1] ?? match[2], {
        displayMode,
        trust: false,
        maxExpand: 100,
        maxSize: 10,
      });
    } catch (error) {
      if (!(error instanceof katex.ParseError)) throw error;
      parts.push(match[0]);
      continue;
    }
    parts.push(
      <span
        key={index}
        className={displayMode ? "quiz-math-display" : undefined}
        dangerouslySetInnerHTML={{ __html: html }}
      />,
    );
  }

  parts.push(text.slice(cursor));
  return <>{parts}</>;
}
