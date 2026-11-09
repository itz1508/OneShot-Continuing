"""Compatibility API: one implementation lives in system.host.guardrails."""

from system.host.guardrails import (
    GuardrailCheck as GuardrailCheck,
    GuardrailBlocked as GuardrailBlocked,
    run_blocking_guardrails as run_blocking_guardrails,
)
