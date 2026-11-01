"""controller.py belongs: the rule the agent module calls to read what a tool may do. `tool_policy`
has no route: no acceptance criterion asks for one, and the `knowledge` policy ships in the
migration. The decision itself is `decide` in `services/tool.py`: only `allow` runs.
It does not belong: queries (`service.py`).
"""

from app.api.tool_policy import service
from app.models.tool_policy.enums import PolicyEffect


async def find_effect(*, mcp_server_id: str, tool_name: str) -> PolicyEffect | None:
    """System operation: the effect of the policy row for a tool, read at each call so a stored
    definition never outranks it. `None` is no row, which is a deny."""
    return await service.find_effect(mcp_server_id, tool_name)
