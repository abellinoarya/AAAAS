"""Pattern memory: learning vendor coding habits, and task state."""
from __future__ import annotations

from aaaas.memory.store import PatternMemory, TaskStatus, TaskStore


def test_pattern_confidence_grows_with_evidence():
    mem = PatternMemory()
    mem.record_coding(vendor_id=7, account_id=5010)
    (coding1, conf1) = mem.suggest_coding(7)
    for _ in range(4):
        mem.record_coding(vendor_id=7, account_id=5010)
    (coding2, conf2) = mem.suggest_coding(7)
    assert coding1 == (5010, "")
    assert coding2 == (5010, "")
    assert conf2 > conf1
    assert 0.0 < conf2 <= 1.0


def test_pattern_picks_majority_coding():
    mem = PatternMemory()
    for _ in range(3):
        mem.record_coding(7, 5010)
    mem.record_coding(7, 6020)
    coding, _ = mem.suggest_coding(7)
    assert coding[0] == 5010


def test_unknown_vendor_has_no_suggestion():
    mem = PatternMemory()
    assert mem.suggest_coding(999) == (None, 0.0)


def test_pattern_persists_to_disk(tmp_path):
    path = str(tmp_path / "patterns.json")
    mem = PatternMemory(path)
    mem.record_coding(7, 5010, "Operations")
    reloaded = PatternMemory(path)
    coding, conf = reloaded.suggest_coding(7)
    assert coding == (5010, "Operations")
    assert conf > 0


def test_task_store_lifecycle():
    store = TaskStore()
    task = store.add("MATCH_VENDOR_BILL", {"bill_id": 42})
    assert store.pending() == [task]
    store.update(task.id, TaskStatus.DONE, note="matched")
    assert store.pending() == []
    assert store.by_status(TaskStatus.DONE)[0].note == "matched"
