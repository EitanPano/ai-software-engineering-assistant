"""jsonb.py belongs: the one pure check of whether a parsed JSON value can be stored in a JSONB
column. Postgres refuses an escaped NUL (`\\u0000`) in a string or a key, and a number that is not
finite: `NaN`, `Infinity` and `1e400` (which Python reads as infinity) all pass a JSON parser and
fail the insert. A lone surrogate never passes the parser, so it is not checked.
It does not belong: I/O or any rule about what to do with a value that fails.
"""

import math


def jsonb_safe(value: object) -> bool:
    """Whether `value` (parsed JSON) holds nothing JSONB refuses, at any depth, keys included."""
    if isinstance(value, str):
        return "\x00" not in value
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(jsonb_safe(key) and jsonb_safe(item) for key, item in value.items())
    if isinstance(value, list):
        return all(jsonb_safe(item) for item in value)
    return True
