"""Settings, trace list, and tools endpoints for the dashboard and app (`/v1`).

Agent settings are owned by each agent; the gateway forwards them. A new API key passes through to
the agent, which stores it; the gateway never stores, logs, or returns keys. General settings combine
the main agent's behavior with the gateway's own retention.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from thursday_gateway.application.errors import AgentRefused, AgentUnavailable
from thursday_gateway.application.ports import Reply
from thursday_gateway.application.projects import NotFound
from thursday_gateway.application.retention import DATA, OLD_DATA
from thursday_gateway.transport.services import Services


class GeneralPatch(BaseModel):
    compaction_threshold_percent: float | None = Field(default=None, ge=10, le=99)
    keep_awake_paused_minutes: float | None = Field(default=None, ge=0, le=24 * 60)
    data_retention_days: int | None = Field(default=None, ge=0, le=3650)  # 0: until deleted by hand
    trace_retention_days: int | None = Field(default=None, ge=1, le=3650)  # the older name of the same
    metrics_retention_days: int | None = Field(default=None, ge=1, le=365)


def refusal_words(detail: object) -> str:
    """Why an agent refused a request, as words for the person who sent it.

    An agent answers a body it cannot accept with a list, one entry for each field that is wrong. Shown as it
    comes, that is a page of brackets; here each entry becomes "field: what is wrong with it".
    """
    if not isinstance(detail, list):
        return str(detail)
    parts = []
    for entry in detail:
        if not isinstance(entry, dict):
            parts.append(str(entry))
            continue
        field = ".".join(str(step) for step in entry.get("loc", ()) if step != "body")
        wrong = str(entry.get("msg", "")).strip()
        parts.append(f"{field}: {wrong}" if field and wrong else field or wrong)
    return "; ".join(part for part in parts if part)[:500]


def build_admin_router(s: Services, auth: Callable[..., Awaitable[None]]) -> APIRouter:
    r = APIRouter(prefix="/v1", dependencies=[Depends(auth)])

    def caller(agent: str) -> Callable[..., Awaitable[Reply]]:
        if agent == "main":
            return s.main.management
        if agent == "voice" and s.voice is not None:
            return s.voice.request
        raise NotFound(agent)

    async def forward(agent: str, method: str, path: str, body: Any = None) -> Any:
        response = await caller(agent)(method, path, **({"json": body} if body is not None else {}))
        if response.status_code >= 400:
            detail = (
                response.json().get("detail", "")
                if response.headers.get("content-type", "").startswith("application/json")
                else response.text[:200]
            )
            raise AgentRefused(response.status_code, refusal_words(detail))
        return response.json() if response.content else None

    async def body_or_none(request: Request) -> Any:
        raw = await request.body()
        return None if not raw else await request.json()

    @r.get("/agents/{agent}/llm")
    async def get_llm(agent: str) -> Any:
        return await forward(agent, "GET", "/llm")

    @r.put("/agents/{agent}/llm")
    async def put_llm(agent: str, request: Request) -> Any:
        return await forward(agent, "PUT", "/llm", await request.json())

    @r.put("/agents/{agent}/llm/key")
    async def put_key(agent: str, request: Request) -> Any:
        """Passed straight to the agent, which stores it in the credential store. The gateway keeps no copy."""
        return await forward(agent, "PUT", "/llm/key", await request.json())

    @r.get("/agents/{agent}/models")
    async def list_models(agent: str) -> Any:
        return await forward(agent, "GET", "/models")

    @r.post("/agents/{agent}/model/{action}")
    async def model_action(agent: str, action: str, request: Request) -> Any:
        return await forward(agent, "POST", f"/model/{action}", await body_or_none(request))

    @r.get("/agents/{agent}/prompt")
    async def get_prompt(agent: str) -> Any:
        return await forward(agent, "GET", "/prompt")

    @r.put("/agents/{agent}/prompt")
    async def put_prompt(agent: str, request: Request) -> Any:
        return await forward(agent, "PUT", "/prompt", await request.json())

    @r.get("/agents/{agent}/prompt/versions")
    async def prompt_versions(agent: str) -> Any:
        return await forward(agent, "GET", "/prompt/versions")

    @r.get("/settings/general")
    async def general() -> dict[str, Any]:
        try:
            behavior = await forward("main", "GET", "/behavior")
        except (AgentUnavailable, AgentRefused):
            behavior = None
        periods = s.retention.current()
        # The older name is still answered, for a phone app that has not been updated yet.
        return {**(behavior or {}), **periods, OLD_DATA: periods[DATA], "main_agent_reachable": behavior is not None}

    @r.put("/settings/general")
    async def put_general(body: GeneralPatch) -> dict[str, Any]:
        patch = body.model_dump(exclude_none=True)
        behavior_patch = {
            k: patch.pop(k) for k in ("compaction_threshold_percent", "keep_awake_paused_minutes") if k in patch
        }
        if behavior_patch:
            await forward("main", "PUT", "/behavior", behavior_patch)
        if OLD_DATA in patch:
            patch.setdefault(DATA, patch.pop(OLD_DATA))
        if patch:
            s.retention.change(patch)
            await s.retention.sync()  # the agents hear it now; one that is down hears it when it is back
        return await general()

    @r.get("/tasks")
    async def tasks(
        state: str = Query("all", pattern="^(all|running|failed)$"),
        q: str | None = Query(None, max_length=200),
        limit: int = Query(100, ge=1, le=500),
    ) -> dict[str, Any]:
        return {"tasks": s.read.find_tasks(state, q, limit)}

    catalog_cache: dict[str, Any] = {}

    @r.get("/tools")
    async def tools() -> dict[str, Any]:
        titles = s.read.chat_titles()
        projects = s.read.projects()
        try:
            rules = (await forward("main", "GET", "/allow-rules"))["rules"]
            status = (await forward("main", "GET", "/status"))["tool_servers"]
            reachable = True
        except (AgentUnavailable, AgentRefused):
            rules, status, reachable = [], {}, False
        if reachable and not catalog_cache and projects:
            try:
                first = projects[0]
                query = urlencode({"project_id": first.project_id, "folder": first.folder})
                catalog_cache["tools"] = (await forward("main", "GET", f"/tools/catalog?{query}"))["tools"]
            except (AgentUnavailable, AgentRefused):
                pass
        servers = [
            {"project_id": p.project_id, "project_name": p.name, **status.get(p.project_id, {"alive": False})}
            for p in projects
        ]
        return {
            "main_agent_reachable": reachable,
            "rules": [{**rule, "chat_title": titles.get(rule["chat_id"], "Deleted chat")} for rule in rules],
            "servers": servers,
            "catalog": catalog_cache.get("tools", []),
        }

    @r.post("/tools/servers/{project_id}/stop")
    async def stop_server(project_id: str) -> Any:
        return await forward("main", "POST", f"/tool-servers/{project_id}/stop")

    return r
