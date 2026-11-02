"""controller.py belongs: the handler of `POST /api/approval/{id}/decision`. The `approval` rows are
the run module's (`api/run/service.py`): a pause and a last decision each commit rows, events and
the run's status together, and a cross-module flow is not atomic, so this module holds no table and
no service. The handler composes the run rule that records the decision with the event that hands
the run back to the agent.
It does not belong: queries, or the loop (`api/agent/controller.py`).
"""

from fastapi import Request

from app.api.approval.schema import Approval, ApprovalId, DecideApprovalBody
from app.api.run.controller import decide_tool_call
from app.middleware.auth import require_caller
from app.models.approval.enums import ApprovalDecision
from app.services.event import RUN_RESUMED, publish
from app.services.utils import clock


async def decide_approval(
    request: Request, approval_id: ApprovalId, body: DecideApprovalBody
) -> Approval:
    """Records the caller's decision on one waiting tool call; the decision that leaves none
    waiting hands the run back to the agent, after its commit."""
    caller = require_caller(request)
    decided = await decide_tool_call(
        approval_id,
        decision=ApprovalDecision(body.decision),
        arguments_digest=body.arguments_digest,
        caller=caller,
    )
    if decided.resumes:
        await publish(RUN_RESUMED, {"run_id": decided.run_id})
    return Approval(
        id=decided.id,
        tool_use_id=decided.tool_use_id,
        decision=decided.decision.value,
        decided_at=clock.to_iso(decided.decided_at),
    )
