"""Management API (service token), used by the gateway only. Keys and tokens are never returned.

Replay, allow-always rules, chat deletion, prompts, LLM settings and model lifecycle, behavior
settings, tool servers and the tool catalog.
"""

from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from thursday_contracts.retention import RETENTION_PATH, RetentionSetting
from thursday_llm import management
from thursday_llm.overrides import KeyChange, LlmOverrides, LoadOverrides
from thursday_llm.providers import ProviderError
from thursday_llm.runtime import LlmRuntime, ModelBusy
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.secret_store import SecretStoreError

from thursday_main_agent.application.behavior import Behavior, BehaviorSettings
from thursday_main_agent.application.deletion import Deletion
from thursday_main_agent.application.ports import ManagementRecords, Outbox
from thursday_main_agent.application.retention import WorkingData
from thursday_main_agent.application.status import ServiceStatus


class PromptBody(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


class BehaviorPatch(BaseModel):
    compaction_threshold_percent: float | None = Field(default=None, ge=10, le=99)
    keep_awake_paused_minutes: float | None = Field(default=None, ge=0, le=24 * 60)


class Tools(Protocol):
    async def list_tools(self, project_id: str, folder: str) -> list[Any]: ...

    async def stop_project(self, project_id: str) -> bool: ...

    def status(self) -> dict[str, dict[str, object]]: ...


def build_management_router(
    store: ManagementRecords,
    outbox: Outbox,
    llm: LlmRuntime,
    auth: ServiceTokenAuth,
    deletion: Deletion,
    status: ServiceStatus,
    behavior: BehaviorSettings,
    retention: WorkingData,
    default_prompt: str,
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
        return {"chat_id": chat_id, "deleted_tasks": await deletion.chat(chat_id)}

    @router.delete("/projects/{project_id}")
    async def remove_project(project_id: str) -> dict[str, Any]:
        """Delete saga participant: idempotent, safe to repeat. The project folder itself is never touched."""
        return {"project_id": project_id, **(await deletion.project(project_id))}

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
        return await management.settings(llm)

    @router.put("/llm")
    async def update_llm(body: LlmOverrides) -> dict[str, Any]:
        try:
            await llm.update(body)
        except ModelBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        return llm.describe()

    @router.put("/llm/key")
    async def set_key(body: KeyChange) -> dict[str, Any]:
        try:
            await llm.set_key(body.key.get_secret_value().strip())
        except ModelBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except SecretStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        return llm.describe()

    @router.get("/model")
    async def model() -> dict[str, Any]:
        return llm.describe()

    @router.get("/models")
    async def available_models() -> dict[str, Any]:
        return await management.available_models(llm)

    @router.post("/model/{action}")
    async def model_action(action: str, body: LoadOverrides | None = None) -> dict[str, Any]:
        try:
            return await management.model_action(llm, action, body)
        except management.UnknownAction as exc:
            raise HTTPException(404, "unknown action") from exc
        except ModelBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("/behavior")
    async def get_behavior() -> Behavior:
        return behavior.current()

    @router.put("/behavior")
    async def put_behavior(body: BehaviorPatch) -> Behavior:
        merged = Behavior.model_validate({**behavior.current().model_dump(), **body.model_dump(exclude_none=True)})
        behavior.apply(merged)
        return merged

    @router.get(RETENTION_PATH)
    async def get_retention() -> RetentionSetting:
        return RetentionSetting(days=retention.days)

    @router.put(RETENTION_PATH)
    async def put_retention(body: RetentionSetting) -> RetentionSetting:
        """The gateway sends the period chosen in Settings. Repeating it changes nothing."""
        return RetentionSetting(days=retention.apply(body.days))

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
        return status.status()

    return router
