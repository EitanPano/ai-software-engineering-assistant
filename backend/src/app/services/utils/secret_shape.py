"""secret_shape.py belongs: a pure check for text that has the shape of an API key or token, so
memory extraction can drop such a fact even when the model's prompt did not stop it
(`.doc/product-definition.md`: no API key is stored in a memory). It judges shape only and has
no I/O.
It does not belong: deciding what to do with a match (the caller) or detecting every secret.

The tradeoff is decided: `_RUN` counts `/` and `-` as key characters, so a long path holding a
digit, a 40-hex commit and a UUID read as keys and the fact is dropped. A lost fact can be
restated; a stored key goes to Voyage and to every later recall. A false positive is the cheaper
error, so the check is not narrowed (`tests/services/test_secret_shape.py` pins the three).
"""

import re
from typing import Final

# Well-known prefixes of provider keys and tokens.
_PREFIXED: Final = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|pa-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|gh[ousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
# A credential in a URL (`scheme://user:password@host`) and a GitLab token.
_URL_CREDENTIAL: Final = re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
_GITLAB: Final = re.compile(r"glpat-[A-Za-z0-9_-]{20,}")
# A long unbroken run of key characters that mixes letters and digits is a key, not a word.
_RUN: Final = re.compile(r"[A-Za-z0-9_+/=-]{32,}")
_PRIVATE_KEY: Final = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def looks_like_secret(text: str) -> bool:
    """True when `text` holds something shaped like an API key, a token or a private key."""
    if (
        _PREFIXED.search(text)
        or _PRIVATE_KEY.search(text)
        or _URL_CREDENTIAL.search(text)
        or _GITLAB.search(text)
    ):
        return True
    for run in _RUN.findall(text):
        if any(c.isdigit() for c in run) and any(c.isalpha() for c in run):
            return True
    return False
