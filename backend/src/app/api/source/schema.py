"""schema.py belongs: this directory's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`. The leaf of the directory: routes and controller import it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access
(`service.py`).
"""

from typing import Annotated, Literal

from fastapi import Path
from pydantic import MISSING, StringConstraints, field_validator

from app.models.source.constants import SOURCE_LIMITS, is_plain_ref, is_repository_name
from app.services.utils.api_model import RequestModel, ResponseModel, Timestamp
from app.services.utils.pagination import Page

# The wire's forms of `models/source/enums.py`, inlined in the contract.
type SourceStatusName = Literal["queued", "indexing", "ready", "failed"]
type SourceErrorCodeName = Literal[
    "repository_unavailable",
    "repository_too_large",
    "embedding_unavailable",
    "interrupted",
    "internal",
]

# A plain assignment, not a `type` statement: FastAPI reads the `Path` metadata off the annotation.
SourceId = Annotated[str, Path(alias="id", min_length=1)]

type RepositoryUrl = Annotated[
    str,
    StringConstraints(pattern=SOURCE_LIMITS.url_pattern, max_length=SOURCE_LIMITS.url_max),
]
type RepositoryRef = Annotated[
    str,
    StringConstraints(
        pattern=SOURCE_LIMITS.ref_pattern,
        min_length=SOURCE_LIMITS.ref.min,
        max_length=SOURCE_LIMITS.ref.max,
    ),
]


class Source(ResponseModel):
    id: str
    url: str
    ref: str
    status: SourceStatusName
    error_code: SourceErrorCodeName | None
    indexed_commit: str | None
    document_count: int
    chunk_count: int
    created_at: Timestamp
    updated_at: Timestamp


class SourcePage(Page[Source]):
    """The list endpoint's page; the concrete name is the contract component."""


class ConnectSourceBody(RequestModel):
    """`url` is exactly `https://github.com/<owner>/<repo>`; `ref` is a branch, tag or commit and
    defaults to the repository's default branch."""

    url: RepositoryUrl
    ref: RepositoryRef | MISSING = MISSING

    @field_validator("url")
    @classmethod
    def _repository_is_named(cls, url: str) -> str:
        if not is_repository_name(url.rsplit("/", 1)[1]):
            raise ValueError("not a repository name")
        return url

    @field_validator("ref")
    @classmethod
    def _ref_is_plain(cls, ref: str) -> str:
        if not is_plain_ref(ref):
            raise ValueError("a ref holds no '..' and no '.' segment")
        return ref
