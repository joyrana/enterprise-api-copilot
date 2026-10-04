"""Granting approvals: who may approve, for which tenant, for how long.

In production the platform owns approval records (ADR-0005) and calls the same signer
contract. Locally, this service is the stand-in: it checks the approver's permission with
the policy decision point and issues an action-bound token.
"""

from __future__ import annotations

from skills.runtime.approvals import ApprovalSigner
from skills.runtime.contracts import Principal
from skills.runtime.errors import SkillError, SkillErrorCode
from skills.runtime.policy import APPROVAL_GRANT, PolicyDecisionPort


class ApprovalService:
    def __init__(
        self, signer: ApprovalSigner, policy: PolicyDecisionPort, *, max_ttl_s: float = 900.0
    ) -> None:
        self._signer = signer
        self._policy = policy
        self._max_ttl = max_ttl_s

    async def check_approver(self, approver: Principal, environment: str) -> None:
        decision = await self._policy.decide(approver, frozenset({APPROVAL_GRANT}), environment)
        if not decision.allowed:
            raise SkillError(SkillErrorCode.FORBIDDEN, "approver lacks approval:grant")

    async def approve(
        self,
        *,
        approver: Principal,
        action_hash: str,
        tenant_id: str,
        environment: str,
        ttl_s: float = 600.0,
    ) -> str:
        if approver.tenant_id != tenant_id:
            raise SkillError(SkillErrorCode.FORBIDDEN, "approver belongs to a different tenant")
        await self.check_approver(approver, environment)
        if len(action_hash) != 64 or any(c not in "0123456789abcdef" for c in action_hash):
            raise SkillError(SkillErrorCode.INVALID_INPUT, "malformed action hash")
        return self._signer.issue(
            action=action_hash,
            approver=approver.subject,
            tenant_id=tenant_id,
            ttl_s=min(ttl_s, self._max_ttl),
        )
