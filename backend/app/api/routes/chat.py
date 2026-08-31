"""SSE transport for the constrained assistant harness (D39)."""

import json
import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.db import get_session
from app.models import ChatMessage, UserProfile
from app.schemas.api import ChatRequest
from app.schemas.llm_contracts import MealProposalBlock
from app.services.assistant import run_assistant

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    sid = body.session_id or uuid.uuid4()
    response_id = uuid.uuid4()

    async def event_stream():
        yield _sse(
            "meta",
            {
                "schema_version": "1",
                "session_id": str(sid),
                "response_id": str(response_id),
            },
        )
        try:
            response = await run_assistant(session, profile, body)
            session.add(
                ChatMessage(
                    user_id=profile.id,
                    session_id=sid,
                    role="user",
                    content=body.message,
                )
            )
            session.add(
                ChatMessage(
                    user_id=profile.id,
                    session_id=sid,
                    role="assistant",
                    content=response.assistant_message,
                    tool_calls={
                        "schema_version": response.schema_version,
                        "blocks": [block.model_dump(mode="json") for block in response.blocks],
                    },
                )
            )
            await session.commit()

            words = response.assistant_message.split(" ")
            for index in range(0, len(words), 4):
                yield _sse("delta", {"text": " ".join(words[index : index + 4]) + " "})

            for index, block in enumerate(response.blocks):
                dumped = block.model_dump(mode="json")
                yield _sse(
                    "block",
                    {
                        "schema_version": "1",
                        "response_id": str(response_id),
                        "index": index,
                        "block": dumped,
                    },
                )
                # One-release compatibility for clients that only understand meal proposals.
                if isinstance(block, MealProposalBlock):
                    yield _sse(
                        "proposal",
                        {
                            "assistant_message": response.assistant_message,
                            "proposed_items": dumped["items"],
                            "requires_user_confirmation": True,
                        },
                    )
            yield _sse(
                "done",
                {
                    "schema_version": "1",
                    "session_id": str(sid),
                    "response_id": str(response_id),
                    "block_count": len(response.blocks),
                },
            )
        except Exception:  # noqa: BLE001 - public error is deliberately sanitized
            logger.exception("Assistant request failed")
            await session.rollback()
            yield _sse(
                "error",
                {
                    "code": "assistant_unavailable",
                    "message": "The assistant could not complete this request. Check the provider and try again.",
                    "retryable": True,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
