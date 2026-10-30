"""interface.py belongs: the stored `run` and `run_event` records, what `api/run/service.py` reads
and writes. Timestamps are timezone-aware `datetime`; a frozen dataclass despite the name.
It does not belong: the wire shape (`api/run/schema.py`) or value sets (`enums.py`).
"""

from dataclasses import dataclass
from datetime import datetime

from app.models.run.enums import RunErrorCode, RunEventType, RunStatus


@dataclass(frozen=True)
class RunRecord:
    id: str
    conversation_id: str
    user_id: str
    status: RunStatus
    error_code: RunErrorCode | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RunEventRecord:
    run_id: str
    sequence: int
    type: RunEventType
    payload: dict[str, object]
    created_at: datetime
