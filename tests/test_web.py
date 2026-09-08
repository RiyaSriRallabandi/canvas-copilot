"""Tests for the local web UI (FastAPI), with a scripted agent."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from canvas_copilot import auth
from canvas_copilot.web import app as webapp


class _ScriptedAgent:
    """Returns a canned graph state; records the configs it was invoked with."""

    def __init__(self, *states):
        self._states = list(states)
        self.calls = []

    def invoke(self, payload, config):
        self.calls.append((payload, config))
        return self._states.pop(0)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "get_token", lambda: "tok")
    monkeypatch.setattr(webapp, "connect", lambda **kw: _memory_conn())
    agent_box = {}

    def fake_ensure(self):
        return agent_box["agent"]

    monkeypatch.setattr(webapp._Engine, "ensure_agent", fake_ensure)
    monkeypatch.setattr(
        webapp._Engine,
        "state",
        lambda self: {"connected": True, "indexed": 1, "courses": 1},
    )
    c = TestClient(webapp.build_app())
    return c, agent_box


def _memory_conn():
    from canvas_copilot.storage.db import connect

    return connect(":memory:")


def test_serves_the_page(monkeypatch):
    monkeypatch.setattr(webapp, "connect", lambda **kw: _memory_conn())
    c = TestClient(webapp.build_app())
    body = c.get("/")
    assert body.status_code == 200
    assert "Canvas Copilot" in body.text


def test_state_reports_disconnected(monkeypatch):
    monkeypatch.setattr(auth, "get_token", lambda: None)
    monkeypatch.setattr(webapp, "connect", lambda **kw: _memory_conn())
    c = TestClient(webapp.build_app())
    assert c.get("/api/state").json() == {"connected": False}


def test_chat_returns_an_answer(client):
    c, box = client
    box["agent"] = _ScriptedAgent(
        {"messages": [AIMessage(content="Lab 3 is due Friday.")]}
    )
    r = c.post("/api/chat", json={"message": "what's due?", "thread_id": "t1"})
    assert r.json() == {"type": "answer", "text": "Lab 3 is due Friday."}
    # the thread id is threaded through to the checkpointer config
    assert box["agent"].calls[0][1]["configurable"]["thread_id"] == "t1"


def test_chat_surfaces_a_clarification_then_resumes(client):
    c, box = client
    box["agent"] = _ScriptedAgent(
        {
            "messages": [],
            "__interrupt__": [
                type(
                    "I",
                    (),
                    {
                        "value": {
                            "prompt": "Which course did you mean?",
                            "options": [
                                {"id": 1, "label": "AI Strategy"},
                                {"id": 2, "label": "Intro to AI"},
                            ],
                        }
                    },
                )()
            ],
        },
        {"messages": [AIMessage(content="Two assignments in AI Strategy.")]},
    )
    first = c.post("/api/chat", json={"message": "work in AI?", "thread_id": "t2"}).json()
    assert first["type"] == "clarification"
    assert [o["label"] for o in first["options"]] == ["AI Strategy", "Intro to AI"]

    second = c.post("/api/resume", json={"thread_id": "t2", "option_id": 1}).json()
    assert second == {"type": "answer", "text": "Two assignments in AI Strategy."}
