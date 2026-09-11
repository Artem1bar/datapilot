"""What each cleaning operation is and what it takes — for humans, not the AI.

A cleaning plan is a machine artefact: ``{"operation": "cap_extreme_values",
"params": {"max_value": 5000}}``. Before it runs, a person has to be able to
read it, disagree with it, and change the 5000. That needs three things this
module supplies and nothing else did: a human label for every operation, which
operations act on a column, and what each parameter is called and typed.

The executor (:mod:`app.services.cleaning`) remains the authority on what those
params *do*; this catalogue only describes them. ``tests/test_cleaning_catalog``
pins the two together, and :mod:`app.services.plan_validator` derives its
required-param and column-optional tables from here so a plan cannot be
described one way and validated another.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal

#: How a param is edited, and what type the executor expects back.
ParamKind = Literal[
    "string",  # free text
    "number",  # float
    "integer",  # int
    "enum",  # one of `choices`
    "column",  # a single column name from the dataset
    "column_list",  # several column names
    "integer_list",  # e.g. row indices
    "mapping",  # {"old value": "new value", ...}
]

#: Python types each kind must satisfy, for the validator's isinstance checks.
_KIND_TYPES: dict[ParamKind, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "enum": str,
    "column": str,
    "column_list": list,
    "integer_list": list,
    "mapping": dict,
}


@dataclass(frozen=True)
class ParamSpec:
    """One editable parameter of a cleaning operation."""

    name: str
    kind: ParamKind
    label: str
    help: str = ""
    required: bool = False
    #: Value the editor starts from. ``None`` means the user must supply one —
    #: the step will not validate until they do.
    default: Any = None
    choices: tuple[str, ...] = ()

    @property
    def expected_type(self) -> type | tuple[type, ...]:
        return _KIND_TYPES[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "help": self.help,
            "required": self.required,
            "default": self.default,
            "choices": list(self.choices),
        }


@dataclass(frozen=True)
class OperationSpec:
    """One cleaning operation as a person sees it in the review card."""

    name: str
    label: str
    group: str
    summary: str
    requires_column: bool = True
    params: tuple[ParamSpec, ...] = ()
    #: Set on operations that discard rows or values outright, so the editor can
    #: say so before a person approves the plan.
    destructive: bool = False
    #: Groups of params where at least one must be supplied — fill_null needs
    #: either a strategy or a fixed value, and neither alone is required.
    requires_one_of: tuple[tuple[str, ...], ...] = ()

    def default_params(self) -> dict[str, Any]:
        """Starting params for a newly added step, omitting user-supplied ones.

        Copied, so a caller cannot reach back through the returned dict and
        mutate a spec's default list or mapping for every later caller.
        """
        return {p.name: copy.deepcopy(p.default) for p in self.params if p.default is not None}

    def param(self, name: str) -> ParamSpec | None:
        return next((p for p in self.params if p.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "group": self.group,
            "summary": self.summary,
            "requiresColumn": self.requires_column,
            "destructive": self.destructive,
            "requiresOneOf": [list(group) for group in self.requires_one_of],
            "params": [p.to_dict() for p in self.params],
        }


# ---------------------------------------------------------------------------
# Groups, in the order the executor is meant to run them. The editor shows this
# order in the "add step" picker so a person adding a step is nudged towards
# putting it in a sensible place.
# ---------------------------------------------------------------------------

GROUP_STRUCTURAL = "Structural"
GROUP_ROWS = "Row removal"
GROUP_FORMATTING = "Formatting"
GROUP_STANDARDIZATION = "Standardization"
GROUP_AGGREGATION = "Aggregation"
GROUP_ANOMALIES = "Anomalies"
GROUP_OTHER = "Other"

GROUP_ORDER: tuple[str, ...] = (
    GROUP_STRUCTURAL,
    GROUP_ROWS,
    GROUP_FORMATTING,
    GROUP_STANDARDIZATION,
    GROUP_AGGREGATION,
    GROUP_ANOMALIES,
    GROUP_OTHER,
)


def _whole_column(
    name: str, label: str, summary: str, *, group: str = GROUP_FORMATTING
) -> OperationSpec:
    """An operation that takes a column and no parameters."""
    return OperationSpec(name=name, label=label, group=group, summary=summary)


_SPECS: tuple[OperationSpec, ...] = (
    # ── Structural ────────────────────────────────────────────────────────
    OperationSpec(
        name="clean_column_names",
        label="Clean column names",
        group=GROUP_STRUCTURAL,
        summary="Trim spaces and non-breaking spaces from every column name.",
        requires_column=False,
    ),
    OperationSpec(
        name="drop_empty_columns",
        label="Drop empty columns",
        group=GROUP_STRUCTURAL,
        summary="Remove columns that hold no values at all.",
        requires_column=False,
        destructive=True,
    ),
    OperationSpec(
        name="drop_incomplete_responses",
        label="Drop unfinished responses",
        group=GROUP_STRUCTURAL,
        summary="Survey rows that never reached the end of the questionnaire.",
        requires_column=False,
        destructive=True,
        params=(
            ParamSpec(
                name="progress_column",
                kind="column",
                label="Progress column",
                default="Progress",
                help="Column holding completion percentage.",
            ),
            ParamSpec(
                name="finished_column",
                kind="column",
                label="Finished column",
                default="Finished",
                help="Column holding the completion flag.",
            ),
            ParamSpec(
                name="min_progress",
                kind="integer",
                label="Minimum progress",
                default=100,
                help="Rows below this are dropped.",
            ),
        ),
    ),
    # ── Row removal ───────────────────────────────────────────────────────
    OperationSpec(
        name="drop_rows",
        label="Drop specific rows",
        group=GROUP_ROWS,
        summary="Remove rows by their position in the file (0 = first row).",
        requires_column=False,
        destructive=True,
        params=(
            ParamSpec(
                name="indices",
                kind="integer_list",
                label="Row indices",
                required=True,
                default=[],
                help="Zero-based row numbers, e.g. 0, 1, 4.",
            ),
        ),
    ),
    # ── Formatting ────────────────────────────────────────────────────────
    _whole_column(
        "strip_whitespace",
        "Strip whitespace",
        "Remove leading and trailing spaces from every value.",
    ),
    _whole_column(
        "remove_currency_symbols",
        "Remove currency symbols",
        "Strip $, £, €, and thousands separators so the column can be numeric.",
    ),
    _whole_column(
        "extract_number",
        "Extract the number",
        'Pull the numeric part out of text like "about 40 hours".',
    ),
    _whole_column(
        "convert_number_words",
        "Convert number words",
        'Turn "twelve" into 12.',
    ),
    _whole_column(
        "convert_time_to_number",
        "Convert times to numbers",
        'Turn "1h 30m" into 1.5.',
    ),
    # ── Standardization ───────────────────────────────────────────────────
    _whole_column(
        "free_to_zero",
        'Read "free" as 0',
        'Values meaning no cost ("free", "n/a", "none") become 0.',
        group=GROUP_STANDARDIZATION,
    ),
    _whole_column(
        "remove_vague_entries",
        "Clear vague entries",
        'Values too vague to use ("some", "a few", "varies") become empty.',
        group=GROUP_STANDARDIZATION,
    ),
    OperationSpec(
        name="fill_null",
        label="Fill empty values",
        group=GROUP_STANDARDIZATION,
        summary="Replace missing values, either with a statistic or a fixed value.",
        requires_one_of=(("strategy", "value"),),
        params=(
            ParamSpec(
                name="strategy",
                kind="enum",
                label="Strategy",
                choices=("mean", "median", "mode"),
                help="Leave empty to use a fixed value instead.",
            ),
            ParamSpec(
                name="value",
                kind="string",
                label="Fixed value",
                help="Used when no strategy is chosen.",
            ),
        ),
    ),
    OperationSpec(
        name="drop_null",
        label="Drop rows with no value",
        group=GROUP_STANDARDIZATION,
        summary="Remove every row where this column is empty.",
        destructive=True,
    ),
    OperationSpec(
        name="cast_type",
        label="Change column type",
        group=GROUP_STANDARDIZATION,
        summary="Convert the column to a number, a date, or text.",
        params=(
            ParamSpec(
                name="target_type",
                kind="enum",
                label="Type",
                choices=("int", "float", "datetime", "str"),
                default="str",
                help="Values that will not convert become empty.",
            ),
        ),
    ),
    OperationSpec(
        name="standardize_values",
        label="Standardize values",
        group=GROUP_STANDARDIZATION,
        summary='Map inconsistent spellings onto one form ("NYC" → "New York").',
        params=(
            ParamSpec(
                name="mapping",
                kind="mapping",
                label="Replacements",
                required=True,
                default={},
                help="One line per replacement: original = replacement.",
            ),
        ),
    ),
    # ── Aggregation ───────────────────────────────────────────────────────
    OperationSpec(
        name="sum_composite_expenses",
        label="Sum composite amounts",
        group=GROUP_AGGREGATION,
        summary='Add up values written as a sum ("20 + 15 + 5" → 40).',
    ),
    # ── Anomalies ─────────────────────────────────────────────────────────
    OperationSpec(
        name="flag_extreme_outliers",
        label="Flag extreme outliers",
        group=GROUP_ANOMALIES,
        summary=(
            "Clear values far outside the column's own spread and mark those "
            "rows for review. Uses your outlier setting unless overridden."
        ),
        destructive=True,
        params=(
            ParamSpec(
                name="threshold",
                kind="number",
                label="Threshold override",
                help="Leave empty to use your Settings outlier threshold.",
            ),
            ParamSpec(
                name="flag_column",
                kind="string",
                label="Flag column",
                default="_flagged",
                help="Where the review marker is written.",
            ),
        ),
    ),
    OperationSpec(
        name="flag_contextual_fraud",
        label="Flag suspicious values",
        group=GROUP_ANOMALIES,
        summary="Mark rows whose value in this column exceeds a limit you set.",
        params=(
            ParamSpec(
                name="threshold",
                kind="number",
                label="Threshold",
                required=True,
                help="Values above this are flagged.",
            ),
            ParamSpec(
                name="flag_column",
                kind="string",
                label="Flag column",
                default="_flagged",
                help="Where the review marker is written.",
            ),
            ParamSpec(
                name="reason",
                kind="string",
                label="Reason",
                help="Text recorded alongside the flag.",
            ),
        ),
    ),
    OperationSpec(
        name="cap_extreme_values",
        label="Cap extreme values",
        group=GROUP_ANOMALIES,
        summary="Clear values above a ceiling you set — for obvious entry errors.",
        destructive=True,
        params=(
            ParamSpec(
                name="max_value",
                kind="number",
                label="Ceiling",
                required=True,
                help="Values above this are emptied.",
            ),
        ),
    ),
    # ── Other ─────────────────────────────────────────────────────────────
    OperationSpec(
        name="deduplicate",
        label="Remove duplicate rows",
        group=GROUP_OTHER,
        summary="Keep the first of each repeated row.",
        requires_column=False,
        destructive=True,
        params=(
            ParamSpec(
                name="subset",
                kind="column_list",
                label="Compare only these columns",
                help="Leave empty to compare whole rows.",
            ),
        ),
    ),
    OperationSpec(
        name="rename_column",
        label="Rename column",
        group=GROUP_OTHER,
        summary="Give the column a different name.",
        params=(
            ParamSpec(
                name="new_name",
                kind="string",
                label="New name",
                required=True,
                help="The name the column will have afterwards.",
            ),
        ),
    ),
    OperationSpec(
        name="remove_outliers",
        label="Drop outlier rows",
        group=GROUP_OTHER,
        summary=(
            "Delete rows sitting outside the column's IQR fence. Unlike "
            "flagging, this removes the whole row."
        ),
        destructive=True,
        params=(
            ParamSpec(
                name="threshold",
                kind="number",
                label="IQR multiplier",
                help="Leave empty to use your Settings outlier threshold.",
            ),
        ),
    ),
)

#: Every operation the review card can show, keyed by operation name.
CATALOG: dict[str, OperationSpec] = {spec.name: spec for spec in _SPECS}


def operation_spec(name: str) -> OperationSpec | None:
    """The spec for one operation, or ``None`` if it is not a known operation."""
    return CATALOG.get(name)


def column_optional_operations() -> set[str]:
    """Operations that legitimately run without a target column."""
    return {spec.name for spec in _SPECS if not spec.requires_column}


def required_params() -> dict[str, set[str]]:
    """Params that must be present, per operation."""
    return {spec.name: {p.name for p in spec.params if p.required} for spec in _SPECS}


def requires_one_of() -> dict[str, tuple[tuple[str, ...], ...]]:
    """Param groups where at least one member must be supplied, per operation."""
    return {spec.name: spec.requires_one_of for spec in _SPECS if spec.requires_one_of}


def required_param_types() -> dict[str, tuple[tuple[str, type | tuple[type, ...]], ...]]:
    """Required params as ``(name, expected_type)`` pairs, for the validator."""
    return {
        spec.name: tuple((p.name, p.expected_type) for p in spec.params if p.required)
        for spec in _SPECS
        if any(p.required for p in spec.params)
    }


def enum_choices(operation: str, param: str) -> tuple[str, ...]:
    """Allowed values for an enum param, or ``()`` if there is no such param."""
    spec = operation_spec(operation)
    found = spec.param(param) if spec else None
    return found.choices if found else ()


def catalog_payload() -> dict[str, Any]:
    """The catalogue in the shape the review card consumes."""
    return {
        "groups": list(GROUP_ORDER),
        "operations": [spec.to_dict() for spec in _SPECS],
    }
