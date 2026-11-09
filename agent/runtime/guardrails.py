"""Compatibility API: one implementation lives in system.host.guardrails."""

from system.host.guardrails import (
    GuardrailBlocked as GuardrailBlocked,
    GuardrailCheck as GuardrailCheck,
    run_blocking_guardrails as run_blocking_guardrails,
)
