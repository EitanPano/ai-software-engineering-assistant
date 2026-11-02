"""constants.py belongs: limits of the source data itself, the exact form of a repository URL and of
a ref. Patterns are for pydantic's regex engine, whose `$` ends the text (`re.match` would let a
trailing newline through) and whose classes are spelled out, since `\\w` is Unicode.
It does not belong: policy such as the indexing caps (`config/constants.py`).
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Bounds:
    min: int
    max: int


_OWNER_MAX: Final = 39
_REPO_MAX: Final = 100
_HOST_PREFIX: Final = "https://github.com/"


@dataclass(frozen=True)
class SourceLimits:
    # `https://github.com/<owner>/<repo>` and nothing else: no userinfo, port, query, fragment or
    # trailing slash. `.`, `..` and a `.git` ending are refused by `is_repository_name`.
    url_pattern: str
    url_max: int
    # No leading `/` or `-`; a `..` or a `.` segment is refused by `is_plain_ref`.
    ref_pattern: str
    ref: Bounds


SOURCE_LIMITS: Final = SourceLimits(
    url_pattern=(
        r"^https://github\.com/"
        rf"[A-Za-z0-9-]{{1,{_OWNER_MAX}}}/[A-Za-z0-9._-]{{1,{_REPO_MAX}}}$"
    ),
    url_max=len(_HOST_PREFIX) + _OWNER_MAX + 1 + _REPO_MAX,
    ref_pattern=r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$",
    ref=Bounds(min=1, max=255),
)


def is_repository_name(name: str) -> bool:
    """What a pattern cannot say: a repository is not `.` or `..` and does not end in `.git`."""
    return name not in {".", ".."} and not name.endswith(".git")


def is_plain_ref(ref: str) -> bool:
    """A ref holds no `..`, and no segment that is just `.`: `httpx` drops a dot segment from a
    path, so `.` would reach the commit list instead of the commit."""
    return ".." not in ref and "." not in ref.split("/")
