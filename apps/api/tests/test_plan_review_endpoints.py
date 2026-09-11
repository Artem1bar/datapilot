"""The endpoints a human review card needs.

Three things change once a person edits a plan by hand:

* the editor has to know what operations exist and what they take
  (``GET /cleaning/operations``),
* an edit has to be checkable before it is dispatched
  (``POST /cleaning/{id}/plan/validate``),
* and ``apply`` can no longer trust its input. It used to receive only
  AI-generated steps that had already been validated at generation time;
  now it receives whatever a person typed, so it validates before dispatch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.cleaning import (
    ApplyCleaningRequest,
    ValidatePlanRequest,
    apply_cleaning_plan,
    list_operations,
    validate_cleaning_plan,
)
from app.schemas import CleaningStep

USER_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def no_redis():
    """Apply is budget-gated; the gate needs Redis, which these tests don't."""
    with (
        patch("app.services.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("app.services.rate_limit.enforce_ai_budget", new_callable=AsyncMock),
    ):
        yield


def _dataset(**overrides: object) -> MagicMock:
    dataset = MagicMock()
    dataset.id = DATASET_ID
    dataset.user_id = USER_ID
    dataset.filename = "sales.csv"
    dataset.status = "ready"
    dataset.row_count = 100
    dataset.profile_json = {"columns": {"Amount": {"dtype": "object"}, "City": {"dtype": "object"}}}
    for key, value in overrides.items():
        setattr(dataset, key, value)
    return dataset


def _dispatch_db(dataset: MagicMock) -> AsyncMock:
    """A mock session that behaves enough like a real one for a dispatch.

    ``refresh`` stamps the server-side defaults a real round-trip would fill
    in, so the handler's ``JobResponse.model_validate`` sees a complete row.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = dataset
    db.execute.return_value = result
    db.add = MagicMock()

    async def _refresh(obj: object) -> None:
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _step(operation: str, column: str | None = None, **params: object) -> dict:
    return {
        "operation": operation,
        "column": column,
        "params": params,
        "description": f"{operation} on {column}",
    }


# ---------------------------------------------------------------------------
# GET /cleaning/operations
# ---------------------------------------------------------------------------


class TestOperationCatalogEndpoint:
    @pytest.mark.asyncio
    async def test_returns_every_operation_with_its_params(self):
        payload = await list_operations()

        names = {entry["name"] for entry in payload["operations"]}
        assert "cap_extreme_values" in names
        assert "fill_null" in names

        cap = next(e for e in payload["operations"] if e["name"] == "cap_extreme_values")
        assert cap["label"]
        assert cap["requiresColumn"] is True
        assert [p["name"] for p in cap["params"]] == ["max_value"]
        assert cap["params"][0]["required"] is True

    @pytest.mark.asyncio
    async def test_groups_are_ordered_for_the_picker(self):
        payload = await list_operations()
        assert payload["groups"][0] == "Structural"
        assert set(payload["groups"]) >= {e["group"] for e in payload["operations"]}

    @pytest.mark.asyncio
    async def test_needs_no_dataset_and_no_ai_call(self):
        """The catalogue is static, so the editor can load it before an upload."""
        payload = await list_operations()
        assert payload["operations"]


# ---------------------------------------------------------------------------
# POST /cleaning/{dataset_id}/plan/validate
# ---------------------------------------------------------------------------


class TestValidatePlanEndpoint:
    @pytest.mark.asyncio
    async def test_clean_edit_reports_valid(self, make_user, make_db):
        body = ValidatePlanRequest(steps=[_step("strip_whitespace", "Amount")])
        result = await validate_cleaning_plan(
            DATASET_ID, body, make_user(user_id=USER_ID), make_db(_dataset())
        )
        assert result == {"valid": True, "issues": []}

    @pytest.mark.asyncio
    async def test_typo_in_a_column_name_is_named(self, make_user, make_db):
        body = ValidatePlanRequest(steps=[_step("strip_whitespace", "Amuont")])
        result = await validate_cleaning_plan(
            DATASET_ID, body, make_user(user_id=USER_ID), make_db(_dataset())
        )
        assert result["valid"] is False
        assert len(result["issues"]) == 1
        issue = result["issues"][0]
        assert issue["stepIndex"] == 0
        assert issue["field"] == "column"
        assert "Amuont" in issue["message"]

    @pytest.mark.asyncio
    async def test_missing_required_param_is_named(self, make_user, make_db):
        body = ValidatePlanRequest(steps=[_step("cap_extreme_values", "Amount")])
        result = await validate_cleaning_plan(
            DATASET_ID, body, make_user(user_id=USER_ID), make_db(_dataset())
        )
        assert result["valid"] is False
        assert result["issues"][0]["field"] == "params"
        assert "max_value" in result["issues"][0]["message"]

    @pytest.mark.asyncio
    async def test_issues_carry_the_index_of_the_step_that_has_them(self, make_user, make_db):
        body = ValidatePlanRequest(
            steps=[
                _step("strip_whitespace", "Amount"),
                _step("rename_column", "City"),  # no new_name
            ]
        )
        result = await validate_cleaning_plan(
            DATASET_ID, body, make_user(user_id=USER_ID), make_db(_dataset())
        )
        assert [i["stepIndex"] for i in result["issues"]] == [1]

    @pytest.mark.asyncio
    async def test_an_empty_plan_is_not_valid_to_apply(self, make_user, make_db):
        result = await validate_cleaning_plan(
            DATASET_ID,
            ValidatePlanRequest(steps=[]),
            make_user(user_id=USER_ID),
            make_db(_dataset()),
        )
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_unprofiled_dataset_is_a_conflict(self, make_user, make_db):
        body = ValidatePlanRequest(steps=[_step("strip_whitespace", "Amount")])
        with pytest.raises(HTTPException) as exc:
            await validate_cleaning_plan(
                DATASET_ID,
                body,
                make_user(user_id=USER_ID),
                make_db(_dataset(status="profiling", profile_json=None)),
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_someone_elses_dataset_is_a_404(self, make_user, make_db):
        body = ValidatePlanRequest(steps=[_step("strip_whitespace", "Amount")])
        with pytest.raises(HTTPException) as exc:
            await validate_cleaning_plan(DATASET_ID, body, make_user(), make_db(None))
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_validation_makes_no_ai_call(self, make_user, make_db):
        """Checking an edit must be instant and free — the editor calls it on
        every keystroke-settled change."""
        body = ValidatePlanRequest(steps=[_step("strip_whitespace", "Amount")])
        with patch("app.services.cleaning.generate_cleaning_plan") as generate:
            await validate_cleaning_plan(
                DATASET_ID, body, make_user(user_id=USER_ID), make_db(_dataset())
            )
        generate.assert_not_called()


# ---------------------------------------------------------------------------
# POST /cleaning/{dataset_id}/apply — now validates hand-edited steps
# ---------------------------------------------------------------------------


def _apply_body(*steps: dict, recipe_id: uuid.UUID | None = None) -> ApplyCleaningRequest:
    return ApplyCleaningRequest(
        steps=[CleaningStep.model_validate(s) for s in steps], recipe_id=recipe_id
    )


class TestApplyValidatesEditedSteps:
    @pytest.mark.asyncio
    async def test_hand_edited_bad_column_is_refused_before_dispatch(self, make_user, make_db):
        """The failure this prevents: a mistyped column silently no-ops and the
        user is told the cleaning succeeded."""
        db = make_db(_dataset())
        with patch("app.tasks.cleaning_task.clean_dataset") as task:
            with pytest.raises(HTTPException) as exc:
                await apply_cleaning_plan(
                    DATASET_ID,
                    _apply_body(_step("strip_whitespace", "Amuont")),
                    make_user(user_id=USER_ID),
                    db,
                )
        assert exc.value.status_code == 422
        assert "Amuont" in str(exc.value.detail)
        task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_required_param_is_refused_before_dispatch(self, make_user, make_db):
        with patch("app.tasks.cleaning_task.clean_dataset") as task:
            with pytest.raises(HTTPException) as exc:
                await apply_cleaning_plan(
                    DATASET_ID,
                    _apply_body(_step("cap_extreme_values", "Amount")),
                    make_user(user_id=USER_ID),
                    make_db(_dataset()),
                )
        assert exc.value.status_code == 422
        task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_valid_edited_plan_still_dispatches(self, make_user):
        db = _dispatch_db(_dataset())
        with patch("app.tasks.cleaning_task.clean_dataset") as task:
            task.delay.return_value = MagicMock(id="celery-1")
            job = await apply_cleaning_plan(
                DATASET_ID,
                _apply_body(_step("cap_extreme_values", "Amount", max_value=5000)),
                make_user(user_id=USER_ID, preferences={}),
                db,
            )
        assert task.delay.called
        assert job.type == "clean"
        assert job.status == "pending"

    @pytest.mark.asyncio
    async def test_recipe_provenance_is_recorded_on_the_job(self, make_user, make_db):
        """An edited recipe still applies through this endpoint, so the job has
        to remember which recipe it came from."""
        recipe_id = uuid.uuid4()
        db = _dispatch_db(_dataset())

        with patch("app.tasks.cleaning_task.clean_dataset") as task:
            task.delay.return_value = MagicMock(id="celery-2")
            await apply_cleaning_plan(
                DATASET_ID,
                _apply_body(_step("strip_whitespace", "Amount"), recipe_id=recipe_id),
                make_user(user_id=USER_ID, preferences={}),
                db,
            )

        added = db.add.call_args[0][0]
        assert added.input_json["recipe_id"] == str(recipe_id)

    @pytest.mark.asyncio
    async def test_no_recipe_id_leaves_no_recipe_key(self, make_user):
        db = _dispatch_db(_dataset())

        with patch("app.tasks.cleaning_task.clean_dataset") as task:
            task.delay.return_value = MagicMock(id="celery-3")
            await apply_cleaning_plan(
                DATASET_ID,
                _apply_body(_step("strip_whitespace", "Amount")),
                make_user(user_id=USER_ID, preferences={}),
                db,
            )

        assert "recipe_id" not in db.add.call_args[0][0].input_json
