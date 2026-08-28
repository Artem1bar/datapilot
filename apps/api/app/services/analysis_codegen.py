"""Code export: the same analysis, as a script someone else can run.

The pipeline's claim is that every reported number was computed from the
uploaded file by deterministic code rather than produced by a model. Provenance
(:mod:`app.services.analysis_provenance`) states that claim; this module makes
it checkable. For a validated spec it renders the equivalent Python or R —
imports, a load line the reader edits, the filter, then one commented block per
operation — so a researcher can rerun the analysis in their own environment and
confirm the figure, or discover that it does not hold.

That only works if the export is faithful, so the export is a transcript rather
than a tidier reimplementation, and the tests execute the generated Python
against the same frame and compare it with the pipeline's own output.

Two dialects, one shape::

    export_code(spec, language="python")   # pandas / numpy / scipy
    export_code(spec, language="r")        # dplyr / tidyr / base stats

An operation with no emitter is never silently dropped. It becomes a comment
carrying :data:`NO_EQUIVALENT_MARKER` and the parameters it was given, because
an export that quietly omits a step reads as a complete reproduction and is not
one. Tiers 1 to 3 register their emitters from the two dialect modules; Tiers 4
to 6 — the models, which need statsmodels on one side and the survey package on
the other — register from the ``_models`` module beside each dialect, imported
here so that importing this façade is enough to have the whole registry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Imported for the side effect of registering: importing the façade must be
# enough to see every operation, or unsupported_operations would report a gap
# that exists only because nobody imported the module that fills it.
from app.services import (
    analysis_codegen_python_models,  # noqa: F401  (registers tiers 4-6)
    analysis_codegen_r_models,  # noqa: F401  (registers tiers 4-6)
)
from app.services.analysis_codegen_python import (  # noqa: F401  (re-exported)
    PYTHON_EMITTERS,
    Emitter,
    Lines,
    comment_text,
    py_literal,
    python_load_statement,
)
from app.services.analysis_codegen_python import filter_block as _python_filter
from app.services.analysis_codegen_python import preamble as _python_preamble
from app.services.analysis_codegen_r import (  # noqa: F401  (re-exported)
    R_EMITTERS,
    r_comment_text,
    r_literal,
    r_load_statement,
)
from app.services.analysis_codegen_r import filter_block as _r_filter
from app.services.analysis_codegen_r import preamble as _r_preamble
from app.services.analysis_provenance import environment

DEFAULT_SOURCE = "data.csv"

# Searched for by the tests, and worth surfacing in the UI: an export carrying
# this marker is incomplete, and saying so is the whole point of emitting it.
NO_EQUIVALENT_MARKER = "NO CODE EQUIVALENT YET"


@dataclass(frozen=True)
class _Dialect:
    """One target language: how it quotes, comments, loads and is registered.

    ``emitters`` is the live registry dict, not a copy, so a tier module that
    registers an emitter after this module is imported is still picked up.
    """

    name: str
    emitters: dict[str, Emitter]
    literal: Callable[[Any], str]
    comment: Callable[[Any], str]
    preamble: Callable[..., Lines]
    filter_block: Callable[[dict[str, Any] | None], Lines]
    note: str


_PYTHON = _Dialect(
    name="Python",
    emitters=PYTHON_EMITTERS,
    literal=py_literal,
    comment=comment_text,
    preamble=_python_preamble,
    filter_block=_python_filter,
    note=(
        "This is the same library stack the product used, so the numbers should "
        "match to the last digit rather than approximately."
    ),
)

_R = _Dialect(
    name="R",
    emitters=R_EMITTERS,
    literal=r_literal,
    comment=r_comment_text,
    preamble=_r_preamble,
    filter_block=_r_filter,
    note=(
        "R computed nothing in the product. Its defaults differ from scipy's in a "
        "few places — exact versus asymptotic rank tests, the odds ratio "
        "fisher.test reports — and every such place is called out in a comment "
        "beside the line it affects. Everywhere else the numbers should match."
    ),
)

_DIALECTS: dict[str, _Dialect] = {"python": _PYTHON, "r": _R}


def supported_operations(language: str) -> frozenset[str]:
    """Operations this language can currently express."""
    return frozenset(_dialect(language).emitters)


def unsupported_operations(spec: dict[str, Any], *, language: str) -> list[str]:
    """Operations in *spec* that the export cannot reproduce, in spec order.

    A non-empty list means the emitted script is an incomplete record of the
    analysis, which is a thing to tell the user rather than to discover later.
    """
    emitters = _dialect(language).emitters
    return [
        str(operation.get("op"))
        for operation in _operations(spec)
        if str(operation.get("op")) not in emitters
    ]


def export_code(
    spec: dict[str, Any],
    *,
    language: str,
    source: str = DEFAULT_SOURCE,
    question: str | None = None,
) -> str:
    """Render a validated *spec* as a runnable script in *language*.

    *source* is the path written into the load line — the one line a reader
    edits. *question* heads the script; without it the spec's rationale is used,
    since a script whose purpose is not stated is a script nobody trusts.
    """
    dialect = _dialect(language)
    operations = _operations(spec)
    lines = _header(spec, question=question, dialect=dialect)
    lines += dialect.preamble(source=source, ops=[str(op.get("op")) for op in operations])
    lines += dialect.filter_block(spec.get("filter"))
    for position, operation in enumerate(operations, start=1):
        lines += ["", ""] + _block(operation, position, dialect)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _dialect(language: str) -> _Dialect:
    dialect = _DIALECTS.get(str(language).lower())
    if dialect is None:
        raise ValueError(f"unknown export language {language!r} (allowed: {sorted(_DIALECTS)})")
    return dialect


def _operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The spec's operations, or none at all for a refusal."""
    if not isinstance(spec, dict) or spec.get("refusal"):
        return []
    operations = spec.get("operations")
    return [item for item in operations if isinstance(item, dict)] if operations else []


def _header(spec: dict[str, Any], *, question: str | None, dialect: _Dialect) -> Lines:
    """What this script answers, what produced the original numbers, and the claim."""
    versions = environment()
    purpose = comment_text(question or spec.get("rationale") or "Analysis exported from DataPilot")
    rule = "# " + "=" * 75
    lines = [
        rule,
        f"# {purpose}",
        "#",
        f"# Equivalent {dialect.name} for an analysis DataPilot ran. Point the load line",
        "# below at the same file and this script reproduces the figures the product",
        "# reported — that is the claim, and it is meant to be checked.",
        "#",
        "# The product computed those figures with:",
        f"#   Python {versions.get('python', '?')}"
        f" · pandas {versions.get('pandas', '?')}"
        f" · numpy {versions.get('numpy', '?')}"
        f" · scipy {versions.get('scipy', '?')}",
        "#",
    ]
    lines += [f"# {line}" for line in _wrap(dialect.note)]
    lines += [rule, ""]
    return lines


def _wrap(text: str, width: int = 74) -> Lines:
    """Fold prose to a comment width without pulling in textwrap's edge cases."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _block(operation: dict[str, Any], position: int, dialect: _Dialect) -> Lines:
    op = str(operation.get("op"))
    label = str(operation.get("label") or op.replace("_", " ").title())
    params = operation.get("params") or {}
    heading = f"# --- [{position}] {dialect.comment(label)}  ({dialect.comment(op)}) ---"

    emitter = dialect.emitters.get(op)
    if emitter is None:
        return [heading] + _no_equivalent(op, params, dialect)
    return [heading] + list(emitter(params, label, position))


def _no_equivalent(op: str, params: dict[str, Any], dialect: _Dialect) -> Lines:
    """Admit the gap rather than leave a hole a reader cannot see."""
    return [
        f"# {NO_EQUIVALENT_MARKER}: DataPilot cannot express"
        f" {dialect.comment(op)} as {dialect.name} yet,",
        "# so this step is NOT reproduced below and this script is an incomplete",
        "# record of the analysis. The product's own result for it still stands.",
        f"# It was run with: {dialect.comment(params)}",
    ]
