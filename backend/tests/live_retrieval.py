"""PAID, and run by a person: `uv run python -m tests.live_retrieval` with `VOYAGE_API_KEY` in the
shell environment. Not collected by pytest and in no gate.

It chunks the fixture repository through `services/chunk.py` (the symbols come from the parse
worker, as in the index), embeds every chunk with the real `voyage-code-4` and the paraphrase
`SEMANTIC_QUERY` with `embed_query`, ranks the chunks by cosine in memory and exits 0 when the chunk
the paraphrase expects is in the top 5. It proves what the scripted fake cannot: that the real
model relates the paraphrase to its chunk. It uses no database and no GitHub.

Cost: the fixture is 50 chunks and 37,924 characters, about 12,600 tokens by this script's own
3-characters-a-token rule, plus a query of a few tokens: well under $0.01 at $0.12 per million
tokens, inside the free allowance. A retry pays again.
"""

import asyncio
import math
import sys
from typing import Final

from app.models.source.type import Chunk
from app.services.chunk import chunk_text, language_of
from app.services.parse import ParseSession
from app.services.voyage import EmbeddingUnavailable, embed_documents, embed_query
from tests.fixture_repository import (
    EXPECTED_SEMANTIC,
    FIXTURE_FILES,
    INDEXED_PATHS,
    SEMANTIC_QUERY,
)

TOP: Final = 5


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm


def chunks_of_fixture() -> list[tuple[str, Chunk]]:
    found: list[tuple[str, Chunk]] = []
    with ParseSession() as session:
        for path in sorted(INDEXED_PATHS):
            text = FIXTURE_FILES[path].decode()
            language = language_of(path)
            symbols = None if language is None else session.symbols(language, text)
            found += [(path, chunk) for chunk in chunk_text(text, symbols)]
    return found


async def main() -> int:
    chunks = chunks_of_fixture()
    characters = sum(len(chunk.content) for _, chunk in chunks)
    print(f"{len(chunks)} chunks, {characters} characters (about {characters // 3} tokens)")
    try:
        vectors = await embed_documents([chunk.content for _, chunk in chunks])
        query = await embed_query(SEMANTIC_QUERY)
    except EmbeddingUnavailable as error:
        print(f"voyage failed: {error}")
        return 2
    ranked = sorted(range(len(chunks)), key=lambda n: cosine(query, vectors[n]), reverse=True)
    expected = (EXPECTED_SEMANTIC.path, EXPECTED_SEMANTIC.start_line, EXPECTED_SEMANTIC.end_line)
    position = next(
        rank
        for rank, n in enumerate(ranked, 1)
        if (chunks[n][0], chunks[n][1].start_line, chunks[n][1].end_line) == expected
    )
    print(f"query: {SEMANTIC_QUERY!r}")
    for rank, n in enumerate(ranked[:TOP], 1):
        path, chunk = chunks[n]
        mark = "  <- expected" if rank == position else ""
        print(
            f"{rank}. {path}:{chunk.start_line}-{chunk.end_line} {chunk.symbol or '-'} "
            f"cosine={cosine(query, vectors[n]):.4f}{mark}"
        )
    print(f"expected chunk {EXPECTED_SEMANTIC.symbol} ranked {position} of {len(chunks)}")
    return 0 if position <= TOP else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop))
