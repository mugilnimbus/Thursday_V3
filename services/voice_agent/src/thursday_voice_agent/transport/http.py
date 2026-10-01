"""HTTP surface: chat turns (NDJSON stream, from the gateway), the A2A push webhook (from the main
agent), and management (replay, prompts). All but the webhook need the service token; the
webhook checks the per-task push token instead."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from thursday_llm.providers import ProviderError
from thursday_llm.runtime import LlmOverrides, LlmRuntime, LoadOverrides
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.outbox import OutboxStore

from thursday_voice_agent.application.conversation import Conversation, Project, VoiceModelUnavailable
from thursday_voice_agent.application.prompts import DEFAULT_SYSTEM_PROMPT
from thursday_voice_agent.application.tasks import TaskRelay
from thursday_voice_agent.infrastructure.store import Store

log = logging.getLogger(__name__)


class TurnIn(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=20_000)
    project_id: str = Field(min_length=1, max_length=64)
    project_folder: str = Field(min_length=1, max_length=4096)


class PromptIn(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


def build_router(
    conversation: Conversation,
    relay: TaskRelay,
    store: Store,
    outbox: OutboxStore,
    auth: ServiceTokenAuth,
    llm: LlmRuntime,
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
        record = store.task(task["id"])
        spoken = relay.apply(task)
        if spoken and record is not None:
            relay.say(record.chat_id, spoken)
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

    @router.get("/llm", dependencies=guarded)
    async def llm_settings() -> dict[str, Any]:
        return {**llm.describe(), "reachable": await llm.provider.reachable()}

    @router.put("/llm", dependencies=guarded)
    async def update_llm(body: LlmOverrides) -> dict[str, Any]:
        await llm.update(body)
        return llm.describe()

    @router.post("/llm/reload-keys", dependencies=guarded)
    async def reload_keys() -> dict[str, Any]:
        await llm.reload_keys()
        return llm.describe()

    @router.post("/model/{action}", dependencies=guarded)
    async def model_action(action: str, body: LoadOverrides | None = None) -> dict[str, Any]:
        try:
            if action == "load":
                await llm.provider.ensure_loaded()
            elif action == "reload":
                await llm.reload_model(body)
            elif action == "unload":
                await llm.provider.unload()
            else:
                raise HTTPException(404, "unknown action")
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc
        return llm.describe()

    return router
