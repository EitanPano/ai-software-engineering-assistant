"""The scripts of the retrieval work import and are shaped as their docstrings say. None runs here:
two are paid or empty `app_test`, and `check_eval_cases` compares lines with the installed click, a
transitive dependency whose release must not turn `check` red. What `check` holds of it is the case
file's shape and the checking logic, on a synthetic source tree."""

import importlib.metadata
import inspect
import json
from pathlib import Path
from typing import NoReturn

import pytest

from app.infra.scripts import seed_eval_case
from tests import check_eval_cases, live_retrieval, measure_search, seed_eval_fixture

COMMIT = "a" * 40
COUNTS = {"identifier": 1, "paraphrase": 1, "no_answer": 1}
# Lines 1-2 and 5-6 are definitions; line 2 is a body, line 3 and 4 are blank and a comment.
SOURCE = (
    "def alpha_beta(first_arg):\n"
    "    return first_arg\n"
    "\n"
    "# between\n"
    "def gamma_delta(second_arg):\n"
    "    return second_arg\n"
)


def test_check_eval_cases_runs_only_as_a_script_against_the_installed_click() -> None:
    assert inspect.isfunction(check_eval_cases.main)
    assert "free" in str(check_eval_cases.__doc__).lower()
    assert check_eval_cases.PINNED_COMMIT == "8b19813f2bfca99f1018a587a8cf54fc959f2e5d"


def test_the_committed_case_file_has_its_shape_without_any_installed_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: object, **__: object) -> NoReturn:
        raise AssertionError("the shape check must not read the installed click")

    monkeypatch.setattr(importlib.metadata, "version", refuse)
    monkeypatch.setattr(check_eval_cases, "installed_click", refuse)

    file, problems = check_eval_cases.check_shape(check_eval_cases.CASE_FILE)

    assert problems == []
    assert file is not None
    assert file.pinned_commit == check_eval_cases.PINNED_COMMIT
    counts: dict[str, int] = {}
    for entry in file.cases:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    assert counts == check_eval_cases.EXPECTED_COUNTS


def test_the_installed_version_is_compared_only_by_its_own_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    assert check_eval_cases.installed_version_problem() == "installed click is 9.9.9, not 8.5.0"

    monkeypatch.setattr(importlib.metadata, "version", lambda _: check_eval_cases.CLICK_VERSION)
    assert check_eval_cases.installed_version_problem() is None


class TestCheckEvalCases:
    """The checking logic on a synthetic module under `tmp_path`; no installed package is read."""

    @pytest.fixture(autouse=True)
    def no_installed_click(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*_: object, **__: object) -> NoReturn:
            raise AssertionError("a gate test must not read the installed click")

        monkeypatch.setattr(importlib.metadata, "version", refuse)
        monkeypatch.setattr(check_eval_cases, "installed_click", refuse)

    @pytest.fixture
    def root(self, tmp_path: Path) -> Path:
        root = tmp_path / "source"
        root.mkdir()
        (root / "mod.py").write_text(SOURCE, encoding="utf-8")
        return root

    def cases(
        self,
        *,
        commit: str = COMMIT,
        identifier: str = "alpha_beta",
        paraphrase: str = "Hand back what was handed over",
        lines: tuple[int, int] = (1, 2),
        path: str = "src/click/mod.py",
        third: str = "no_answer",
    ) -> dict[str, object]:
        """A valid file of one case per kind over `SOURCE`; the arguments break one thing each."""
        chunk = {"path": path, "startLine": lines[0], "endLine": lines[1]}
        sound = {"path": "src/click/mod.py", "startLine": 1, "endLine": 2}
        return {
            "pinnedCommit": commit,
            "cases": [
                {"kind": "identifier", "question": identifier, "expectedChunks": [chunk]},
                {"kind": "paraphrase", "question": paraphrase, "expectedChunks": [sound]},
                {
                    "kind": third,
                    "question": "Bake sourdough",
                    "expectedChunks": [] if third == "no_answer" else [sound],
                },
            ],
        }

    def problems(self, tmp_path: Path, root: Path, file: dict[str, object]) -> list[str]:
        path = tmp_path / "cases.json"
        path.write_text(json.dumps(file), encoding="utf-8")
        return check_eval_cases.check_file(path, root, commit=COMMIT, counts=COUNTS)

    def test_a_file_that_agrees_with_its_source_has_no_problem(
        self, tmp_path: Path, root: Path
    ) -> None:
        assert self.problems(tmp_path, root, self.cases()) == []

    def test_a_paraphrase_sharing_an_identifier_is_flagged(
        self, tmp_path: Path, root: Path
    ) -> None:
        file = self.cases(paraphrase="Give back first_arg")

        (problem,) = self.problems(tmp_path, root, file)

        assert "shares" in problem

    def test_an_identifier_question_naming_nothing_of_its_lines_is_flagged(
        self, tmp_path: Path, root: Path
    ) -> None:
        file = self.cases(identifier="unrelated words")

        (problem,) = self.problems(tmp_path, root, file)

        assert "names no identifier" in problem

    def test_a_span_past_the_end_or_off_a_definition_is_flagged(
        self, tmp_path: Path, root: Path
    ) -> None:
        (past,) = self.problems(tmp_path, root, self.cases(lines=(100000, 100001)))
        (off,) = self.problems(tmp_path, root, self.cases(lines=(2, 2)))

        assert "the file has 7 lines" in past
        assert "not a definition" in off

    def test_a_span_ending_on_a_blank_line_or_in_a_missing_file_is_flagged(
        self, tmp_path: Path, root: Path
    ) -> None:
        (blank_problem,) = self.problems(tmp_path, root, self.cases(lines=(1, 3)))
        (missing_problem,) = self.problems(tmp_path, root, self.cases(path="src/click/none.py"))

        assert "ends on a blank line" in blank_problem
        assert "no such installed file" in missing_problem

    def test_a_wrong_commit_or_count_is_flagged(self, tmp_path: Path, root: Path) -> None:
        file = self.cases(commit="0" * 40, third="paraphrase")

        problems = self.problems(tmp_path, root, file)

        assert any("pinned to" in problem for problem in problems)
        assert any("cases, expected" in problem for problem in problems)

    def test_a_file_the_seed_would_refuse_is_flagged(self, tmp_path: Path, root: Path) -> None:
        path = tmp_path / "cases.json"
        path.write_text("not json", encoding="utf-8")

        (problem,) = check_eval_cases.check_file(path, root, commit=COMMIT, counts=COUNTS)

        assert "not a valid case file" in problem

    def test_the_guard_fails_when_the_installed_click_is_reached(self) -> None:
        with pytest.raises(AssertionError, match="installed click"):
            importlib.metadata.version("click")
        with pytest.raises(AssertionError, match="installed click"):
            check_eval_cases.installed_click()


def test_the_seed_scripts_are_coroutines_that_run_only_as_scripts() -> None:
    assert inspect.iscoroutinefunction(seed_eval_case.seed)
    assert inspect.iscoroutinefunction(seed_eval_fixture.main)


def test_live_retrieval_imports_and_runs_only_as_a_script() -> None:
    assert inspect.iscoroutinefunction(live_retrieval.main)
    assert "PAID" in str(live_retrieval.__doc__)
    assert live_retrieval.TOP == 5


def test_measure_search_imports_and_runs_only_as_a_script() -> None:
    assert inspect.iscoroutinefunction(measure_search.main)
    assert "EMPTIES" in str(measure_search.__doc__)
    assert measure_search.CHUNKS == 100_000
    assert measure_search.BUDGET_SECONDS == 1.0
