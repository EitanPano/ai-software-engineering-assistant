"""schema.py belongs: this directory's contract, the pydantic models that validate requests, type
responses and produce `openapi.json`. The leaf of the directory: routes and controller import it.
It does not belong: business rules or HTTP handling (`controller.py`) or data access (the queries
are `api/run/service.py`'s).
"""

from typing import Annotated, Literal

from fastapi import Path
from pydantic import StringConstraints

from app.services.utils.api_model import RequestModel, ResponseModel, Timestamp

type ApprovalDecisionName = Literal["approved", "rejected"]

# A plain assignment, not a `type` statement: FastAPI reads the `Path` metadata off the annotation.
ApprovalId = Annotated[str, Path(alias="id", min_length=1)]

# SHA-256 as 64 lowercase hex characters; the class is spelled out, as `\d` is Unicode in pydantic.
type ArgumentsDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DecideApprovalBody(RequestModel):
    decision: ApprovalDecisionName
    arguments_digest: ArgumentsDigest


class Approval(ResponseModel):
    id: str
    tool_use_id: str
    decision: ApprovalDecisionName
    decided_at: Timestamp
