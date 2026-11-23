const pairs: Record<string, string> = { "{": "}", "[": "]", "(": ")", '"': '"', "'": "'", "`": "`" };

function insideFence(text: string, position: number): boolean {
  const lineStart = text.lastIndexOf("\n", position - 1) + 1;
  let fence = "";
  for (const line of text.slice(0, lineStart).split("\n")) {
    const match = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (!match) continue;
    if (!fence) {
      fence = match[1];
    } else if (match[1][0] === fence[0] && match[1].length >= fence.length && !match[2].trim()) {
      fence = "";
    }
  }
  const lineEnd = text.indexOf("\n", lineStart);
  const currentLine = text.slice(lineStart, lineEnd === -1 ? text.length : lineEnd);
  const closer = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(currentLine)?.[1];
  return Boolean(fence) && !(closer && closer[0] === fence[0] && closer.length >= fence.length);
}

export function codeEdit(text: string, start: number, end: number, key: string, shift: boolean) {
  const close = pairs[key];
  const isClosing = Object.values(pairs).includes(key);
  if (!close && !isClosing && key !== "Tab") return;
  if (!insideFence(text, start) || !insideFence(text, end)) return;
  const replace = (value: string, selectionStart: number, selectionEnd = selectionStart) => ({
    body: text.slice(0, start) + value + text.slice(end),
    start: selectionStart,
    end: selectionEnd,
  });
  if (key === "Tab") {
    if (!shift) return replace("  " + text.slice(start, end), start + 2, end + 2);
    const lineStart = text.lastIndexOf("\n", start - 1) + 1;
    const indent = /^ {1,2}/.exec(text.slice(lineStart, start))?.[0].length ?? 0;
    if (indent) return {
      body: text.slice(0, lineStart) + text.slice(lineStart + indent),
      start: start - indent,
      end: end - indent,
    };
    return;
  }
  if (start === end && text[start] === key && isClosing) {
    return { body: text, start: start + 1, end: start + 1 };
  }
  if (close) return replace(key + text.slice(start, end) + close, start + 1, end + 1);
}

export function overlapsNoteBlock(text: string, start: number, end: number): boolean {
  let offset = 0;
  let fence = "";
  for (const line of text.split("\n")) {
    const lineEnd = offset + line.length;
    const opening = /^ {0,3}(`{3,}|~{3,}|[$]{2,})(.*)$/.exec(line);
    const marker = opening?.[1];
    const rest = opening?.[2].trim();
    const closes = Boolean(fence && marker && marker[0] === fence[0] && marker.length >= fence.length && !rest);
    if ((fence || opening) && (closes ? start < lineEnd : start <= lineEnd) && (start === end || end > offset)) {
      return true;
    }
    if (closes) fence = "";
    else if (!fence && marker && (!marker.startsWith("$") || !rest)) fence = marker;
    offset = lineEnd + 1;
    if (offset > end) break;
  }
  return false;
}
