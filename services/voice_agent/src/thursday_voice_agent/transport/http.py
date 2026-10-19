"""HTTP surface: chat turns (NDJSON stream, from the gateway), hearing a recording with the voice model,
the A2A push webhook (from the main agent), and management (replay, prompts). All but the webhook need the
service token; the webhook checks the per-task push token instead."""

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from thursday_contracts.retention import RETENTION_PATH, RetentionSetting
from thursday_llm import management
from thursday_llm.overrides import KeyChange, LlmOverrides, LoadOverrides
from thursday_llm.providers import ProviderError
from thursday_llm.runtime import LlmRuntime, ModelBusy
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.secret_store import SecretStoreError

from thursday_voice_agent.application.conversation import Conversation, Project
from thursday_voice_agent.application.errors import ChatDeleted, MainAgentRefused, MainAgentUnavailable
from thursday_voice_agent.application.model_stream import VoiceModelUnavailable
from thursday_voice_agent.application.ports import ManagementRecords, Outbox
from thursday_voice_agent.application.prompts import DEFAULT_SYSTEM_PROMPT
from thursday_voice_agent.application.retention import WorkingData
from thursday_voice_agent.application.tasks import TaskRelay
from thursday_voice_agent.domain.audio import MAX_HEAR_SECONDS, plausible, wav_seconds

log = logging.getLogger(__name__)


class TurnIn(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=20_000)
    project_id: str = Field(min_length=1, max_length=64)
    project_folder: str = Field(min_length=1, max_length=4096)


class PromptIn(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


CHAT_DELETED = "this chat was deleted"


def build_router(
    conversation: Conversation,
    relay: TaskRelay,
    store: ManagementRecords,
    outbox: Outbox,
    auth: ServiceTokenAuth,
    llm: LlmRuntime,
    retention: WorkingData,
) -> APIRouter:
    router = APIRouter(prefix="/v1")
    guarded = [Depends(auth)]

    @router.post("/chats/{chat_id}/turns", dependencies=guarded)
    async def turn(chat_id: str, body: TurnIn) -> StreamingResponse:
        stream = conversation.turn(
            chat_id, body.client_message_id, body.text, Project(body.project_id, body.project_folder)
        )
        try:
            first = await anext(stream)
        except ChatDeleted as exc:
            raise HTTPException(410, CHAT_DELETED) from exc
        except VoiceModelUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

        async def lines() -> AsyncIterator[bytes]:
            yield (json.dumps(first) + "\n").encode()
            try:
                async for part in stream:
                    yield (json.dumps(part) + "\n").encode()
            except Exception as exc:
                log.exception("turn failed", extra={"chat_id": chat_id})
                yield (json.dumps({"type": "error", "message": type(exc).__name__}) + "\n").encode()

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    @router.post("/hear", dependencies=guarded)
    async def hear(request: Request) -> dict[str, Any]:
        """Body: a WAV clip. The voice model itself writes down what is said.

        409 means "use speech-to-text instead": the model cannot hear, the clip is too long, or nothing was heard.
        """
        wav = await request.body()
        length = wav_seconds(wav)
        if length is None:
            raise HTTPException(422, "the recording must be a WAV clip")
        if length > MAX_HEAR_SECONDS:
            raise HTTPException(409, "the recording is too long for the model to hear")
        started = time.perf_counter()
        try:
            text = await llm.hear(wav)
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc
        if text is None:
            raise HTTPException(409, "the voice model cannot hear")
        if not text:
            raise HTTPException(409, "the voice model heard nothing")
        if not plausible(text, length):
            log.warning(
                "the voice model wrote %d words for a %.1f s clip; using speech-to-text", len(text.split()), length
            )
            raise HTTPException(409, "the voice model's words do not fit the recording")
        return {
            "text": text,
            "audio_seconds": round(length, 2),
            "seconds": round(time.perf_counter() - started, 3),
            "by": "voice_model",
        }

    @router.post("/chats/{chat_id}/direct", dependencies=guarded)
    async def direct(chat_id: str, body: TurnIn) -> dict[str, Any]:
        """Start a task from the user's words, unchanged, without the voice model. 503 means "try again later"."""
        try:
            return await conversation.direct(
                chat_id, body.client_message_id, body.text, Project(body.project_id, body.project_folder)
            )
        except ChatDeleted as exc:
            raise HTTPException(410, CHAT_DELETED) from exc
        except MainAgentUnavailable as exc:
            raise HTTPException(503, "the main agent is not reachable") from exc
        except MainAgentRefused as exc:
            raise HTTPException(409, f"the main agent refused the task: {exc}") from exc

    @router.delete("/chats/{chat_id}", status_code=204, dependencies=guarded)
    async def delete_chat(chat_id: str) -> None:
        store.delete_chat(chat_id)
        outbox.forget(chat_id=chat_id)

    @router.post("/push")
    async def push(request: Request) -> dict[str, Any]:
        body = await request.json()
        update = body.get("statusUpdate")
        task = body.get("task") or ({"id": update.get("taskId"), "status": update.get("status")} if update else None)
        if not task or not task.get("id"):
            return {"ignored": True}
        if not relay.push_token_ok(task["id"], request.headers.get("X-A2A-Notification-Token")):
            raise HTTPException(401, "bad push token")
        spoken = relay.apply(task)
        if spoken:
            relay.announce(task["id"], spoken)
        return {"spoken": bool(spoken)}

    @router.get("/replay", dependencies=guarded)
    async def replay(after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000)) -> dict[str, Any]:
        return {"events": outbox.after(after, limit)}

    @router.get("/prompt", dependencies=guarded)
    async def prompt() -> dict[str, Any]:
        current = store.current_prompt()
        return {"version": current[0] if current else 0, "text": current[1] if current else DEFAULT_SYSTEM_PROMPT}

    @router.put("/prompt", dependencies=guarded)
    async def save_prompt(body: PromptIn) -> dict[str, Any]:
        return {"version": store.save_prompt(body.text)}

    @router.get("/prompt/versions", dependencies=guarded)
    async def prompt_versions() -> dict[str, Any]:
        versions = [{"version": v, "created_at": c, "text": t} for v, c, t in store.prompt_versions()]
        return {"versions": versions, "default": DEFAULT_SYSTEM_PROMPT}

    @router.get(RETENTION_PATH, dependencies=guarded)
    async def get_retention() -> RetentionSetting:
        return RetentionSetting(days=retention.days)

    @router.put(RETENTION_PATH, dependencies=guarded)
    async def put_retention(body: RetentionSetting) -> RetentionSetting:
        """The gateway sends the period chosen in Settings. Repeating it changes nothing."""
        return RetentionSetting(days=retention.apply(body.days))

    @router.get("/llm", dependencies=guarded)
    async def llm_settings() -> dict[str, Any]:
        return await management.settings(llm)

    @router.put("/llm", dependencies=guarded)
    async def update_llm(body: LlmOverrides) -> dict[str, Any]:
        try:
            await llm.update(body)
        except ModelBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        return llm.describe()

    @router.put("/llm/key", dependencies=guarded)
    async def set_key(body: KeyChange) -> dict[str, Any]:
        try:
            await llm.set_key(body.key.get_secret_value().strip())
        except ModelBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except SecretStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        return llm.describe()

    @router.get("/models", dependencies=guarded)
    async def available_models() -> dict[str, Any]:
        return await management.available_models(llm)

    @router.post("/model/{action}", dependencies=guarded)
    async def model_action(action: str, body: LoadOverrides | None = None) -> dict[str, Any]:
        try:
            return await management.model_action(llm, action, body)
        except management.UnknownAction as exc:
            raise HTTPException(404, "unknown action") from exc
        except ModelBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc

    return router
