"""Compatibility API: one implementation lives in agent.skills.auditor.core."""

from agent.skills.auditor.core import (
    Finding as Finding,
    AuditResult as AuditResult,
    evidence as evidence,
    python_files as python_files,
    Scanner as Scanner,
    scan as scan,
)
