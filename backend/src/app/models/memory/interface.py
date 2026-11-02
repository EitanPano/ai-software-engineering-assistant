"""interface.py belongs: the stored `memory` record, what `api/memory/service.py` reads and writes.
The embedding is a column of the table and not a field here: nothing but the recall query reads
it, and no response carries it. A frozen dataclass despite the name. `user_id` and
`conversation_id` are plain text, because modules are independent.
It does not belong: the wire shape (`api/memory/schema.py`).
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    user_id: str
    conversation_id: str
    content: str
    created_at: datetime
