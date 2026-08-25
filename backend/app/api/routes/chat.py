"""Conversational assistant: SSE endpoint with contextual injection.

Flow (decision D9): one structured LLM call returns assistant_message +
proposed_items as validated JSON; the SSE channel then streams the message
progressively and emits the proposal as a discrete event. This keeps a single
LLM round-trip (no double latency/cost) while preserving a streaming UX and
full provider-agnosticism (works identically against OpenAI, Gemini compat,
and Ollama).

Proposals are persisted ONLY as chat metadata — meal logs are written
exclusively by POST /api/meal-logs after user confirmation (zero silent
mutations).
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_profile
from app.api.routes.meals import consumed_for_day
from app.db import get_session
from app.models import ChatMessage, UserProfile
from app.schemas.api import ChatRequest
from app.schemas.llm_contracts import LogProposalResponse
from app.services.llm import get_llm

router = APIRouter(prefix="/api/chat", tags=["chat"])

CHAT_SYSTEM = """You are PlateOS, a concise, empathetic nutrition coach for a single
self-hosted user. Voice: warm, direct, never preachy. Keep replies short
(2-4 sentences) unless asked to elaborate.

When the user describes food they ate, ALWAYS return proposed_items covering
every distinct food, with your best weight estimate in grams and the macro
totals for that weight. State your portion assumptions briefly in reasoning
(raw vs cooked weight, oil absorbed, drained canned goods, dry vs cooked
pasta). Include a per100 density consistent with your estimates so totals can
be recomputed if the user edits quantities. When the user asks a question
instead, proposed_items may be empty. Never log anything yourself — the user
confirms every proposal manually."""


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def build_context(session: AsyncSession, profile: UserProfile) -> str:
    """Contextual injector: now, today's budget state, last 3 days of trends."""
    tz_name = profile.timezone
    now = datetime.now(ZoneInfo(tz_name))
    today = now.date()

    consumed = await consumed_for_day(session, profile, today)
    targets = {
        "calories": profile.target_calories,
        "protein_g": profile.target_protein_g,
        "carbs_g": profile.target_carbs_g,
        "fat_g": profile.target_fat_g,
    }
    lines = [
        f"Current local date/time: {now.strftime('%A %Y-%m-%d %H:%M')} ({tz_name}).",
        "Today's budget:",
        f"- calories: {consumed['calories']:.0f} consumed / {targets['calories']} target"
        f" ({targets['calories'] - consumed['calories']:.0f} remaining)",
        f"- protein: {consumed['protein_g']:.0f}g / {targets['protein_g']}g"
        f" ({targets['protein_g'] - consumed['protein_g']:.0f}g remaining)",
        f"- carbs: {consumed['carbs_g']:.0f}g / {targets['carbs_g']}g",
        f"- fat: {consumed['fat_g']:.0f}g / {targets['fat_g']}g",
        "Last 3 days total calories:",
    ]
    for i in range(1, 4):
        day = now.date() - timedelta(days=i)
        day_consumed = await consumed_for_day(session, profile, day)
        lines.append(f"- {day.isoformat()}: {day_consumed['calories']:.0f} kcal, "
                     f"{day_consumed['protein_g']:.0f}g protein")
    return "\n".join(lines)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    profile: UserProfile = Depends(get_current_profile),
    session: AsyncSession = Depends(get_session),
):
    async def event_stream():
        try:
            llm = get_llm("text")
            context = await build_context(session, profile)
            proposal = await llm.extract_json(
                system=CHAT_SYSTEM + "\n\n# User context\n" + context,
                prompt=body.message,
                schema=LogProposalResponse,
            )

            sid = body.session_id or uuid.uuid4()
            session.add(
                ChatMessage(user_id=profile.id, session_id=sid, role="user", content=body.message)
            )
            session.add(
                ChatMessage(
                    user_id=profile.id,
                    session_id=sid,
                    role="assistant",
                    content=proposal.assistant_message,
                    tool_calls={"proposed_items": [p.model_dump() for p in proposal.proposed_items]},
                )
            )
            await session.commit()

            words = proposal.assistant_message.split(" ")
            for i in range(0, len(words), 3):
                yield _sse("delta", {"text": " ".join(words[i : i + 3]) + " "})
                await asyncio.sleep(0.02)

            if proposal.proposed_items:
                yield _sse("proposal", json.loads(proposal.model_dump_json()))
            yield _sse("done", {"session_id": str(sid)})
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
