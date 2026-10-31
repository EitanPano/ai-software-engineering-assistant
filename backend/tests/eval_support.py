"""Helpers for the eval suites: the fixture repository's labelled cases, built from the fixture's
own constants so no line number is copied, and a case file for a number of generated cases."""

from collections.abc import Mapping

from app.api.eval.schema import EvalCaseFile
from tests.fixture_repository import (
    DOTTED_QUERY,
    EXPECTED_DOTTED,
    EXPECTED_KEYWORD,
    EXPECTED_SEMANTIC,
    FIXTURE_COMMIT,
    KEYWORD_QUERY,
    SEMANTIC_QUERY,
    ExpectedChunk,
)

NO_ANSWER_QUESTION = "how does the limiter talk to a relational database"

type Json = dict[str, object]


def label(expected: ExpectedChunk) -> Json:
    return {
        "path": expected.path,
        "startLine": expected.start_line,
        "endLine": expected.end_line,
    }


def case(kind: str, question: str, *expected: ExpectedChunk) -> Json:
    return {"kind": kind, "question": question, "expectedChunks": [label(e) for e in expected]}


def fixture_cases() -> list[Json]:
    """Two identifiers, a paraphrase and a question the fixture cannot answer."""
    return [
        case("identifier", KEYWORD_QUERY, EXPECTED_KEYWORD),
        case("identifier", DOTTED_QUERY, EXPECTED_DOTTED),
        case("paraphrase", SEMANTIC_QUERY, EXPECTED_SEMANTIC),
        case("no_answer", NO_ANSWER_QUESTION),
    ]


def fixture_file(
    cases: list[Json] | None = None, *, commit: str = FIXTURE_COMMIT
) -> Mapping[str, object]:
    """A case file as the seed command reads it, before validation."""
    return {"pinnedCommit": commit, "cases": fixture_cases() if cases is None else cases}


def fixture_case_file(
    cases: list[Json] | None = None, *, commit: str = FIXTURE_COMMIT
) -> EvalCaseFile:
    return EvalCaseFile.model_validate(fixture_file(cases, commit=commit))


def generated_cases(count: int) -> list[Json]:
    """`count` identifier cases with distinct questions, all labelled with one fixture chunk."""
    return [
        case("identifier", f"{KEYWORD_QUERY} variant {n}", EXPECTED_KEYWORD) for n in range(count)
    ]
