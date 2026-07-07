"""Analysis / chat endpoints."""

from __future__ import annotations

import asyncio
import io
import logging
import uuid

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DBSession
from app.models.chat_session import ChatSession
from app.models.dataset import Dataset
from app.schemas import ChatMessageRequest, ChatSessionResponse
from app.services.analysis import analyze_data
from app.services.storage import download_file_bytes
from app.utils.dataframe import to_sample_records

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


def _read_sample_rows(file_bytes: bytes, filename: str, n: int = 20) -> list[dict]:
    """Read the first *n* rows from a dataset file and return them as a list of dicts."""
    lower = filename.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        df = pd.read_excel(io.BytesIO(file_bytes), nrows=n)
    elif lower.endswith(".parquet"):
        df = pd.read_parquet(io.BytesIO(file_bytes))
        df = df.head(n)
    else:
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=n)

    return to_sample_records(df)


@router.post(
    "/{dataset_id}/chat", response_model=ChatSessionResponse, status_code=status.HTTP_200_OK
)
async def chat(
    dataset_id: uuid.UUID,
    body: ChatMessageRequest,
    user: CurrentUser,
    db: DBSession,
) -> ChatSessionResponse:
    """Send a natural-language question about a dataset."""
    from app.services.rate_limit import check_rate_limit

    await check_rate_limit(str(user.id), action="analysis_chat", max_calls=30, window_seconds=3600)

    result = await db.execute(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    if not dataset.profile_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset has not been profiled yet. Please wait for profiling to complete.",
        )

    # Load or create chat session
    session: ChatSession | None = None
    if body.session_id is not None:
        sess_result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == body.session_id,
                ChatSession.dataset_id == dataset_id,
                ChatSession.user_id == user.id,
            )
        )
        session = sess_result.scalar_one_or_none()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
            )

    if session is None:
        session = ChatSession(
            id=uuid.uuid4(),
            dataset_id=dataset.id,
            user_id=user.id,
            messages_json=[],
        )
        db.add(session)

    # Download file and read sample rows — run sync IO in thread
    try:
        file_bytes = await asyncio.to_thread(download_file_bytes, dataset.r2_key)
        sample_rows = _read_sample_rows(file_bytes, dataset.filename)
    except Exception:
        logger.exception("Failed to download or read dataset file for dataset %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read dataset file.",
        )

    # Call Claude in a thread so we don't block the event loop
    history = list(session.messages_json) if session.messages_json else []
    analysis_result = await asyncio.to_thread(
        analyze_data,
        question=body.message,
        profile_json=dataset.profile_json,
        sample_rows=sample_rows,
        history=history,
    )

    # Append messages to the session
    messages = list(session.messages_json) if session.messages_json else []
    messages.append({"role": "user", "content": body.message})
    messages.append(
        {
            "role": "assistant",
            "content": analysis_result["answer"],
            "charts": analysis_result.get("charts", []),
            "tables": analysis_result.get("tables", []),
        }
    )
    session.messages_json = messages

    await db.commit()
    await db.refresh(session)

    return ChatSessionResponse.model_validate(session)


@router.get(
    "/{dataset_id}/sessions",
    response_model=list[ChatSessionResponse],
    status_code=status.HTTP_200_OK,
)
async def list_sessions(
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> list[ChatSessionResponse]:
    """List chat sessions for a dataset."""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.dataset_id == dataset_id, ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    sessions = result.scalars().all()
    return [ChatSessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/sessions/{session_id}", response_model=ChatSessionResponse, status_code=status.HTTP_200_OK
)
async def get_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> ChatSessionResponse:
    """Get a single chat session with message history."""
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    return ChatSessionResponse.model_validate(session)
