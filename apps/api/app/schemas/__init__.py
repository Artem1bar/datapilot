"""Pydantic v2 schemas for DataPilot API."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class DatasetStatus(StrEnum):
    uploaded = "uploaded"
    profiling = "profiling"
    ready = "ready"
    error = "error"


class ExportFormat(StrEnum):
    csv = "csv"
    xlsx = "xlsx"
    parquet = "parquet"
    json = "json"


# ---------------------------------------------------------------------------
# Core domain schemas
# ---------------------------------------------------------------------------


class CleaningStep(BaseModel):
    """A single cleaning operation."""

    model_config = ConfigDict(from_attributes=True)

    operation: str = Field(
        ..., description="Cleaning operation name, e.g. drop_nulls, rename_column"
    )
    column: str | None = Field(None, description="Target column name")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Operation-specific parameters"
    )
    description: str = Field("", description="Human-readable description of this step")


class CleaningPlan(BaseModel):
    """An ordered list of cleaning steps proposed for a dataset."""

    model_config = ConfigDict(from_attributes=True)

    dataset_id: uuid.UUID
    steps: list[CleaningStep]
    summary: str = Field("", description="AI-generated summary of the plan")
    estimated_row_impact: int | None = Field(None, description="Estimated rows affected")


class AnalysisResult(BaseModel):
    """Result of an analysis chat turn."""

    model_config = ConfigDict(from_attributes=True)

    answer: str = Field(..., description="Natural-language answer")
    sql: str | None = Field(None, description="Generated SQL/pandas code, if any")
    charts: list[ChartConfig] = Field(default_factory=list)
    tables: list[TableResult] = Field(default_factory=list)
    provenance: dict[str, Any] | None = Field(
        None,
        description=(
            "What actually ran: operations, denominators, assumption checks, library "
            "versions, and a rendered methods note. Null when the analysis was refused "
            "or could not be computed."
        ),
    )
    tokens_used: int = Field(0)


class ChartConfig(BaseModel):
    """Configuration for a chart to render on the frontend."""

    chart_type: str = Field(..., description="E.g. bar, line, scatter, pie")
    title: str = ""
    x_field: str = ""
    y_field: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class TableResult(BaseModel):
    """Tabular data returned from analysis."""

    columns: list[str]
    rows: list[list[Any]]
    total_rows: int = 0


class JobUpdate(BaseModel):
    """Real-time job progress update (sent over WebSocket / SSE)."""

    job_id: uuid.UUID
    status: JobStatus
    progress: int = Field(0, ge=0, le=100)
    message: str = ""
    result: dict[str, Any] | None = None


# Fix forward reference in AnalysisResult
AnalysisResult.model_rebuild()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=500)
    content_type: str = Field("text/csv")
    file_size_bytes: int = Field(..., gt=0, le=500_000_000)  # max 500 MB


class ConfirmUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=500)
    file_size_bytes: int | None = None


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)
    session_id: uuid.UUID | None = None


class ScatterPlotRequest(BaseModel):
    """A scatter plot of one numeric column against another."""

    x: str = Field(..., min_length=1, max_length=500, description="Numeric column on the x axis")
    y: str = Field(..., min_length=1, max_length=500, description="Numeric column on the y axis")
    color_by: str | None = Field(
        None,
        min_length=1,
        max_length=500,
        description="Optional categorical column that colors the points",
    )
    size: str | None = Field(
        None,
        min_length=1,
        max_length=500,
        description="Optional numeric column that sizes the points (a bubble chart)",
    )


class ExportRequest(BaseModel):
    format: ExportFormat = ExportFormat.csv
    columns: list[str] | None = Field(None, description="Subset of columns to export; None = all")
    filters: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UploadUrlResponse(BaseModel):
    upload_url: str
    r2_key: str
    dataset_id: uuid.UUID


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    r2_key: str
    file_size_bytes: int | None = None
    sheet_names: list[str] | None = None
    row_count: int | None = None
    col_count: int | None = None
    status: str
    profile_json: dict[str, Any] | None = None
    created_at: datetime


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    type: str
    status: str
    progress: int
    result_json: dict[str, Any] | None = None
    error_text: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    messages_json: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Verification schemas
# ---------------------------------------------------------------------------


class VerificationStepResult(BaseModel):
    """Verification result for a single cleaning step."""

    step_index: int
    operation: str
    column: str | None = None
    passed: bool
    expected: str
    actual: str
    remaining_issues: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Full verification report for a cleaning job."""

    overall_passed: bool
    flags_resolved: list[str] = Field(default_factory=list)
    flags_remaining: list[str] = Field(default_factory=list)
    flags_new: list[str] = Field(default_factory=list)
    step_results: list[VerificationStepResult] = Field(default_factory=list)
    failed_steps: list[dict[str, Any]] = Field(default_factory=list)
    audit_completeness: float = Field(0.0, ge=0.0, le=1.0)
    agent_assessment: dict[str, Any] | None = None
    summary: str = ""


class CleaningRecipeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    steps_json: dict[str, Any]
    created_at: datetime
