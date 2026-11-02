"""type.py belongs: the shapes the index passes between its steps: a text file read from an
archive, a symbol the parse worker found, and a chunk of a file. Lines are 1-based, inclusive, and
numbered on `\\n` only, as tree-sitter and GitHub number them.
It does not belong: the stored records (`interface.py`) or the wire shapes (`api/source/schema.py`).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    """A text file of a repository: its path from the repository root, and its text."""

    path: str
    text: str


@dataclass(frozen=True)
class Symbol:
    """A top-level definition a grammar found: its name (when it has one) and its lines."""

    name: str | None
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Chunk:
    """A piece of a file that is embedded as one text. `content` is the file's lines
    `start_line` to `end_line`, except for a line longer than the chunk bound, which is cut into
    pieces that share its number."""

    symbol: str | None
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True)
class ChunkLines:
    """Where a stored chunk lies: the commit its source was indexed at, the file and the lines
    (1-based, inclusive). No content: a caller that only places chunks never reads one."""

    commit: str
    path: str
    start_line: int
    end_line: int
