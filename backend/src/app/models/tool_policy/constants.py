"""constants.py belongs: what is fixed about the policy of the servers the product ships: the only
`github` tools whose effect may be `allow` (the five reads `0011` seeds at `allow`). Every other
`github` tool, a future one included, may be `ask` or `deny`: anything the agent changes on GitHub
needs an approval, and an admin's click does not end that.
It does not belong: value sets (`enums.py`) or timeouts (`config/constants.py`).
"""

from typing import Final

GITHUB_ALLOWABLE_TOOLS: Final = frozenset(
    {
        "get_file_contents",
        "issue_read",
        "list_issues",
        "pull_request_read",
        "list_pull_requests",
    }
)
