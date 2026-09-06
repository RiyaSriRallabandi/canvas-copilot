"""Opt-in tests that call the real Canvas API.

Run with:  uv run pytest --run-live

They use your stored token and CANVAS_BASE_URL, make only GET requests, and
assert loosely (your real data changes over time).
"""

from __future__ import annotations

import pytest

from canvas_copilot import auth
from canvas_copilot.canvas.client import CanvasClient
from canvas_copilot.config import get_settings

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_client():
    settings = get_settings()
    token = auth.get_token()
    if not settings.canvas_base_url or not token:
        pytest.skip("no CANVAS_BASE_URL or stored token; run `canvas-copilot login`")
    with CanvasClient(settings.canvas_base_url, token) as client:
        yield client


def test_whoami(live_client):
    user = live_client.get_current_user()
    assert user.id > 0
    assert user.name


def test_list_courses(live_client):
    courses = live_client.list_courses()
    assert isinstance(courses, list)
