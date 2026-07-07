"""Shared pytest fixtures for the DataPilot API test suite.

Most router/service tests call the handler coroutine directly with a mock user
and a mock ``AsyncSession``, and (for AI paths) a mocked Anthropic response
carrying a forced tool call. Those three shapes were hand-rolled in ~20 test
files; they live here now so new tests inherit them instead of copy-pasting.

The DB/user/response fixtures are *factory fixtures* (they yield a callable) so
each test can stamp out exactly the objects it needs while sharing the wiring.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@pytest.fixture
def make_user() -> Callable[..., MagicMock]:
    """Factory for a mock authenticated user (``get_current_user`` result).

    ``make_user()`` gives a fresh random id; pass ``user_id=`` to pin one, e.g.
    for ownership tests that need a stable id across the user and their rows.
    """

    def _make(user_id: uuid.UUID | None = None, **attrs: object) -> MagicMock:
        user = MagicMock()
        user.id = user_id or uuid.uuid4()
        for key, value in attrs.items():
            setattr(user, key, value)
        return user

    return _make


@pytest.fixture
def mock_user(make_user: Callable[..., MagicMock]) -> MagicMock:
    """A ready-to-use mock user with a random id."""
    return make_user()


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------


def _result_for(value: object) -> MagicMock:
    """Wrap a value in a mock ``Result``.

    A ``list`` is exposed via ``.scalars().all()``; anything else via
    ``.scalar_one_or_none()`` — matching how the routers consume queries.
    """
    result = MagicMock()
    if isinstance(value, list):
        result.scalars.return_value.all.return_value = value
    else:
        result.scalar_one_or_none.return_value = value
    return result


@pytest.fixture
def make_db() -> Callable[..., AsyncMock]:
    """Factory for a mock ``AsyncSession`` whose ``execute()`` calls return the
    given results in order.

    ``make_db(dataset, [job1, job2])`` → first ``await db.execute(...)`` yields a
    result with ``.scalar_one_or_none() == dataset``; the second yields one with
    ``.scalars().all() == [job1, job2]``. With no args, ``execute`` returns an
    empty (``None``) result so a bare ``make_db()`` still behaves.
    """

    def _make(*results: object) -> AsyncMock:
        db = AsyncMock()
        if results:
            db.execute.side_effect = [_result_for(r) for r in results]
        else:
            db.execute.return_value = _result_for(None)
        return db

    return _make


@pytest.fixture
def mock_db() -> AsyncMock:
    """A bare mock ``AsyncSession`` for tests that stub ``execute`` themselves or
    only assert on ``commit``/``add``/``execute`` calls."""
    return AsyncMock()


# ---------------------------------------------------------------------------
# Anthropic responses
# ---------------------------------------------------------------------------


@pytest.fixture
def anthropic_tool_response() -> Callable[..., MagicMock]:
    """Factory for a mock Anthropic ``Message`` carrying a single forced tool
    call, as ``structured_output.request_tool_call`` expects.

    ``anthropic_tool_response({"steps": [...]}, name="submit_cleaning_plan")``
    returns a response whose ``.content[0]`` is a ``tool_use`` block with
    ``.input`` set to the given payload.
    """

    def _make(
        payload: dict,
        *,
        name: str = "submit_cleaning_plan",
        tool_id: str = "toolu_test",
    ) -> MagicMock:
        block = MagicMock()
        block.type = "tool_use"
        block.name = name
        block.id = tool_id
        block.input = payload
        response = MagicMock()
        response.content = [block]
        return response

    return _make


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """A small mixed-type frame (nulls, whitespace, a numeric column) for
    executor/profile tests that just need *some* representative data."""
    return pd.DataFrame(
        {
            "name": ["  Alice ", "Bob", None, "Dave"],
            "amount": [10.0, None, 30.0, 40.0],
            "category": ["a", "a", "b", None],
        }
    )
