"""Read-only client for the Canvas LMS REST API.

Every request goes through :meth:`CanvasClient._request`, which refuses any HTTP
method other than GET. That method is the single enforcement point for Canvas
Copilot's read-only guarantee.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol

import httpx

from canvas_copilot.canvas.models import (
    Announcement,
    Assignment,
    Course,
    CourseNickname,
    Module,
    Page,
    User,
)

_MAX_PAGES = 50
_PER_PAGE = 100


class CanvasError(RuntimeError):
    """Raised when the Canvas API returns an error or the client is misconfigured."""


class CanvasReader(Protocol):
    """The read-only surface the agent needs (real client or a test fake)."""

    def list_courses(self, *, enrollment_state: str = ...) -> list[Course]: ...
    def list_assignments(
        self,
        course_id: int,
        *,
        due_after: datetime | None = ...,
        due_before: datetime | None = ...,
    ) -> list[Assignment]: ...
    def get_todo(self) -> list[Assignment]: ...
    def get_upcoming_events(self) -> list[dict]: ...
    def close(self) -> None: ...


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not base_url:
            raise CanvasError(
                "No Canvas base URL configured. Set CANVAS_BASE_URL in .env "
                "(e.g. https://canvas.cmu.edu/api/v1)."
            )
        if not token:
            raise CanvasError(
                "No Canvas token found. Run `canvas-copilot login` to store one."
            )
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> CanvasClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def web_base_url(self) -> str:
        """The Canvas web origin (the API base with ``/api/vN`` stripped)."""
        return re.sub(r"/api/v\d+/?$", "", str(self._client.base_url))

    # -- low level --------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if method.upper() != "GET":
            raise CanvasError(
                f"Canvas Copilot is read-only; refusing {method.upper()} {url}."
            )
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise CanvasError(f"Request to Canvas failed: {exc}") from exc

        if response.status_code == 401:
            raise CanvasError(
                "Canvas rejected the token (401). It may be expired or revoked; "
                "run `canvas-copilot login` with a fresh token."
            )
        if response.status_code == 403:
            raise CanvasError(
                "Canvas returned 403 — forbidden, or you have hit the API rate "
                "limit. Wait a moment and try again."
            )
        if response.status_code >= 400:
            raise CanvasError(
                f"Canvas returned {response.status_code} for {url}: {response.text[:200]}"
            )
        return response

    def _get_paginated(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict]:
        query: dict[str, Any] = dict(params or {})
        query.setdefault("per_page", _PER_PAGE)

        results: list[dict] = []
        next_url: str | None = path
        pages = 0
        while next_url and pages < _MAX_PAGES:
            # Only the first request needs params; Canvas's `next` link URL
            # already carries them forward.
            response = self._request(
                "GET", next_url, params=query if pages == 0 else None
            )
            payload = response.json()
            if isinstance(payload, list):
                results.extend(payload)
            else:
                results.append(payload)
            next_url = response.links.get("next", {}).get("url")
            pages += 1
        return results

    def _get_one(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return self._request("GET", path, params=params).json()

    # -- endpoints -------------------------------------------------------

    def get_current_user(self) -> User:
        return User.model_validate(self._get_one("/users/self"))

    def list_course_nicknames(self) -> list[CourseNickname]:
        raw = self._get_paginated("/users/self/course_nicknames")
        return [CourseNickname.model_validate(item) for item in raw]

    def list_favorite_course_ids(self) -> set[int]:
        """Course ids the user has starred (their Canvas dashboard courses)."""
        raw = self._get_paginated("/users/self/favorites/courses")
        return {item["id"] for item in raw if "id" in item}

    def list_courses(self, *, enrollment_state: str = "active") -> list[Course]:
        raw = self._get_paginated("/courses", {"enrollment_state": enrollment_state})
        nicknames = {n.course_id: n.nickname for n in self.list_course_nicknames()}
        favorites = self.list_favorite_course_ids()

        courses: list[Course] = []
        for item in raw:
            if "id" not in item:  # Canvas can return access-restricted stubs
                continue
            course = Course.model_validate(item)
            course.nickname = nicknames.get(course.id)
            course.is_favorite = course.id in favorites
            courses.append(course)

        # If the user has starred nothing, treat every active course as current.
        if not favorites:
            for course in courses:
                course.is_favorite = True
        return courses

    def get_todo(self) -> list[Assignment]:
        """The student's Canvas to-do list: assignments still needing submission."""
        raw = self._get_paginated("/users/self/todo")
        todo: list[Assignment] = []
        for item in raw:
            assignment = item.get("assignment")
            if assignment and "id" in assignment:
                todo.append(Assignment.model_validate(assignment))
        return todo

    def get_upcoming_events(self) -> list[dict]:
        """Raw upcoming events (assignments + calendar events) for ~the next week."""
        return self._get_paginated("/users/self/upcoming_events")

    def list_assignments(
        self,
        course_id: int,
        *,
        due_after: datetime | None = None,
        due_before: datetime | None = None,
    ) -> list[Assignment]:
        raw = self._get_paginated(
            f"/courses/{course_id}/assignments", {"include[]": "submission"}
        )
        assignments = [Assignment.model_validate(item) for item in raw]
        if due_after is not None:
            assignments = [a for a in assignments if a.due_at and a.due_at >= due_after]
        if due_before is not None:
            assignments = [a for a in assignments if a.due_at and a.due_at <= due_before]
        return assignments

    # -- unstructured content (for indexing) ---------------------------

    def get_syllabus(self, course_id: int) -> str | None:
        course = self._get_one(f"/courses/{course_id}", {"include[]": "syllabus_body"})
        return course.get("syllabus_body") or None

    def list_files(self, course_id: int) -> list[dict]:
        return self._get_paginated(f"/courses/{course_id}/files")

    def download_file(self, url: str) -> bytes:
        return self._request("GET", url).content

    def list_pages(self, course_id: int) -> list[Page]:
        raw = self._get_paginated(f"/courses/{course_id}/pages")
        return [Page.model_validate(item) for item in raw if item.get("url")]

    def get_page(self, course_id: int, page_url: str) -> Page:
        return Page.model_validate(
            self._get_one(f"/courses/{course_id}/pages/{page_url}")
        )

    def get_front_page(self, course_id: int) -> Page | None:
        try:
            return Page.model_validate(self._get_one(f"/courses/{course_id}/front_page"))
        except CanvasError:
            return None  # 404 when the course has no front page set

    def list_modules(self, course_id: int) -> list[Module]:
        raw = self._get_paginated(f"/courses/{course_id}/modules", {"include[]": "items"})
        web = self.web_base_url
        modules = []
        for item in raw:
            module = Module.model_validate(item)
            module.html_url = f"{web}/courses/{course_id}/modules#module_{module.id}"
            modules.append(module)
        return modules

    def list_announcements(self, course_id: int) -> list[Announcement]:
        raw = self._get_paginated(
            "/announcements",
            {"context_codes[]": f"course_{course_id}", "per_page": 50},
        )
        return [Announcement.model_validate(item) for item in raw]
