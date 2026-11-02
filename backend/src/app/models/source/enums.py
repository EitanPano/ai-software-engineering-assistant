"""enums.py belongs: the closed value sets of a source: where an index stands, and why one failed.
It does not belong: limits (`constants.py`) or object shapes (`interface.py`).
"""

from enum import StrEnum


class SourceStatus(StrEnum):
    queued = "queued"
    indexing = "indexing"
    ready = "ready"
    failed = "failed"


class SourceErrorCode(StrEnum):
    repository_unavailable = "repository_unavailable"
    repository_too_large = "repository_too_large"
    embedding_unavailable = "embedding_unavailable"
    interrupted = "interrupted"
    internal = "internal"
