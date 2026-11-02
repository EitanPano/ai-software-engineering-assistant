"""schema.py belongs: this directory's contract, the pydantic models that validate the search query,
type the answer and produce `openapi.json`. The leaf of the directory: routes and controller import
it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access.
"""

from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.models.search.constants import SEARCH_LIMITS
from app.services.utils.api_model import QueryModel, ResponseModel

type SearchText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=SEARCH_LIMITS.q_min, max_length=SEARCH_LIMITS.q_max
    ),
]


class SearchQuery(QueryModel):
    """`q` is 1 to 500 characters after trimming, with no NUL, which Postgres cannot store in a
    text; `limit` is how many hits the answer holds at most."""

    q: SearchText
    limit: Annotated[int, Field(ge=SEARCH_LIMITS.limit_min, le=SEARCH_LIMITS.limit_max)] = (
        SEARCH_LIMITS.limit_default
    )

    @field_validator("q")
    @classmethod
    def _has_no_nul(cls, q: str) -> str:
        if "\x00" in q:
            raise ValueError("must not contain NUL")
        return q


class SearchHit(ResponseModel):
    chunk_id: str
    source_id: str
    url: str
    ref: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int
    content: str
    score: float
    semantic_rank: int | None
    full_text_rank: int | None
    trigram_rank: int | None


class SearchResult(ResponseModel):
    items: list[SearchHit]
    incomplete: bool
