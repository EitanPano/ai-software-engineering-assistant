"""chunk.py belongs: splitting a file's text into the pieces that are embedded. Pure: no I/O, no
state. The symbols come from `services/parse.py`; this module only decides the pieces.

A file with symbols gets one chunk per symbol, and the code between symbols (imports, comments,
top-level statements) gets overlapping line windows. A file with no symbols (an unknown language, a
syntax error, a parse deadline, a spent budget) is line windows throughout, and so is a symbol over
the chunk bound. A window is at most `window_lines` lines and `max_chars` characters, and starts
`overlap_lines` before the previous one ended, but never behind half of the previous one's length,
so a line is not embedded again and again. The ratio of embedded to input text is 2.0 on uniform
lines and 3.28 on the worst pattern measured; it is not bounded by this module. The cost is bounded
by `IndexCaps.chunks` and `embedded_chars`, which the controller counts.

Lines are split on `\\n` only, as tree-sitter and GitHub number them: `str.splitlines` would also
split at a form feed or a vertical tab and shift every number after it. A chunk's `content` is
exactly its lines, joined with `\\n`; the one exception is a single line longer than the bound,
which is cut into pieces that share its number, so no chunk exceeds the bound.
It does not belong: parsing (`services/parse.py`), embedding (`services/voyage.py`) or storage.
"""

from collections.abc import Sequence
from typing import Final

from app.config.constants import CHUNK_BOUNDS, ChunkBounds
from app.models.source.type import Chunk, Symbol

_SUFFIX_LANGUAGE: Final = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
}


def language_of(path: str) -> str | None:
    """The grammar for a path, or `None` for a file with no grammar."""
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return None if dot < 0 else _SUFFIX_LANGUAGE.get(name[dot:].lower())


def chunk_text(
    text: str, symbols: Sequence[Symbol] | None, bounds: ChunkBounds = CHUNK_BOUNDS
) -> list[Chunk]:
    """The chunks of `text`; `symbols` is `None` when the file has none to split by."""
    lines = text.split("\n")
    if not symbols:
        return _windows(lines, 0, len(lines) - 1, None, bounds)
    chunks: list[Chunk] = []
    next_line = 0  # the first line (0-based) not yet covered
    for symbol in sorted(symbols, key=lambda s: (s.start_line, s.end_line)):
        first, last = symbol.start_line - 1, min(symbol.end_line, len(lines)) - 1
        if first < next_line or first > last:
            continue  # inside the previous symbol, or not a range
        chunks += _windows(lines, next_line, first - 1, None, bounds)
        content = "\n".join(lines[first : last + 1])
        if len(content) <= bounds.max_chars:
            chunks.append(Chunk(symbol.name, first + 1, last + 1, content))
        else:
            chunks += _windows(lines, first, last, symbol.name, bounds)
        next_line = last + 1
    chunks += _windows(lines, next_line, len(lines) - 1, None, bounds)
    return chunks


def _windows(
    lines: list[str], first: int, last: int, symbol: str | None, bounds: ChunkBounds
) -> list[Chunk]:
    """Windows over lines `first` to `last` (0-based, inclusive), blank lines trimmed off both
    ends; nothing for a range with no text."""
    while first <= last and not lines[first].strip():
        first += 1
    while last >= first and not lines[last].strip():
        last -= 1
    chunks: list[Chunk] = []
    start = first
    while start <= last:
        end = start
        size = len(lines[start])
        while (
            end < last
            and end - start + 1 < bounds.window_lines
            and size + 1 + len(lines[end + 1]) <= bounds.max_chars
        ):
            end += 1
            size += 1 + len(lines[end])
        if end == start and len(lines[start]) > bounds.max_chars:
            chunks += _pieces(lines[start], start + 1, symbol, bounds)
        else:
            chunks.append(Chunk(symbol, start + 1, end + 1, "\n".join(lines[start : end + 1])))
        if end >= last:
            break
        # The overlap, but never more than half the window: a window the character bound ended
        # at a few lines would otherwise advance by one and embed every line again and again.
        start = max(end - bounds.overlap_lines + 1, start + (end - start + 2) // 2)
    return chunks


def _pieces(line: str, number: int, symbol: str | None, bounds: ChunkBounds) -> list[Chunk]:
    """A line longer than the bound, cut into pieces of at most the bound that share its number."""
    return [
        Chunk(symbol, number, number, line[offset : offset + bounds.max_chars])
        for offset in range(0, len(line), bounds.max_chars)
    ]
