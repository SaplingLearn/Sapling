/** The block glyphs the brand icon set does not have. */

function Glyph({ d }: { d: string }) {
  return (
    <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

export const ChartGlyph = () => <Glyph d="M4 4v16h16M8 15l4-5 3 3 4-6" />;
export const TableGlyph = () => <Glyph d="M4 5h16v14H4zM4 10h16M12 5v14" />;
export const FormulaGlyph = () => <Glyph d="M18 6V5H6l6 7-6 7h12v-1" />;
