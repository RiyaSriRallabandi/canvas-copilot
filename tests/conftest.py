"""Shared pytest configuration.

Tests marked ``live`` hit the real Canvas API and are skipped unless
``--run-live`` is passed:

    uv run pytest --run-live
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked 'live' that call the real Canvas API",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="needs --run-live (calls the real Canvas API)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
