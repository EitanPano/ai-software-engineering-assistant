"""parse_worker.py belongs: the child process that runs tree-sitter, and nothing else. It is the
only importer of `tree_sitter`. `services/parse.py` starts it
(`python -m app.services.parse_worker`) with a minimal environment and talks to it over its pipes:
one JSON line in, one JSON line out, per file. Why a process: a parse holds the GIL for as long as
it lasts, cannot be interrupted, and its time grows about with the square of a crafted file's size,
so in the API process one hostile file would stall the server that streams chat. The parent kills
this process at a deadline.

The isolation is deliberate and small: this module imports nothing of the app (not `app.config`, so
this code never reads a secret), opens no file and no socket, and reads only its stdin. It is
isolation, not a sandbox: the child runs as the API's user, and on Linux a same-user process may
read its parent's environment (`/proc/<pid>/environ`), where the secrets are, so code running in
this child would reach them. What the process boundary buys is that a hostile file cannot stall
the server, and that a crash here is only a fallback to line windows.

Protocol, requests (UTF-8 JSON, one per line):

- `{"op": "parse", "language": "python" | "javascript" | "typescript" | "tsx", "source": "..."}`
  answers `{"symbols": [[name | null, start_line, end_line], ...]}`, lines 1-based and inclusive,
  or `{"error": "language" | "syntax" | "internal"}`. A tree with a syntax error gives no symbols:
  the caller falls back to line windows.
- `{"op": "inspect"}` answers `{"modules": [...], "environment": {...}}`, what the isolation tests
  read.

The first line it writes is `{"ready": true, "pid": <its process id>}`, once its grammars are
loaded.
It does not belong: chunking (`services/chunk.py`) or the deadline and restarts
(`services/parse.py`).
"""

import json
import os
import sys
from typing import Final

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

type Json = dict[str, object]

_LANGUAGES: Final = {
    "python": Language(tree_sitter_python.language()),
    "javascript": Language(tree_sitter_javascript.language()),
    "typescript": Language(tree_sitter_typescript.language_typescript()),
    "tsx": Language(tree_sitter_typescript.language_tsx()),
}

_SCRIPT_DEFINITIONS: Final = frozenset(
    {"function_declaration", "generator_function_declaration", "class_declaration"}
)
_TYPED_DEFINITIONS: Final = _SCRIPT_DEFINITIONS | {
    "abstract_class_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
    "module",
    "internal_module",
}
_DEFINITIONS: Final = {
    "python": frozenset({"function_definition", "class_definition"}),
    "javascript": _SCRIPT_DEFINITIONS,
    "typescript": _TYPED_DEFINITIONS,
    "tsx": _TYPED_DEFINITIONS,
}
# `const f = () => ...` names a function; `const n = 1` is not a definition worth a chunk.
_FUNCTION_VALUES: Final = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function", "class"}
)


def _text(node: Node | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.decode("utf-8", errors="replace")


def _definition(node: Node, language: str) -> tuple[bool, str | None]:
    """Whether `node` is a definition, and its name."""
    kind = node.type
    if kind in _DEFINITIONS[language]:
        return True, _text(node.child_by_field_name("name"))
    if kind == "decorated_definition":
        inner = node.child_by_field_name("definition")
        return (False, None) if inner is None else _definition(inner, language)
    if kind == "export_statement":
        inner = node.child_by_field_name("declaration")
        return (False, None) if inner is None else _definition(inner, language)
    if kind in {"lexical_declaration", "variable_declaration"}:
        for child in node.named_children:
            value = child.child_by_field_name("value")
            if (
                child.type == "variable_declarator"
                and value is not None
                and (value.type in _FUNCTION_VALUES)
            ):
                return True, _text(child.child_by_field_name("name"))
    return False, None


def _lines(node: Node) -> tuple[int, int]:
    # Never `.row` or `.column`: on a `tree_sitter.Point` of tree-sitter 0.26.0 those getters
    # corrupt memory for a value of 257 or more (a use-after-free that kills the child, or answers
    # wrong numbers first). Indexing and unpacking the same tuple are safe. A definition ending
    # past line 256 is ordinary, and the fixtures were short, so a test parses long modules.
    start_row = node.start_point[0]
    end_row, end_column = node.end_point
    start = start_row + 1
    end = end_row + 1
    # A node that ends at the start of a line does not own that line.
    if end_column == 0 and end > start:
        end -= 1
    return start, end


def _parse(language: str, source: str) -> Json:
    grammar = _LANGUAGES.get(language)
    if grammar is None:
        return {"error": "language"}
    tree = Parser(grammar).parse(source.encode("utf-8"))
    if tree.root_node.has_error:
        return {"error": "syntax"}
    symbols: list[list[object]] = []
    for node in tree.root_node.named_children:
        found, name = _definition(node, language)
        if found:
            start, end = _lines(node)
            symbols.append([name, start, end])
    return {"symbols": symbols}


def _inspect() -> Json:
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    entry = getattr(spec, "name", None)
    modules = sorted(name for name in sys.modules if name == "app" or name.startswith("app."))
    if isinstance(entry, str) and entry not in modules:
        modules.append(entry)
    return {"modules": modules, "environment": dict(os.environ)}


def _answer(line: bytes) -> Json:
    try:
        request = json.loads(line)
    except ValueError:
        return {"error": "internal"}
    if not isinstance(request, dict):
        return {"error": "internal"}
    operation = request.get("op")
    if operation == "inspect":
        return _inspect()
    language, source = request.get("language"), request.get("source")
    if operation != "parse" or not isinstance(language, str) or not isinstance(source, str):
        return {"error": "internal"}
    try:
        return _parse(language, source)
    except Exception as error:
        # The class only: stderr is not read, and the parent logs this as the one trace.
        return {"error": "internal", "type": type(error).__name__}


def _send(message: Json) -> None:
    sys.stdout.buffer.write(json.dumps(message).encode("ascii") + b"\n")
    sys.stdout.buffer.flush()


def main() -> None:
    # The pid: on Windows a virtual environment's `python.exe` starts the real interpreter as its
    # own child, and the parent ends both.
    _send({"ready": True, "pid": os.getpid()})
    while line := sys.stdin.buffer.readline():
        _send(_answer(line))


if __name__ == "__main__":
    main()
