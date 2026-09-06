"""Unit tests for CanvasClient. All HTTP is mocked — no network, no token."""

from __future__ import annotations

import httpx
import pytest

from canvas_copilot.canvas.client import CanvasClient, CanvasError

BASE = "https://canvas.example.edu/api/v1"


def make_client(handler) -> CanvasClient:
    return CanvasClient(BASE, "test-token", transport=httpx.MockTransport(handler))


def test_requires_base_url_and_token():
    with pytest.raises(CanvasError, match="base URL"):
        CanvasClient("", "tok")
    with pytest.raises(CanvasError, match="login"):
        CanvasClient(BASE, "")


def test_get_current_user_sends_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/users/self"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={"id": 7, "name": "Ada Lovelace", "primary_email": "ada@example.edu"},
        )

    with make_client(handler) as client:
        user = client.get_current_user()

    assert user.id == 7
    assert user.name == "Ada Lovelace"
    assert user.primary_email == "ada@example.edu"


def test_read_only_enforcement_blocks_non_get():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be sent for a blocked verb")

    with make_client(handler) as client:
        with pytest.raises(CanvasError, match="read-only"):
            client._request("POST", "/courses")


def test_pagination_follows_link_header():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "page=2" in str(request.url):
            return httpx.Response(200, json=[{"course_id": 2, "nickname": "B"}])
        return httpx.Response(
            200,
            json=[{"course_id": 1, "nickname": "A"}],
            headers={
                "Link": f'<{BASE}/users/self/course_nicknames?page=2>; rel="next"'
            },
        )

    with make_client(handler) as client:
        nicknames = client.list_course_nicknames()

    assert [n.course_id for n in nicknames] == [1, 2]
    assert len(seen) == 2


def test_401_gives_actionable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": [{"message": "Invalid token"}]})

    with make_client(handler) as client:
        with pytest.raises(CanvasError, match="login"):
            client.get_current_user()


def test_403_mentions_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Rate Limit Exceeded")

    with make_client(handler) as client:
        with pytest.raises(CanvasError, match="rate"):
            client.get_current_user()


def _course_list_handler(courses, nicknames=None, favorites=None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/course_nicknames"):
            return httpx.Response(200, json=nicknames or [])
        if path.endswith("/favorites/courses"):
            return httpx.Response(200, json=favorites or [])
        if path.endswith("/courses"):
            return httpx.Response(200, json=courses)
        return httpx.Response(404)

    return handler


def test_list_courses_merges_nicknames_and_favorites():
    handler = _course_list_handler(
        courses=[
            {"id": 10, "name": "Intro to AI", "course_code": "11-411"},
            {"id": 20, "name": "Statistics", "course_code": "36-700"},
            {"access_restricted_by_date": True},
        ],
        nicknames=[{"course_id": 10, "nickname": "AI"}],
        favorites=[{"id": 20}],
    )
    with make_client(handler) as client:
        courses = client.list_courses()

    by_id = {c.id: c for c in courses}
    assert set(by_id) == {10, 20}  # the restricted stub is dropped
    assert by_id[10].nickname == "AI"
    assert by_id[10].is_favorite is False
    assert by_id[20].is_favorite is True


def test_list_courses_marks_all_favorite_when_none_starred():
    handler = _course_list_handler(
        courses=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        favorites=[],
    )
    with make_client(handler) as client:
        courses = client.list_courses()

    assert all(c.is_favorite for c in courses)


def test_list_assignments_filters_by_due_window():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": 1, "name": "HW1", "due_at": "2026-09-01T23:59:00Z"},
                {"id": 2, "name": "HW2", "due_at": "2026-09-10T23:59:00Z"},
                {"id": 3, "name": "No due date", "due_at": None},
            ],
        )

    from datetime import datetime, timezone

    with make_client(handler) as client:
        due = client.list_assignments(
            99,
            due_after=datetime(2026, 9, 5, tzinfo=timezone.utc),
            due_before=datetime(2026, 9, 15, tzinfo=timezone.utc),
        )

    assert [a.id for a in due] == [2]
