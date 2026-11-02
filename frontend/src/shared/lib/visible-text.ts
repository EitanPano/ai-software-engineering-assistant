// Repository text (a chunk, a tool's input or output) comes from a repository anyone can publish,
// so none of it is trusted. Bidi controls could make a path or a line read as something else, and
// other invisible or control characters hide content (or smuggle instructions the model reads and
// the person cannot see), so they are shown as `[U+XXXX]` instead of obeyed: controls, format
// characters (bidi, zero width, tags), line and paragraph separators, and every default-ignorable
// code point (soft hyphen, fillers, variation selectors). Newline and tab stay, and a carriage
// return before a newline is dropped (a CRLF file), a lone one shown.
const HIDDEN = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Default_Ignorable_Code_Point}]/u

export function visibleText(text: string): string {
  let shown = ''
  for (const char of text.replace(/\r\n/g, '\n')) {
    const code = char.codePointAt(0) ?? 0
    shown +=
      char !== '\t' && char !== '\n' && HIDDEN.test(char)
        ? `[U+${code.toString(16).toUpperCase().padStart(4, '0')}]`
        : char
  }
  return shown
}
