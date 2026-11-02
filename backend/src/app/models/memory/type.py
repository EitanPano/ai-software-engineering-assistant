"""type.py belongs: shapes that several layers share and that are neither stored records nor wire
models.
It does not belong: the stored records (`interface.py`) or value sets (`enums.py`).
"""

from app.models.memory.enums import ToolRecallCode


class ToolRecallFailed(Exception):  # noqa: N818  # named for the fixed answer it becomes
    """The `recall` tool's failure. It carries one fixed code, which is all the model sees."""

    def __init__(self, code: ToolRecallCode) -> None:
        super().__init__(code.value)
        self.code = code
