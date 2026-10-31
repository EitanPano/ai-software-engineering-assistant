"""`uv run python -m tests.check_eval_cases`: checks the labelled eval cases of pallets/click 8.5.0
(`src/app/infra/eval_cases/click-8.5.0.json`) against the installed click, whose `<name>.py` is
`src/click/<name>.py` at the tag. Free: no network, no database and no key. Run it before the paid
run, and after any edit to the file. Only `main` reads the installed click and its version, so no
gate depends on a transitive dependency's release: `check` holds the file's shape
(`check_shape`) and the checking logic on a synthetic source tree (`tests/test_search_scripts.py`).

It checks that
- the file is a valid case file (the seed's own schema), pinned to the commit the stored corpus was
  indexed at, with 15 identifier, 15 paraphrase and 10 no_answer cases and distinct questions;
- the installed click is 8.5.0, so its files are the tag's;
- each expected chunk lies inside its installed file and opens at a definition (`def`, `class` or
  a decorator) and ends on a line with text;
- each identifier question names an identifier of the lines it points at, and each paraphrase
  shares none: an identifier is the name of a definition in those lines, a parameter name, or a
  word with an underscore or a capital inside it (compared whole, ignoring case).

Exit 0 when every check holds, 1 with one line per failure.
"""

import ast
import importlib.metadata
import importlib.util
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from app.api.eval.schema import EvalCaseEntry, EvalCaseFile, EvalExpectedChunk

PINNED_COMMIT: Final = "8b19813f2bfca99f1018a587a8cf54fc959f2e5d"
CLICK_VERSION: Final = "8.5.0"
EXPECTED_COUNTS: Final = {"identifier": 15, "paraphrase": 15, "no_answer": 10}
CASE_FILE: Final = (
    Path(__file__).resolve().parents[1] / "src/app/infra/eval_cases" / f"click-{CLICK_VERSION}.json"
)
REPOSITORY_PREFIX: Final = "src/click/"
WORD: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A word that is an identifier whatever the language: an underscore, or a capital after the first.
CODE_WORD: Final = re.compile(r"[A-Za-z0-9]*(_|[a-z][A-Z])[A-Za-z0-9_]*|_[A-Za-z0-9_]*")


def installed_click() -> Path | None:
    spec = importlib.util.find_spec("click")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def identifiers_in(source: str, start: int, end: int) -> set[str]:
    """The identifiers of lines `start` to `end` of a module, lowercased."""
    lines = source.split("\n")[start - 1 : end]
    found = {word.lower() for word in WORD.findall("\n".join(lines)) if CODE_WORD.fullmatch(word)}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if not start <= node.lineno <= end:
            continue
        found.add(node.name.lower())
        if isinstance(node, ast.ClassDef):
            continue
        arguments = node.args
        every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        found |= {argument.arg.lower() for argument in every}
        found |= {a.arg.lower() for a in (arguments.vararg, arguments.kwarg) if a is not None}
    found.discard("self")
    found.discard("cls")
    return found


def check_chunk(root: Path, chunk: EvalExpectedChunk) -> tuple[str | None, set[str]]:
    """A problem with the label, or `None`, and the identifiers of the lines it points at."""
    if not chunk.path.startswith(REPOSITORY_PREFIX):
        return f"{chunk.path}: not under {REPOSITORY_PREFIX}", set()
    file = root / chunk.path.removeprefix(REPOSITORY_PREFIX)
    if not file.is_file():
        return f"{chunk.path}: no such installed file", set()
    source = file.read_text(encoding="utf-8")
    lines = source.split("\n")
    where = f"{chunk.path}:{chunk.start_line}-{chunk.end_line}"
    if chunk.end_line > len(lines):
        return f"{where}: the file has {len(lines)} lines", set()
    opening = lines[chunk.start_line - 1].strip()
    if not opening.startswith(("def ", "class ", "@", "async def ")):
        return f"{where}: opens on {opening[:40]!r}, not a definition", set()
    if not lines[chunk.end_line - 1].strip():
        return f"{where}: ends on a blank line", set()
    return None, identifiers_in(source, chunk.start_line, chunk.end_line)


def check_case(root: Path, entry: EvalCaseEntry) -> list[str]:
    problems: list[str] = []
    labelled: set[str] = set()
    for chunk in entry.expected_chunks:
        problem, names = check_chunk(root, chunk)
        if problem is not None:
            problems.append(problem)
        labelled |= names
    asked = {word.lower() for word in WORD.findall(entry.question)}
    shared = asked & labelled
    if entry.kind == "identifier" and not shared and not problems:
        problems.append("names no identifier of its lines")
    if entry.kind == "paraphrase" and shared:
        problems.append(f"shares {sorted(shared)} with its lines")
    return [f"{entry.kind} {entry.question[:50]!r}: {problem}" for problem in problems]


def installed_version_problem() -> str | None:
    """A problem with the installed click's version. Only the script reads it, so a routine bump of
    a transitive dependency never turns a gate red."""
    try:
        version = importlib.metadata.version("click")
    except importlib.metadata.PackageNotFoundError:
        return "click is not installed"
    return (
        None if version == CLICK_VERSION else f"installed click is {version}, not {CLICK_VERSION}"
    )


def check_shape(
    path: Path,
    *,
    commit: str = PINNED_COMMIT,
    counts: Mapping[str, int] = EXPECTED_COUNTS,
) -> tuple[EvalCaseFile | None, list[str]]:
    """The file, when the seed would accept it, and the problems of its shape. Reads no package."""
    try:
        file = EvalCaseFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        detail = error.errors() if isinstance(error, ValidationError) else error
        return None, [f"{path.name}: not a valid case file: {detail}"]
    problems: list[str] = []
    if file.pinned_commit != commit:
        problems.append(f"pinned to {file.pinned_commit}, not {commit}")
    found = Counter(entry.kind for entry in file.cases)
    if dict(found) != dict(counts):
        problems.append(f"{dict(found)} cases, expected {dict(counts)}")
    return file, problems


def check_file(
    path: Path,
    root: Path,
    *,
    commit: str = PINNED_COMMIT,
    counts: Mapping[str, int] = EXPECTED_COUNTS,
) -> list[str]:
    """Every problem of the file: its shape, and each label against the sources under `root`."""
    file, problems = check_shape(path, commit=commit, counts=counts)
    if file is None:
        return problems
    for entry in file.cases:
        problems += check_case(root, entry)
    return problems


def main(argv: Sequence[str] = ()) -> int:
    path = Path(argv[0]) if argv else CASE_FILE
    root = installed_click()
    version_problem = installed_version_problem()
    problems = [version_problem] if version_problem else []
    if root is None:
        problems.append("click is not installed")
    else:
        problems += check_file(path, root)
    for problem in problems:
        print(problem)
    if not problems:
        print(f"ok: {path.name} holds {sum(EXPECTED_COUNTS.values())} cases that check out")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
