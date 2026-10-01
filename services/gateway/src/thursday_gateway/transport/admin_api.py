"""Settings, trace list, and tools endpoints for the dashboard and app (`/v1`).

Agent settings are owned by each agent; the gateway forwards them and never sees or writes
keys. General settings combine the main agent's behavior with the gateway's own retention.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from thursday_gateway.application.projects import NotFound
from thursday_gateway.infrastructure.agents import AgentRefused, AgentUnavailable
from thursday_gateway.transport.api import Services

AGENTS = ("main", "voice")
RUNNING_STATES = ("submitted", "working", "input_required")


class GeneralPatch(BaseModel):
    compaction_threshold_percent: float | None = Field(default=None, ge=10, le=99)
    keep_awake_paused_minutes: float | None = Field(default=None, ge=0, le=24 * 60)
    trace_retention_days: int | None = Field(default=None, ge=1, le=3650)
    metrics_retention_days: int | None = Field(default=None, ge=1, le=365)


def build_admin_router(
    s: Services, auth: Callable[..., Awaitable[None]], retention_defaults: dict[str, int]
) -> APIRouter:
    r = APIRouter(prefix="/v1", dependencies=[Depends(auth)])

    def caller(agent: str) -> Callable[..., Awaitable[httpx.Response]]:
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
            raise AgentRefused(response.status_code, str(detail))
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

    @r.post("/agents/{agent}/llm/reload-keys")
    async def reload_keys(agent: str) -> Any:
        return await forward(agent, "POST", "/llm/reload-keys")

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

    def retention() -> dict[str, int]:
        return {**retention_defaults, **(s.store.get_setting("retention") or {})}

    @r.get("/settings/general")
    async def general() -> dict[str, Any]:
        try:
            behavior = await forward("main", "GET", "/behavior")
        except (AgentUnavailable, AgentRefused):
            behavior = None
        return {**(behavior or {}), **retention(), "main_agent_reachable": behavior is not None}

    @r.put("/settings/general")
    async def put_general(body: GeneralPatch) -> dict[str, Any]:
        patch = body.model_dump(exclude_none=True)
        behavior_patch = {
            k: patch.pop(k) for k in ("compaction_threshold_percent", "keep_awake_paused_minutes") if k in patch
        }
        if behavior_patch:
            await forward("main", "PUT", "/behavior", behavior_patch)
        if patch:
            s.store.set_setting("retention", {**retention(), **patch})
        return await general()

    @r.get("/tasks")
    async def tasks(
        state: str = Query("all", pattern="^(all|running|failed)$"),
        q: str | None = Query(None, max_length=200),
        limit: int = Query(100, ge=1, le=500),
    ) -> dict[str, Any]:
        sql = (
            "select t.*, c.title as chat_title, p.name as project_name from tasks t "
            "left join chats c on c.chat_id = t.chat_id left join projects p on p.project_id = t.project_id where 1=1"
        )
        params: list[Any] = []
        if state == "running":
            sql += " and t.state in ('submitted','working','input_required')"
        elif state == "failed":
            sql += " and t.state = 'failed'"
        if q:
            sql += " and (t.instruction like ? escape '\\' or t.summary like ? escape '\\')"
            like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
            params += [like, like]
        rows = s.store.query(sql + " order by t.created_at desc limit ?", (*params, limit))
        return {"tasks": [dict(row) for row in rows]}

    catalog_cache: dict[str, Any] = {}

    @r.get("/tools")
    async def tools() -> dict[str, Any]:
        titles = {row["chat_id"]: row["title"] for row in s.store.query("select chat_id, title from chats")}
        projects = s.store.projects()
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
