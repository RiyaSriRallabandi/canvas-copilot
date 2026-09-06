"""Tests for the nickname store."""

from __future__ import annotations

import pytest

from canvas_copilot.storage.db import connect
from canvas_copilot.storage.nicknames import NicknameStore


@pytest.fixture
def store() -> NicknameStore:
    return NicknameStore(connect(":memory:"))


def test_lookup_is_case_and_filler_insensitive(store: NicknameStore):
    store.add("My Stats Class!", 10)
    assert store.lookup("stats") == 10
    assert store.lookup("STATS") == 10


def test_remove(store: NicknameStore):
    store.add("ml", 1)
    assert store.remove("ml") is True
    assert store.lookup("ml") is None
    assert store.remove("ml") is False


def test_learn_does_not_override_manual(store: NicknameStore):
    store.add("ai", 1, source="manual")
    store.learn("ai", 2)
    entry = store.get("ai")
    assert entry is not None
    assert entry.course_id == 1
    assert entry.source == "manual"


def test_learn_creates_learned_entry(store: NicknameStore):
    store.learn("theory", 5)
    entry = store.get("theory")
    assert entry is not None
    assert entry.course_id == 5
    assert entry.source == "learned"


def test_add_rejects_empty_after_normalization(store: NicknameStore):
    with pytest.raises(ValueError):
        store.add("the class", 1)


def test_list(store: NicknameStore):
    store.add("alpha", 1)
    store.add("beta", 2)
    assert {n.course_id for n in store.list()} == {1, 2}


def test_one_course_can_have_several_nicknames(store: NicknameStore):
    store.add("strategy", 55274)
    store.add("ai strat", 55274)
    assert store.lookup("strategy") == 55274
    assert store.lookup("ai strat") == 55274
