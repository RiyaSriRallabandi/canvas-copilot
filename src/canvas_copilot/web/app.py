"""FastAPI app behind `canvas-copilot serve`.

One server process, one user (the person on this machine). It wraps the same
LangGraph agent the CLI uses: a lazily built ``AgentDeps`` + agent + in-memory
checkpointer, guarded by a single lock because FastAPI runs sync handlers on a
threadpool and the SQLite connection and the graph state are shared.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from canvas_copilot import auth
from canvas_copilot.canvas.client import CanvasClient, CanvasError
from canvas_copilot.config import get_settings
from canvas_copilot.storage import CourseCache, NicknameStore, connect
from canvas_copilot.storage.content import ContentStore

_STATIC = Path(__file__).parent / "static"


class _Engine:
    """Storage handles plus the lazily built agent for the process."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.conn = connect(check_same_thread=False)
        self.cache = CourseCache(self.conn)
        self.nicknames = NicknameStore(self.conn)
        self._client: CanvasClient | None = None
        self._agent: Any | None = None

    # -- connection ------------------------------------------------------

    def connected(self) -> bool:
        return bool(auth.get_token())

    def _canvas(self) -> CanvasClient:
        settings = get_settings()
        return CanvasClient(settings.canvas_base_url, auth.get_token() or "")

    def _fetch_courses(self) -> Any:
        with self._canvas() as client:
            return client.list_courses()

    def account_name(self) -> str | None:
        try:
            with self._canvas() as client:
                return client.get_current_user().name
        except CanvasError:
            return None

    def connect_token(self, token: str) -> str:
        token = token.strip()
        if not token:
            raise HTTPException(400, "No token provided.")
        settings = get_settings()
        try:
            with CanvasClient(settings.canvas_base_url, token) as client:
                user = client.get_current_user()
        except CanvasError as exc:
            raise HTTPException(400, f"Canvas rejected the token: {exc}") from exc
        auth.store_token(token)
        if self._client is not None:
            self._client.close()
        self._client = self._agent = None
        return user.name

    # -- agent ---------------------------------------------------------

    def ensure_agent(self) -> Any:
        if self._agent is None:
            if not self.connected():
                raise HTTPException(409, "Connect a Canvas account first.")
            from langgraph.checkpoint.memory import InMemorySaver

            from canvas_copilot.agent import AgentDeps, build_agent
            from canvas_copilot.content.embed import Embedder

            settings = get_settings()
            self._client = self._canvas()
            deps = AgentDeps(
                client=self._client,
                cache=self.cache,
                nicknames=self.nicknames,
                conn=self.conn,
                embedder=Embedder(settings.embed_model, settings.ollama_host),
            )
            self._agent = build_agent(
                deps,
                model_name=settings.model,
                ollama_host=settings.ollama_host,
                checkpointer=InMemorySaver(),
            )
        return self._agent

    # -- indexing ----------------------------------------------------

    def index_events(self) -> Iterator[str]:
        """Yield SSE lines while every starred course is (re)indexed."""
        from canvas_copilot.content.embed import Embedder
        from canvas_copilot.content.index import index_course

        settings = get_settings()
        with self.lock:
            try:
                courses = self.cache.get_courses(self._fetch_courses)
            except CanvasError as exc:
                yield _sse({"error": str(exc)})
                return
            targets = [c for c in courses if c.is_favorite] or courses
            embedder = Embedder(settings.embed_model, settings.ollama_host)
            client = self._canvas()
            try:
                for done, course in enumerate(targets):
                    yield _sse(
                        {
                            "course": course.nickname or course.name,
                            "done": done,
                            "total": len(targets),
                        }
                    )
                    index_course(client, self.conn, embedder, course.id)
                yield _sse(
                    {"done": len(targets), "total": len(targets), "finished": True}
                )
            except Exception as exc:  # noqa: BLE001 - surface to the UI
                yield _sse({"error": str(exc)})
            finally:
                client.close()

    # -- state ------------------------------------------------------

    def state(self) -> dict[str, Any]:
        if not self.connected():
            return {"connected": False}
        try:
            courses = [
                c for c in self.cache.get_courses(self._fetch_courses) if c.is_favorite
            ]
        except CanvasError as exc:
            return {"connected": True, "account": None, "error": str(exc)}
        store = ContentStore(self.conn)
        indexed = sum(1 for c in courses if not store.needs_reindex(c.id))
        return {
            "connected": True,
            "account": self.account_name(),
            "courses": len(courses),
            "indexed": indexed,
        }


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class _Token(BaseModel):
    token: str


class _Chat(BaseModel):
    message: str
    thread_id: str


class _Resume(BaseModel):
    thread_id: str
    option_id: int


def _turn(
    engine: _Engine,
    thread_id: str,
    *,
    message: str | None = None,
    resume_option: int | None = None,
) -> dict[str, Any]:
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.types import Command

    from canvas_copilot.agent._util import message_text
    from canvas_copilot.agent.dates import hints_for, primary_window

    agent = engine.ensure_agent()
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    if resume_option is not None:
        state = agent.invoke(Command(resume=resume_option), config)
    else:
        assert message is not None
        today = date.today()
        state = agent.invoke(
            {
                "messages": [HumanMessage(content=message)],
                "date_hints": hints_for(message, today),
                "date_window": primary_window(message, today),
                "clarify": None,
                "blocked": False,
            },
            config,
        )

    interrupts = state.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value
        return {
            "type": "clarification",
            "prompt": payload["prompt"],
            "options": [{"id": o["id"], "label": o["label"]} for o in payload["options"]],
        }

    answer = next(
        (
            message_text(m)
            for m in reversed(state["messages"])
            if isinstance(m, AIMessage) and message_text(m)
        ),
        "(no answer)",
    )
    return {"type": "answer", "text": answer}


def build_app() -> FastAPI:
    engine = _Engine()
    app = FastAPI(title="Canvas Copilot")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        with engine.lock:
            return engine.state()

    @app.post("/api/connect")
    def connect_account(body: _Token) -> dict[str, Any]:
        with engine.lock:
            engine.connect_token(body.token)
            return engine.state()

    @app.post("/api/index")
    def run_index() -> StreamingResponse:
        return StreamingResponse(engine.index_events(), media_type="text/event-stream")

    @app.post("/api/chat")
    def chat(body: _Chat) -> dict[str, Any]:
        with engine.lock:
            return _turn(engine, body.thread_id, message=body.message)

    @app.post("/api/resume")
    def resume(body: _Resume) -> dict[str, Any]:
        with engine.lock:
            return _turn(engine, body.thread_id, resume_option=body.option_id)

    return app
