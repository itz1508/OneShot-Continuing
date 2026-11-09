"""Check that relocated Host, Runtime and Auditor have single implementations."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    ("old", "new", "symbol"),
    [
        ("agent.runtime.controller", "system.host.controller", "HostController"),
        ("agent.runtime.authorization", "system.host.authorization", "AuthorizationEngine"),
        ("agent.runtime.guardrails", "system.host.guardrails", "run_blocking_guardrails"),
        ("agent.runtime.artifact_store", "system.runtime.artifact_store.store", "ArtifactStore"),
        ("agent.runtime.checkpoint_store", "system.runtime.checkpoint_store.store", "CheckpointStore"),
        ("agent.runtime.event_store", "system.runtime.event_store.store", "EventStore"),
        ("agent.runtime.receipt_store", "system.runtime.receipt_store.store", "ReceiptStore"),
        ("agent.runtime.effect_executor", "system.runtime.execution.executor", "EffectExecutor"),
        ("agent.audit.core", "agent.skills.auditor.core", "scan"),
        ("agent.audit.security", "agent.skills.auditor.security", "scan_security"),
    ],
)
def test_compatibility_import_identity(old: str, new: str, symbol: str) -> None:
    assert getattr(importlib.import_module(old), symbol) is getattr(importlib.import_module(new), symbol)


def test_controller_is_host_owned() -> None:
    from system.host.controller import HostController

    assert HostController.__module__ == "system.host.controller"


def test_audit_public_interface_identity() -> None:
    from agent.audit import scan as old_scan
    from agent.skills.auditor import scan

    assert scan is old_scan
