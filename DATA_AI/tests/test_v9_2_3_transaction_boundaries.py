import ast
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import service

ROOT = Path(__file__).resolve().parents[1]


class FakeQuery:
    def filter_by(self, **kwargs):
        return self

    def count(self):
        return 0

    def first(self):
        return None


class FailingCommitSession:
    def __init__(self):
        self.added = []
        self.rolled_back = False

    def query(self, model):
        return FakeQuery()

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        raise RuntimeError("simulated database commit failure")

    def rollback(self):
        self.rolled_back = True


def test_csv_processor_does_not_commit_before_pipeline_run_is_completed():
    tree = ast.parse((ROOT / "app" / "service.py").read_text(encoding="utf-8"))
    target = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "process_csv")
    commits = [node for node in ast.walk(target) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "commit"]
    assert not commits, "process_csv must participate in the parent process_document transaction"


def test_failed_document_commit_removes_orphaned_file(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "storage_dir", tmp_path)
    monkeypatch.setattr(service, "append_evidence_manifest_entry", lambda *args, **kwargs: None)
    case = SimpleNamespace(id=uuid4())
    db = FailingCommitSession()
    with pytest.raises(RuntimeError, match="simulated database commit failure"):
        service.save_upload(db, case, "statement.csv", b"date,amount\\n2026-01-01,100")
    assert db.rolled_back
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


class SuccessfulCommitSession(FailingCommitSession):
    def commit(self):
        return None

    def refresh(self, obj):
        return None


def test_concurrent_duplicate_upload_cleanup_does_not_delete_winning_file(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "storage_dir", tmp_path)
    monkeypatch.setattr(service, "append_evidence_manifest_entry", lambda *args, **kwargs: None)
    case = SimpleNamespace(id=uuid4())
    content = b"date,amount\n2026-01-01,100"

    winner = service.save_upload(SuccessfulCommitSession(), case, "statement.csv", content)
    winner_path = Path(winner.stored_path)
    assert winner_path.exists()

    # Simulate a second request that passed the pre-insert duplicate lookup
    # before the first transaction committed, then lost the DB unique race.
    losing = FailingCommitSession()
    with pytest.raises(RuntimeError, match="simulated database commit failure"):
        service.save_upload(losing, case, "statement.csv", content)

    assert winner_path.exists()
    remaining = [path for path in tmp_path.rglob("*.csv") if path.is_file()]
    assert remaining == [winner_path]


class NoCommitSession(SuccessfulCommitSession):
    def __init__(self):
        super().__init__()
        self.commit_called = False

    def commit(self):
        self.commit_called = True


def test_save_upload_can_leave_commit_to_atomic_workflow_outbox_caller(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "storage_dir", tmp_path)
    monkeypatch.setattr(service, "append_evidence_manifest_entry", lambda *args, **kwargs: None)
    db = NoCommitSession()
    case = SimpleNamespace(id=uuid4())
    saved = service.save_upload(db, case, "statement.csv", b"date,amount\n2026-01-01,100", commit=False)
    assert saved is not None
    assert Path(saved.stored_path).is_file()
    assert db.commit_called is False
