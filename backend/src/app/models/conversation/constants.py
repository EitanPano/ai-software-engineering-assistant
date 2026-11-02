"""constants.py belongs: limits of the data itself, read by the schema and the controller.
It does not belong: policy such as rates or turn limits (`config/constants.py`).
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Bounds:
    min: int
    max: int


@dataclass(frozen=True)
class MessageLimits:
    content: Bounds


MESSAGE_LIMITS: Final = MessageLimits(content=Bounds(min=1, max=32000))
