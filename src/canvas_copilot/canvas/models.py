"""Typed models for the subset of Canvas API fields Canvas Copilot uses.

Canvas returns large objects with dozens of fields; we model only what the app
needs. ``extra="ignore"`` means unknown fields are dropped rather than raising,
so a Canvas response gaining a field won't break parsing — but a field we rely
on changing type will surface immediately.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CanvasModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class User(CanvasModel):
    id: int
    name: str
    short_name: str | None = None
    primary_email: str | None = None


class Course(CanvasModel):
    id: int
    name: str | None = None
    course_code: str | None = None
    # Filled in from the course_nicknames endpoint, not the course payload.
    nickname: str | None = None
    # Filled in from the favorites endpoint: True for "starred" dashboard courses.
    is_favorite: bool = False


class Submission(CanvasModel):
    # "unsubmitted" | "submitted" | "pending_review" | "graded"
    workflow_state: str | None = None
    submitted_at: datetime | None = None
    score: float | None = None

    @property
    def is_submitted(self) -> bool:
        return self.workflow_state in {"submitted", "pending_review", "graded"}


class Assignment(CanvasModel):
    id: int
    course_id: int | None = None
    name: str
    description: str | None = None  # HTML; only used for content indexing
    due_at: datetime | None = None
    unlock_at: datetime | None = None
    lock_at: datetime | None = None
    html_url: str | None = None
    points_possible: float | None = None
    submission_types: list[str] = []
    # Present only when the assignments list is fetched with include[]=submission.
    submission: Submission | None = None

    @property
    def is_submittable_online(self) -> bool:
        online = {"online_text_entry", "online_url", "online_upload", "online_quiz"}
        return bool(online.intersection(self.submission_types))


class CourseNickname(CanvasModel):
    course_id: int
    nickname: str


class Page(CanvasModel):
    url: str  # the page's slug, used to fetch its body
    title: str | None = None
    body: str | None = None  # HTML, populated by get_page
    html_url: str | None = None


class Announcement(CanvasModel):
    id: int
    title: str | None = None
    message: str | None = None  # HTML
    html_url: str | None = None
    posted_at: datetime | None = None


class ModuleItem(CanvasModel):
    title: str | None = None
    type: str | None = None  # "Page" | "Assignment" | "File" | "ExternalUrl" | ...
    html_url: str | None = None


class Module(CanvasModel):
    id: int
    name: str | None = None
    items: list[ModuleItem] = []
    html_url: str | None = None  # constructed by the client (Canvas omits it)
