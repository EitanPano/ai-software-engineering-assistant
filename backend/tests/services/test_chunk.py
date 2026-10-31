"""Chunking by symbol, and by overlapping line windows where there is no symbol (V05)."""

import itertools
import random
from collections.abc import Iterator

import pytest

from app.config.constants import CHUNK_BOUNDS, ChunkBounds, ParseLimits
from app.models.source.type import Chunk, Symbol
from app.services.chunk import chunk_text, language_of
from app.services.parse import ParseSession
from tests.fixture_repository import (
    JAVASCRIPT_SOURCE,
    PYTHON_SOURCE,
    TSX_SOURCE,
    TYPESCRIPT_SOURCE,
)

SMALL = ChunkBounds(max_chars=200, window_lines=5, overlap_lines=2)


def assert_faithful(text: str, chunks: list[Chunk]) -> None:
    """Each chunk is exactly its lines, and every non-blank line is in some chunk."""
    lines = text.split("\n")
    covered: set[int] = set()
    for chunk in chunks:
        assert chunk.content == "\n".join(lines[chunk.start_line - 1 : chunk.end_line]), chunk
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines)
        covered.update(range(chunk.start_line, chunk.end_line + 1))
    missing = [n for n, line in enumerate(lines, 1) if line.strip() and n not in covered]
    assert missing == []


@pytest.fixture
def session() -> Iterator[ParseSession]:
    with ParseSession() as opened:
        yield opened


class TestLanguageOf:
    @pytest.mark.parametrize(
        ("path", "language"),
        [
            ("a.py", "python"),
            ("pkg/a.pyi", "python"),
            ("a.js", "javascript"),
            ("a.mjs", "javascript"),
            ("a.cjs", "javascript"),
            ("a.jsx", "javascript"),
            ("a.ts", "typescript"),
            ("a.mts", "typescript"),
            ("a.tsx", "tsx"),
            ("A.PY", "python"),
            ("README.md", None),
            ("Makefile", None),
            ("a.d.ts.txt", None),
        ],
    )
    def test_names_the_grammar_from_the_suffix(self, path: str, language: str | None) -> None:
        assert language_of(path) == language


class TestBySymbol:
    def test_one_chunk_per_symbol_and_windows_for_the_code_between(self) -> None:
        text = PYTHON_SOURCE
        symbols = [
            Symbol("Greeter", 6, 11),
            Symbol("shout", 14, 15),
            Symbol("decorator", 18, 19),
            Symbol("main", 22, 24),
        ]

        chunks = chunk_text(text, symbols)

        assert [(c.symbol, c.start_line, c.end_line) for c in chunks] == [
            (None, 1, 3),
            ("Greeter", 6, 11),
            ("shout", 14, 15),
            ("decorator", 18, 19),
            ("main", 22, 24),
        ]
        assert_faithful(text, chunks)

    @pytest.mark.parametrize(
        ("language", "source", "names"),
        [
            ("python", PYTHON_SOURCE, ["Greeter", "shout", "decorator", "main"]),
            ("javascript", JAVASCRIPT_SOURCE, ["add", "double", "Counter"]),
            ("typescript", TYPESCRIPT_SOURCE, ["Point", "Id", "norm", "Box", "Color"]),
            ("tsx", TSX_SOURCE, ["Hello", "Bye"]),
        ],
    )
    def test_splits_each_language_by_symbol(
        self, session: ParseSession, language: str, source: str, names: list[str]
    ) -> None:
        chunks = chunk_text(source, session.symbols(language, source))

        assert [c.symbol for c in chunks if c.symbol is not None] == names
        assert_faithful(source, chunks)

    def test_an_oversized_symbol_falls_back_to_windows_that_keep_its_name(self) -> None:
        body = "\n".join(f"    value_{n} = {n}" for n in range(30))
        text = f"def big():\n{body}\n"
        symbols = [Symbol("big", 1, 31)]

        chunks = chunk_text(text, symbols, SMALL)

        assert len(chunks) > 1
        assert {c.symbol for c in chunks} == {"big"}
        assert all(len(c.content) <= SMALL.max_chars for c in chunks)
        assert_faithful(text, chunks)

    def test_ignores_a_symbol_that_overlaps_the_one_before_it(self) -> None:
        text = "a\nb\nc\nd\n"
        chunks = chunk_text(text, [Symbol("one", 1, 3), Symbol("two", 2, 4)])

        assert_faithful(text, chunks)
        assert chunks[0].symbol == "one"


class TestByWindow:
    def test_no_symbols_means_overlapping_windows_under_the_bound(self) -> None:
        text = "\n".join(f"line {n}" for n in range(1, 21)) + "\n"

        chunks = chunk_text(text, None, SMALL)

        assert [(c.start_line, c.end_line) for c in chunks[:3]] == [(1, 5), (4, 8), (7, 11)]
        assert all(c.symbol is None for c in chunks)
        assert all(len(c.content) <= SMALL.max_chars for c in chunks)
        assert chunks[-1].end_line >= 20
        assert_faithful(text, chunks)

    def test_a_window_ends_before_the_bound_is_crossed(self) -> None:
        text = "\n".join(["x" * 90] * 6)

        chunks = chunk_text(text, None, SMALL)

        assert all(len(c.content) <= SMALL.max_chars for c in chunks)
        assert_faithful(text, chunks)

    def test_a_line_over_the_bound_is_cut_into_pieces_that_share_its_number(self) -> None:
        text = "short\n" + "y" * 450 + "\nshort\n"

        chunks = chunk_text(text, None, SMALL)

        pieces = [c for c in chunks if c.start_line == 2 and c.end_line == 2]
        assert "".join(p.content for p in pieces) == "y" * 450
        assert all(len(c.content) <= SMALL.max_chars for c in chunks)

    def test_the_default_bound_is_applied_when_none_is_given(self) -> None:
        text = "\n".join("z" * 100 for _ in range(300))

        chunks = chunk_text(text, None)

        assert all(len(c.content) <= CHUNK_BOUNDS.max_chars for c in chunks)
        assert all(c.end_line - c.start_line + 1 <= CHUNK_BOUNDS.window_lines for c in chunks)
        assert_faithful(text, chunks)

    def test_a_blank_file_has_no_chunk(self) -> None:
        assert chunk_text("", None) == []
        assert chunk_text("\n\n   \n", None) == []
        assert chunk_text("\n\n   \n", []) == []

    def test_a_form_feed_is_not_a_line_break(self) -> None:
        """GitHub numbers lines on `\\n` only; `str.splitlines` would split at the form feed."""
        text = "first\n\x0csecond\nthird\n"

        chunks = chunk_text(text, None)

        assert [(c.start_line, c.end_line) for c in chunks] == [(1, 3)]
        assert chunks[0].content == "first\n\x0csecond\nthird"
        assert_faithful(text, chunks)

    def test_keeps_a_carriage_return_in_its_line(self) -> None:
        text = "one\r\ntwo\r\n"

        chunks = chunk_text(text, None)

        assert chunks[0].content == "one\r\ntwo\r"
        assert_faithful(text, chunks)

    def test_the_symbols_empty_list_still_windows_the_whole_file(self) -> None:
        text = "just a comment\n# and another\n"

        chunks = chunk_text(text, [])

        assert_faithful(text, chunks)
        assert chunks


class TestLineNumbersAgainstTheRealParser:
    """The parse worker and the chunker must number lines the same way, whatever separator
    characters the text holds: a drift shifts every chunk after it."""

    @pytest.mark.parametrize(
        "separator",
        ["\x0c", "\x0b", "\x1c", "\x1d", "\x1e", "\x85", " ", " ", "\r", "\U0001f600"],  # noqa: RUF001  # the separators are the subject
    )
    def test_python_symbol_lines_survive_separator_characters_in_earlier_lines(
        self, session: ParseSession, separator: str
    ) -> None:
        text = (
            f'NOTE = "a{separator}b"\n'
            f"# comment {separator} here\n"
            f"\n"
            f"def target():\n"
            f'    return "{separator}"\n'
            f"\n"
            f"class After:\n"
            f"    pass\n"
        )

        chunks = chunk_text(text, session.symbols("python", text))

        by_symbol = {c.symbol: c for c in chunks if c.symbol is not None}
        assert by_symbol["target"].start_line == 4
        assert by_symbol["target"].content.startswith("def target():")
        assert by_symbol["After"].content == "class After:\n    pass"
        assert_faithful(text, chunks)

    @pytest.mark.parametrize("separator", ["\x0c", " ", "\U0001f600"])  # noqa: RUF001  # the separator is the subject
    def test_typescript_symbol_lines_survive_separator_characters(
        self, session: ParseSession, separator: str
    ) -> None:
        text = f'const s = "{separator}";\n\nexport function target(): number {{\n  return 1;\n}}\n'

        chunks = chunk_text(text, session.symbols("typescript", text))

        target = next(c for c in chunks if c.symbol == "target")
        assert (target.start_line, target.end_line) == (3, 5)
        assert target.content.startswith("export function target")
        assert_faithful(text, chunks)

    def test_a_crlf_file_numbers_lines_on_the_newline_only(self, session: ParseSession) -> None:
        text = "x = 1\r\n\r\ndef target():\r\n    return 1\r\n"

        chunks = chunk_text(text, session.symbols("python", text))

        target = next(c for c in chunks if c.symbol == "target")
        assert (target.start_line, target.end_line) == (3, 4)

    def test_a_byte_order_mark_stripped_text_numbers_from_the_first_line(
        self, session: ParseSession
    ) -> None:
        text = "def target():\n    return 1\n"

        chunks = chunk_text(text, session.symbols("python", text))

        assert [(c.symbol, c.start_line) for c in chunks] == [("target", 1)]


class TestTheBoundHoldsForAnyText:
    def test_every_chunk_is_under_the_bound_and_every_non_blank_character_is_kept(self) -> None:
        generator = random.Random(20261031)  # noqa: S311  # fixed seed: a failure must reproduce
        bounds = ChunkBounds(max_chars=50, window_lines=4, overlap_lines=3)
        alphabet = "ab \t{}()é😀\x0c"
        for _ in range(300):
            lines = [
                "".join(
                    generator.choice(alphabet)
                    for _ in range(generator.choice([0, 3, 49, 50, 51, 120]))
                )
                for _ in range(generator.randint(1, 12))
            ]
            text = "\n".join(lines)
            symbols = (
                None
                if generator.random() < 0.3
                else [Symbol("s", generator.randint(1, 6), generator.randint(1, 14))]
            )

            chunks = chunk_text(text, symbols, bounds)

            assert all(len(c.content) <= bounds.max_chars for c in chunks), (text, chunks)
            covered = {n for c in chunks for n in range(c.start_line, c.end_line + 1)}
            assert all(n in covered for n, line in enumerate(lines, 1) if line.strip()), (
                lines,
                chunks,
            )

    def test_a_single_line_ten_times_the_bound_is_pieces_that_rejoin_to_the_line(self) -> None:
        line = "x" * (CHUNK_BOUNDS.max_chars * 10 + 7)

        chunks = chunk_text(line, None)

        assert {c.start_line for c in chunks} == {1}
        assert "".join(c.content for c in chunks) == line
        assert max(len(c.content) for c in chunks) <= CHUNK_BOUNDS.max_chars

    def test_a_symbol_whose_range_runs_past_the_end_of_the_file_is_clamped(self) -> None:
        text = "def f():\n    pass\n"

        chunks = chunk_text(text, [Symbol("f", 1, 999)])

        assert [(c.symbol, c.start_line) for c in chunks] == [("f", 1)]
        assert chunks[0].end_line <= len(text.split("\n"))


def embedded_ratio(text: str) -> float:
    return sum(len(chunk.content) for chunk in chunk_text(text, None)) / len(text)


class TestTheVolumeChunkingProduces:
    """The review's P1: a window of 11 lines or fewer (it ended at the character bound) moved on
    by one line, so 545-character lines were embedded 11 times over. A window now advances by
    at least half its length."""

    def test_lines_of_545_characters_embed_under_2_1_times_their_size(self) -> None:
        text = "\n".join(["y" * 545] * 2000)

        assert embedded_ratio(text) < 2.1

    @pytest.mark.parametrize("width", [1, 2, 10, 40, 100, 200, 400, 545, 600, 900, 1500, 3000])
    def test_no_line_width_embeds_more_than_2_6_times_the_text(self, width: int) -> None:
        text = "\n".join(["z" * width] * 1500)

        assert embedded_ratio(text) < 2.6

    def test_a_window_advances_by_at_least_half_its_length(self) -> None:
        bounds = ChunkBounds(max_chars=100, window_lines=60, overlap_lines=10)
        text = "\n".join(["a" * 20] * 200)  # four lines fit a window

        chunks = chunk_text(text, None, bounds)

        sizes = [c.end_line - c.start_line + 1 for c in chunks]
        advances = [b.start_line - a.start_line for a, b in itertools.pairwise(chunks)]
        assert all(
            advance >= (size + 1) // 2 for advance, size in zip(advances, sizes, strict=False)
        )
        assert_faithful(text, chunks)

    def test_the_worst_measured_pattern_is_3_28_times_so_the_cap_not_the_ratio_bounds_cost(
        self,
    ) -> None:
        """A window the character bound cuts short keeps halving toward a wide line, so that
        line recurs: 24 short lines then three wide ones, repeating, embed 3.28 times. This is
        why `IndexCaps.embedded_chars` bounds the cost and the ratio does not."""
        pattern = ["s" * 10] * 24 + ["w" * 2900] * 3
        text = "\n".join(pattern * 200)

        assert 3.0 < embedded_ratio(text) < 3.4

    def test_mixed_line_widths_stay_under_the_ratio(self) -> None:
        widths = [5, 300, 30, 540, 1, 700, 90]
        text = "\n".join("q" * widths[n % len(widths)] for n in range(3000))

        assert embedded_ratio(text) < 2.6


class TestASymbolWithNoName:
    def test_a_one_mebibyte_identifier_makes_chunks_with_no_symbol(self) -> None:
        """The worker drops a name over `SYMBOL_NAME_MAX`; the chunks keep the lines and carry no
        name, so no cap on the content has to count 1 MiB of name on every window."""
        text = f"def {'n' * (1024 * 1024 - 20)}(): pass\n"

        with ParseSession(ParseLimits(file_seconds=20, index_seconds=60)) as opened:
            chunks = chunk_text(text, opened.symbols("python", text))

        assert chunks
        assert {chunk.symbol for chunk in chunks} == {None}
        assert chunks[0].start_line == chunks[-1].end_line == 1


class TestAFileThatFailsToParse:
    def test_falls_back_to_windows(self, session: ParseSession) -> None:
        text = "def (:\n" * 5

        chunks = chunk_text(text, session.symbols("python", text))

        assert chunks
        assert all(c.symbol is None for c in chunks)
        assert_faithful(text, chunks)
