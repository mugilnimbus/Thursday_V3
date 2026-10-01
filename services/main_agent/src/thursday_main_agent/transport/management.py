"""Management API (service token), used by the gateway only. Keys and tokens are never returned.

Replay, allow-always rules, chat deletion, prompts, LLM settings and model lifecycle, behavior
settings, tool servers and the tool catalog.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from thursday_llm.providers import ProviderError
from thursday_llm.runtime import LlmOverrides, LlmRuntime, LoadOverrides
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.outbox import OutboxStore

from thursday_main_agent.infrastructure.store import Store


class PromptBody(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


class Behavior(BaseModel):
    compaction_threshold_percent: float = Field(ge=10, le=99)
    keep_awake_paused_minutes: float = Field(ge=0, le=24 * 60)


class BehaviorPatch(BaseModel):
    compaction_threshold_percent: float | None = Field(default=None, ge=10, le=99)
    keep_awake_paused_minutes: float | None = Field(default=None, ge=0, le=24 * 60)


class Tools(Protocol):
    async def list_tools(self, project_id: str, folder: str) -> list[Any]: ...

    async def stop_project(self, project_id: str) -> bool: ...

    def status(self) -> dict[str, dict[str, object]]: ...


def build_management_router(
    store: Store,
    outbox: OutboxStore,
    llm: LlmRuntime,
    auth: ServiceTokenAuth,
    delete_chat: Callable[[str], Awaitable[int]],
    delete_project: Callable[[str], Awaitable[dict[str, Any]]],
    status: Callable[[], dict[str, Any]],
    default_prompt: str,
    behavior: Callable[[], Behavior],
    apply_behavior: Callable[[Behavior], None],
    tools: Tools,
) -> APIRouter:
    router = APIRouter(prefix="/v1", dependencies=[Depends(auth)])

    @router.get("/replay")
    async def replay(after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000)) -> dict[str, Any]:
        return {"events": outbox.after(after, limit)}

    @router.get("/allow-rules")
    async def all_rules() -> dict[str, Any]:
        return {
            "rules": [
                {"chat_id": r.chat_id, "tool": r.tool, "created_at": r.created_at.isoformat()}
                for r in store.all_rules()
            ]
        }

    @router.get("/chats/{chat_id}/allow-rules")
    async def allow_rules(chat_id: str) -> dict[str, Any]:
        return {
            "rules": [{"tool": r.tool, "created_at": r.created_at.isoformat()} for r in store.rules_for_chat(chat_id)]
        }

    @router.delete("/chats/{chat_id}/allow-rules/{tool}", status_code=204)
    async def revoke_rule(chat_id: str, tool: str) -> None:
        store.revoke_rule(chat_id, tool)

    @router.delete("/chats/{chat_id}")
    async def remove_chat(chat_id: str) -> dict[str, Any]:
        """Delete saga participant: idempotent, safe to repeat."""
        return {"chat_id": chat_id, "deleted_tasks": await delete_chat(chat_id)}

    @router.delete("/projects/{project_id}")
    async def remove_project(project_id: str) -> dict[str, Any]:
        """Delete saga participant: idempotent, safe to repeat. The project folder itself is never touched."""
        return {"project_id": project_id, **(await delete_project(project_id))}

    @router.get("/prompt")
    async def prompt() -> dict[str, Any]:
        current = store.current_prompt()
        return {"version": current[0] if current else 0, "text": current[1] if current else default_prompt}

    @router.put("/prompt")
    async def save_prompt(body: PromptBody) -> dict[str, Any]:
        return {"version": store.save_prompt(body.text)}

    @router.get("/prompt/versions")
    async def prompt_versions() -> dict[str, Any]:
        versions = [{"version": v, "created_at": c, "text": t} for v, c, t in store.prompt_versions()]
        return {"versions": versions, "default": default_prompt}

    @router.get("/llm")
    async def llm_settings() -> dict[str, Any]:
        return {**llm.describe(), "reachable": await llm.provider.reachable()}

    @router.put("/llm")
    async def update_llm(body: LlmOverrides) -> dict[str, Any]:
        await llm.update(body)
        return llm.describe()

    @router.post("/llm/reload-keys")
    async def reload_keys() -> dict[str, Any]:
        await llm.reload_keys()
        return llm.describe()

    @router.get("/model")
    async def model() -> dict[str, Any]:
        return llm.describe()

    @router.post("/model/{action}")
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

    @router.get("/behavior")
    async def get_behavior() -> Behavior:
        return behavior()

    @router.put("/behavior")
    async def put_behavior(body: BehaviorPatch) -> Behavior:
        merged = Behavior.model_validate({**behavior().model_dump(), **body.model_dump(exclude_none=True)})
        apply_behavior(merged)
        return merged

    @router.get("/tools/catalog")
    async def catalog(project_id: str, folder: str) -> dict[str, Any]:
        listed = await tools.list_tools(project_id, folder)
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": (t.description or "").split(". ")[0],
                    "asks_first": bool(getattr(t.annotations, "destructive_hint", False)),
                }
                for t in listed
            ]
        }

    @router.post("/tool-servers/{project_id}/stop")
    async def stop_server(project_id: str) -> dict[str, Any]:
        return {"stopped": await tools.stop_project(project_id)}

    @router.get("/status")
    async def service_status() -> dict[str, Any]:
        return status()

    return router
