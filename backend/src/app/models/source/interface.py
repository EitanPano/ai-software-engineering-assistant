"""interface.py belongs: the stored `source`, `document` and `chunk` records, what
`api/source/service.py` reads and writes. A frozen dataclass despite the name. A chunk's embedding
travels as text cast to `halfvec` and is not part of the record read back.
It does not belong: the wire shape (`api/source/schema.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.source.enums import SourceErrorCode, SourceStatus


@dataclass(frozen=True)
class SourceRecord:
    id: str
    url: str
    ref: str
    status: SourceStatus
    error_code: SourceErrorCode | None
    indexed_commit: str | None
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    source_id: str
    path: str
    language: str | None
    created_at: datetime


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    document_id: str
    symbol: str | None
    start_line: int
    end_line: int
    content: str
    created_at: datetime
