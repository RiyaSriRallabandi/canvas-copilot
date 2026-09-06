"""Read-only client for the Canvas LMS REST API.

Every request goes through :meth:`CanvasClient._request`, which refuses any HTTP
method other than GET. That method is the single enforcement point for Canvas
Copilot's read-only guarantee.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from canvas_copilot.canvas.models import Assignment, Course, CourseNickname, User

_MAX_PAGES = 50
_PER_PAGE = 100


class CanvasError(RuntimeError):
    """Raised when the Canvas API returns an error or the client is misconfigured."""


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
                f"Canvas returned {response.status_code} for {url}: "
                f"{response.text[:200]}"
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

    def list_courses(self, *, enrollment_state: str = "active") -> list[Course]:
        raw = self._get_paginated(
            "/courses", {"enrollment_state": enrollment_state}
        )
        nicknames = {n.course_id: n.nickname for n in self.list_course_nicknames()}

        courses: list[Course] = []
        for item in raw:
            if "id" not in item:  # Canvas can return access-restricted stubs
                continue
            course = Course.model_validate(item)
            course.nickname = nicknames.get(course.id)
            courses.append(course)
        return courses

    def list_assignments(
        self,
        course_id: int,
        *,
        due_after: datetime | None = None,
        due_before: datetime | None = None,
    ) -> list[Assignment]:
        raw = self._get_paginated(f"/courses/{course_id}/assignments")
        assignments = [Assignment.model_validate(item) for item in raw]
        if due_after is not None:
            assignments = [
                a for a in assignments if a.due_at and a.due_at >= due_after
            ]
        if due_before is not None:
            assignments = [
                a for a in assignments if a.due_at and a.due_at <= due_before
            ]
        return assignments
