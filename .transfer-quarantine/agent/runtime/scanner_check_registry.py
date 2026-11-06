"""Host-pinned Scanner check selection; this module never executes a tool."""

from __future__ import annotations

from pydantic import Field, model_validator

from agent.contracts.common import ArtifactRef, ContractModel
from agent.contracts.tool_registry import ToolEffect, ToolInvocation, resolve_invocation
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.canonical_serialization import SERIALIZER_PROFILE, digest_raw
from agent.runtime.tool_registry import load_pinned_tool_registry


class ScannerCheck(ContractModel):
    capability: str = Field(min_length=1)
    invocation: ToolInvocation


class ScannerCheckRegistrySnapshot(ContractModel):
    tool_registry_ref: ArtifactRef
    checks: tuple[ScannerCheck, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_capabilities(self) -> ScannerCheckRegistrySnapshot:
        capabilities = [check.capability for check in self.checks]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("duplicate Scanner capability")
        return self


class ScannerCheckRegistry:
    """Resolve each required check against exact host-pinned tool identities."""

    def __init__(self, artifacts: ArtifactStore, ref: ArtifactRef) -> None:
        if ref.contract_id != "scanner_check_registry" or ref.contract_version != "1.0":
            raise ValueError("wrong Scanner check registry contract")
        raw = artifacts.get_verified(ref.artifact_id, ref.artifact_revision)
        if digest_raw(raw) != ref.artifact_digest:
            raise ValueError("Scanner check registry digest mismatch")
        snapshot = ScannerCheckRegistrySnapshot.model_validate_json(raw)
        tools = load_pinned_tool_registry(artifacts, snapshot.tool_registry_ref)
        for check in snapshot.checks:
            command = resolve_invocation(tools, check.invocation, "planning", frozenset())
            if command.effect is not ToolEffect.READ_ONLY or command.network:
                raise ValueError(f"Scanner check is not read-only: {check.capability}")
        self.ref = ref
        self.snapshot = snapshot

    @property
    def required_capabilities(self) -> tuple[str, ...]:
        return tuple(check.capability for check in self.snapshot.checks)


def pin_scanner_check_registry(
    artifacts: ArtifactStore, snapshot: ScannerCheckRegistrySnapshot, artifact_id: str, revision: int = 1
) -> ArtifactRef:
    """Persist only a registry whose exact tool snapshot and checks resolve."""
    tools = load_pinned_tool_registry(artifacts, snapshot.tool_registry_ref)
    for check in snapshot.checks:
        command = resolve_invocation(tools, check.invocation, "planning", frozenset())
        if command.effect is not ToolEffect.READ_ONLY or command.network:
            raise ValueError(f"Scanner check is not read-only: {check.capability}")
    digest = artifacts.put_immutable(snapshot, artifact_id, revision, "scanner_check_registry", "1.0")
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_revision=revision,
        artifact_digest=digest,
        contract_id="scanner_check_registry",
        contract_version="1.0",
        serializer_profile=SERIALIZER_PROFILE,
    )
