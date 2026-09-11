"""Tests for the cleaning operation catalogue.

The catalogue is what the review card renders: it tells the editor which
operations exist, which need a target column, and what each parameter is
called and typed. Because a human now edits plans by hand, a catalogue that
disagrees with the executor or the validator would offer fields that silently
do nothing — so the agreement is pinned here rather than trusted.
"""

from __future__ import annotations

from app.services.cleaning import supported_operations
from app.services.cleaning_catalog import (
    CATALOG,
    column_optional_operations,
    operation_spec,
    required_params,
)
from app.services.plan_validator import COLUMN_OPTIONAL_OPS, validate_plan


class TestCatalogCoversExecutor:
    def test_every_executable_operation_is_described(self):
        """No operation the executor can run is missing from the editor."""
        assert set(CATALOG) == supported_operations()

    def test_no_described_operation_is_unexecutable(self):
        """The editor never offers an operation the executor would reject."""
        for name in CATALOG:
            assert name in supported_operations()

    def test_every_operation_has_a_label_and_group(self):
        for name, spec in CATALOG.items():
            assert spec.label, f"{name} has no human label"
            assert spec.group, f"{name} has no group"
            assert spec.summary, f"{name} has no summary"

    def test_operation_spec_lookup(self):
        assert operation_spec("fill_null").name == "fill_null"
        assert operation_spec("not_an_operation") is None


class TestCatalogMatchesValidator:
    def test_column_optional_ops_agree(self):
        """Operations the editor lets you leave column-less are the same ones
        the validator lets through without a column."""
        assert column_optional_operations() == COLUMN_OPTIONAL_OPS

    def test_required_params_agree_with_validator(self):
        """A param the catalogue marks required is one the validator enforces."""
        # These are the operations the validator refuses without a param.
        expected = {
            "drop_rows": {"indices"},
            "cap_extreme_values": {"max_value"},
            "flag_contextual_fraud": {"threshold"},
            "rename_column": {"new_name"},
            "standardize_values": {"mapping"},
        }
        actual = {op: names for op, names in required_params().items() if names}
        assert actual == expected

    def test_catalogue_param_names_are_the_ones_the_executor_reads(self):
        """Spot-check the params against the executor's own ``params.get`` keys.

        A renamed field here would render an input that changes nothing.
        """
        assert {p.name for p in operation_spec("fill_null").params} == {"strategy", "value"}
        assert {p.name for p in operation_spec("cast_type").params} == {"target_type"}
        assert {p.name for p in operation_spec("rename_column").params} == {"new_name"}
        assert {p.name for p in operation_spec("deduplicate").params} == {"subset"}
        assert {p.name for p in operation_spec("cap_extreme_values").params} == {"max_value"}
        assert {p.name for p in operation_spec("drop_incomplete_responses").params} == {
            "progress_column",
            "finished_column",
            "min_progress",
        }

    def test_enum_choices_match_the_executor_branches(self):
        """cast_type's dropdown offers exactly the casts the executor implements."""
        target = next(p for p in operation_spec("cast_type").params if p.name == "target_type")
        assert set(target.choices) == {"int", "float", "datetime", "str"}

        strategy = next(p for p in operation_spec("fill_null").params if p.name == "strategy")
        assert set(strategy.choices) == {"mean", "median", "mode"}


class TestCatalogRoundTrip:
    @staticmethod
    def _default_step(name: str) -> dict:
        spec = CATALOG[name]
        return {
            "operation": name,
            "column": "Amount" if spec.requires_column else None,
            "params": spec.default_params(),
            "description": spec.label,
        }

    def test_added_step_validates_unless_it_needs_a_value_from_the_user(self):
        """ "Add step" produces something the executor accepts.

        The exceptions are operations whose whole point is a value only the
        user can supply (the cap ceiling, the new column name) — those must
        arrive at the validator as a *named missing param*, so the editor can
        mark the field instead of failing at dispatch.
        """
        columns = ["Amount", "Name", "City"]
        needs_user_value = {
            "cap_extreme_values",
            "flag_contextual_fraud",
            "rename_column",
            "fill_null",  # needs a strategy or a fixed value
        }

        for name in CATALOG:
            issues = validate_plan([self._default_step(name)], supported_operations(), columns)
            if name in needs_user_value:
                assert issues, f"{name} should report its missing param"
                assert all(issue.field == "params" for issue in issues)
            else:
                assert issues == [], f"{name} default step does not validate: {issues}"

    def test_either_or_params_are_declared_so_the_editor_can_mark_both(self):
        """fill_null is valid with a strategy *or* a value — the catalogue says so."""
        from app.services.cleaning_catalog import requires_one_of

        assert requires_one_of()["fill_null"] == (("strategy", "value"),)

    def test_params_the_user_must_supply_are_marked_required_without_a_default(self):
        """The editor decides what to mark red from the catalogue alone."""
        for name in ("cap_extreme_values", "flag_contextual_fraud", "rename_column"):
            missing = [p for p in CATALOG[name].params if p.required and p.default is None]
            assert missing, f"{name} has nothing marked as needing a user value"

    def test_serialization_is_json_ready(self):
        """The catalogue crosses the wire to the editor, so it must serialize."""
        import json

        from app.services.cleaning_catalog import catalog_payload

        payload = catalog_payload()
        json.dumps(payload)  # raises if anything is not JSON-serializable
        names = {entry["name"] for entry in payload["operations"]}
        assert names == supported_operations()
