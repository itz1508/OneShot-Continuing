"""Tests for Scanner tools — verify each scanner detects known patterns."""

from __future__ import annotations

import textwrap

import pytest

from agent.scanners.attempt_scanner import scan_attempt_identity
from agent.scanners.checkpoint_scanner import scan_checkpoint_integrity
from agent.scanners.core import Finding, ScannerResult, scan
from agent.scanners.effect_scanner import scan_effect_executor
from agent.scanners.recovery_scanner import scan_recovery_classification
from agent.scanners.schema_scanner import scan_schema_compatibility


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "runtime").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


class TestCheckpointIntegrityScanner:
    def test_detects_unverified_read(self, repo):
        path = repo / "agent" / "runtime" / "store.py"
        path.write_text(
            textwrap.dedent("""
            def load_checkpoint(self, task_id):
                row = conn.execute("SELECT state_json, state_digest FROM checkpoints").fetchone()
                if row is None:
                    return None
                return row[0], row[1]
        """)
        )
        findings = scan_checkpoint_integrity(repo, repo)
        assert len(findings) == 1
        assert findings[0].code == "DIGEST_NOT_VERIFIED_ON_READ"
        assert findings[0].severity == "high"

    def test_passes_verified_read(self, repo):
        path = repo / "agent" / "runtime" / "store.py"
        path.write_text(
            textwrap.dedent("""
            def load_checkpoint(self, task_id):
                row = conn.execute("SELECT state_json, state_digest FROM checkpoints").fetchone()
                if row is None:
                    return None
                actual = hashlib.sha256(row[0].encode()).hexdigest()
                if actual != row[1]:
                    raise IntegrityError()
                return row[0], row[1]
        """)
        )
        findings = scan_checkpoint_integrity(repo, repo)
        assert len(findings) == 0

    def test_ignores_unrelated_methods(self, repo):
        path = repo / "agent" / "runtime" / "store.py"
        path.write_text("def get_name(self): return 'test'\n")
        findings = scan_checkpoint_integrity(repo, repo)
        assert len(findings) == 0


class TestSchemaCompatibilityScanner:
    def test_detects_shared_table_name(self, repo):
        s1 = repo / "agent" / "runtime" / "store1.py"
        s1.write_text(
            textwrap.dedent("""
            def _init_db(self):
                conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (task_id TEXT, rev INTEGER)")
        """)
        )
        s2 = repo / "agent" / "runtime" / "store2.py"
        s2.write_text(
            textwrap.dedent("""
            def _init_db(self):
                conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (id TEXT, payload BLOB)")
        """)
        )
        findings = scan_schema_compatibility(repo, repo)
        codes = {f.code for f in findings}
        assert "SHARED_TABLE_NAME_MISMATCHED_SCHEMA" in codes

    def test_detects_missing_compat_check(self, repo):
        s1 = repo / "agent" / "runtime" / "store1.py"
        s1.write_text(
            textwrap.dedent("""
            def _init_db(self):
                conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (id TEXT, rev INTEGER)")
        """)
        )
        findings = scan_schema_compatibility(repo, repo)
        codes = {f.code for f in findings}
        assert "MISSING_SCHEMA_COMPATIBILITY_CHECK" in codes


class TestAttemptIdentityScanner:
    def test_detects_missing_attempt(self, repo):
        path = repo / "agent" / "runtime" / "executor.py"
        path.write_text(
            textwrap.dedent("""
            def _pre_effect_checkpoint(self, action_id, pre, post):
                key = f"pre-effect-{action_id}"
                store.checkpoint_cas(key, 0, data)
        """)
        )
        findings = scan_attempt_identity(repo, repo)
        assert len(findings) == 1
        assert findings[0].code == "MISSING_ATTEMPT_IDENTITY"

    def test_passes_with_attempt(self, repo):
        path = repo / "agent" / "runtime" / "executor.py"
        path.write_text(
            textwrap.dedent("""
            def _pre_effect_checkpoint(self, action_id, pre, post, attempt):
                key = f"pre-effect-{action_id}-attempt-{attempt}"
                store.checkpoint_cas(key, 0, data)
        """)
        )
        findings = scan_attempt_identity(repo, repo)
        assert len(findings) == 0


class TestRecoveryClassificationScanner:
    def test_detects_fstring_return(self, repo):
        path = repo / "agent" / "runtime" / "recovery.py"
        path.write_text(
            textwrap.dedent("""
            def reconcile(self, operation_id, operation_data):
                return f"reconciled:{operation_id}"
        """)
        )
        findings = scan_recovery_classification(repo, repo)
        assert len(findings) == 1
        assert findings[0].code == "RECONCILE_RETURNS_FSTRING"

    def test_detects_constant_return(self, repo):
        path = repo / "agent" / "runtime" / "recovery.py"
        path.write_text('def reconcile(self, op_id, data): return "done"\n')
        findings = scan_recovery_classification(repo, repo)
        assert len(findings) == 1
        assert findings[0].code == "RECONCILE_RETURNS_STRING"

    def test_passes_structured_return(self, repo):
        path = repo / "agent" / "runtime" / "recovery.py"
        path.write_text("def reconcile(self, op_id, data): return {'status': 'ok'}\n")
        findings = scan_recovery_classification(repo, repo)
        assert len(findings) == 0


class TestEffectExecutorScanner:
    def test_detects_missing_prior_check(self, repo):
        path = repo / "agent" / "runtime" / "effect_executor.py"
        path.write_text(
            textwrap.dedent("""
            def execute_admitted(self, action_id, kind, receipt):
                self._pre_effect_checkpoint(action_id, "file.py", "pre", "post")
                self._write_atomic(target, content)
                self._clear_pre_effect_checkpoint(action_id)
                return result
            def _clear_pre_effect_checkpoint(self, action_id):
                key = f"pre-effect-{action_id}"
                store.checkpoint_cas(key, 1, completion_data)
        """)
        )
        findings = scan_effect_executor(repo, repo)
        codes = {f.code for f in findings}
        assert "MISSING_PRIOR_ATTEMPT_CHECK" in codes
        assert "CLEAR_FAILS_ON_MISSING_CHECKPOINT" in codes

    def test_passes_with_prior_check(self, repo):
        path = repo / "agent" / "runtime" / "effect_executor.py"
        path.write_text(
            textwrap.dedent("""
            def execute_admitted(self, action_id, kind, receipt):
                prior = self._has_pre_effect_checkpoint(action_id, attempt)
                if prior is not None:
                    return uncertain
                self._pre_effect_checkpoint(action_id, "file.py", "pre", "post", attempt)
                self._write_atomic(target, content)
                self._clear_pre_effect_checkpoint(action_id, attempt)
                return result
            def _clear_pre_effect_checkpoint(self, action_id, attempt):
                existing = store.load_checkpoint(key)
                if existing is None:
                    return
                store.checkpoint_cas(key, 1, data)
        """)
        )
        findings = scan_effect_executor(repo, repo)
        assert len(findings) == 0


class TestScanOrchestrator:
    def test_scan_returns_result(self, repo):
        result = scan(repo)
        assert isinstance(result, ScannerResult)
        assert len(result.scanners_run) == 5
        assert result.limitations is not None

    def test_scan_with_specific_scanners(self, repo):
        result = scan(repo, scanners=("checkpoint_integrity",))
        assert result.scanners_run == ("checkpoint_integrity",)

    def test_scan_rejects_unknown_scanner(self, repo):
        with pytest.raises(ValueError, match="unknown scanners"):
            scan(repo, scanners=("nonexistent",))

    def test_scan_scope_escape_rejected(self, repo):
        with pytest.raises(ValueError, match="escapes repository root"):
            scan(repo, scope="..")

    def test_to_dict_structure(self, repo):
        path = repo / "agent" / "runtime" / "recovery.py"
        path.write_text('def reconcile(self, op_id, data): return "done"\n')
        result = scan(repo, scanners=("recovery_classification",))
        d = result.to_dict()
        assert d["root"] == str(repo)
        assert d["findings_count"] == 1
        assert d["findings"][0]["finding_id"].startswith("SCP-")

    def test_has_findings_property(self, repo):
        path = repo / "agent" / "runtime" / "recovery.py"
        path.write_text('def reconcile(self, op_id, data): return "done"\n')
        result = scan(repo, scanners=("recovery_classification",))
        assert result.has_findings is True

    def test_no_findings(self, repo):
        path = repo / "agent" / "runtime" / "clean.py"
        path.write_text("def get_name(self): return 'clean'\n")
        result = scan(repo, scanners=("recovery_classification",))
        assert result.has_findings is False


class TestFindingIdentity:
    def test_finding_is_frozen(self):
        f = Finding(scanner="test", code="TEST001", severity="high", path="a.py", line=1, message="test message")
        with pytest.raises(Exception):
            f.scanner = "other"

    def test_finding_evidence_digest_optional(self):
        f = Finding(scanner="test", code="TEST001", severity="high", path="a.py", line=1, message="test message")
        assert f.evidence_digest == ""
