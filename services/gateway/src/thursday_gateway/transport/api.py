"""Client REST API (`/v1`): projects, chats, messages, tasks, approvals, notifications, search, monitor, backup.

The same router serves the trusted localhost listener and the proxy listener; only the auth
dependency differs. Errors are turned into problem documents by `errors`.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from thursday_contracts.approvals import ApprovalDecision

from thursday_gateway.application.backup import BackupSettings
from thursday_gateway.application.files import ProjectFiles, list_folders
from thursday_gateway.application.hub import row_message
from thursday_gateway.application.projects import NotFound
from thursday_gateway.transport.services import Services

MONITOR_SPANS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class ProjectIn(BaseModel):
    name: str
    folder: str


class ProjectPatch(BaseModel):
    name: str | None = None
    folder: str | None = None


class ChatIn(BaseModel):
    title: str | None = None


class ChatPatch(BaseModel):
    title: str | None = None
    direct: bool | None = None


class MessageIn(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=20_000)


class AnswerIn(BaseModel):
    decision: ApprovalDecision


def project_json(p: Any) -> dict[str, Any]:
    return {"project_id": p.project_id, "name": p.name, "folder": p.folder, "created_at": p.created_at.isoformat()}


def build_client_router(s: Services, auth: Callable[..., Awaitable[None]]) -> APIRouter:
    r = APIRouter(prefix="/v1", dependencies=[Depends(auth)])

    def changed() -> None:
        """Tell every connected client that the list of projects or chats changed, so it reloads it."""
        s.hub.publish({"kind": "catalog_changed"})

    @r.get("/projects")
    async def list_projects() -> dict[str, Any]:
        return {"projects": [project_json(p) for p in s.read.projects()]}

    @r.post("/projects", status_code=201)
    async def create_project(body: ProjectIn) -> dict[str, Any]:
        created = project_json(s.projects.create_project(body.name, body.folder))
        changed()
        return created

    @r.get("/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        return project_json(s.projects.get_project(project_id))

    @r.patch("/projects/{project_id}")
    async def patch_project(project_id: str, body: ProjectPatch) -> dict[str, Any]:
        updated = project_json(s.projects.update_project(project_id, body.name, body.folder))
        changed()
        return updated

    @r.delete("/projects/{project_id}", status_code=202)
    async def delete_project(project_id: str) -> dict[str, Any]:
        s.projects.get_project(project_id)
        s.projects.mark_project_deleting(project_id)
        s.deletion.wakeup.set()
        changed()
        return {"status": "deleting"}

    @r.get("/fs/folders")
    async def folders(path: str = Query("", max_length=1000)) -> dict[str, Any]:
        """Sub-folders of a folder on this PC, for choosing a project folder. Names only, read-only."""
        return await asyncio.to_thread(list_folders, path)

    @r.get("/projects/{project_id}/files")
    async def files(
        project_id: str, path: str = Query("", max_length=1000), q: str | None = Query(None, max_length=200)
    ) -> dict[str, Any]:
        """List a folder inside the project, or search file names in the whole project. Read-only."""
        view = ProjectFiles(s.projects.get_project(project_id).folder)
        entries = await asyncio.to_thread(view.search, q) if q else await asyncio.to_thread(view.entries, path)
        return {"path": path, "entries": [e.as_json() for e in entries]}

    @r.get("/projects/{project_id}/file")
    async def file(project_id: str, path: str = Query(min_length=1, max_length=1000)) -> dict[str, Any]:
        """Text preview of one file inside the project (first 200 kB). Read-only."""
        return await asyncio.to_thread(ProjectFiles(s.projects.get_project(project_id).folder).preview, path)

    @r.get("/projects/{project_id}/chats")
    async def list_chats(project_id: str) -> dict[str, Any]:
        s.projects.get_project(project_id)
        return {
            "chats": [
                {
                    "chat_id": c["chat_id"],
                    "title": c["title"],
                    "created_at": c["created_at"],
                    "last_activity": c["last_activity"],
                    "direct": bool(c["direct"]),
                }
                for c in s.read.chats(project_id)
            ]
        }

    @r.post("/projects/{project_id}/chats", status_code=201)
    async def create_chat(project_id: str, body: ChatIn) -> dict[str, Any]:
        chat = s.projects.create_chat(project_id, body.title)
        changed()
        return {"chat_id": chat.chat_id, "project_id": chat.project_id, "title": chat.title, "direct": chat.direct}

    @r.patch("/chats/{chat_id}")
    async def patch_chat(chat_id: str, body: ChatPatch) -> dict[str, Any]:
        chat = s.projects.get_chat(chat_id)
        if body.title is not None:
            chat = s.projects.rename_chat(chat_id, body.title)
        if body.direct is not None:
            chat = s.projects.set_chat_direct(chat_id, body.direct)
        changed()
        return {"chat_id": chat.chat_id, "title": chat.title, "direct": chat.direct}

    @r.delete("/chats/{chat_id}", status_code=202)
    async def delete_chat(chat_id: str) -> dict[str, Any]:
        s.projects.get_chat(chat_id)
        s.projects.mark_chat_deleting(chat_id)
        s.deletion.wakeup.set()
        changed()
        return {"status": "deleting"}

    @r.get("/chats/{chat_id}/messages")
    async def messages(chat_id: str, before: int | None = None, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        s.projects.get_chat(chat_id)
        pending = [
            {
                "client_message_id": o.client_message_id,
                "text": o.text,
                "status": o.status.value,
                "error": o.error,
                "direct": o.direct,
            }
            for o in s.read.pending_outgoing(chat_id)
        ]
        return {
            "messages": [
                {
                    "id": m["id"],
                    "pos": m["pos"],
                    "role": m["role"],
                    "text": m["text"],
                    "created_at": m["created_at"],
                    "client_message_id": m["client_message_id"],
                    "direct": bool(m["direct"]),
                }
                for m in s.read.messages(chat_id, before, limit)
            ],
            "pending": pending,
        }

    @r.post("/chats/{chat_id}/messages", status_code=202)
    async def send(chat_id: str, body: MessageIn) -> dict[str, Any]:
        chat = s.projects.get_chat(chat_id)
        status, new = s.relay.accept(chat_id, body.client_message_id, body.text, chat.direct)
        return {"status": status.value, "new": new, "direct": chat.direct}

    @r.get("/chats/{chat_id}/timeline")
    async def timeline(chat_id: str, after: int = 0, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
        s.projects.get_chat(chat_id)
        return {"events": [row_message(e) for e in s.read.events_after(after, limit, chat_id)]}

    @r.get("/chats/{chat_id}/tasks")
    async def tasks(chat_id: str) -> dict[str, Any]:
        return {"tasks": s.read.chat_tasks(chat_id)}

    @r.get("/tasks/{task_id}")
    async def task(task_id: str) -> dict[str, Any]:
        found = s.read.task(task_id)
        if found is None:
            raise NotFound(task_id)
        events, omitted = s.read.task_events(task_id)
        return {"task": found, "trace": [row_message(e) for e in events], "omitted": omitted}

    @r.post("/tasks/{task_id}/{action}")
    async def control(task_id: str, action: str) -> dict[str, Any]:
        handlers = {"pause": s.control.pause, "resume": s.control.resume, "stop": s.control.stop}
        if action not in handlers:
            raise NotFound(action)
        return await handlers[action](task_id)

    @r.get("/approvals")
    async def approvals(chat_id: str | None = None) -> dict[str, Any]:
        return {"approvals": s.read.pending_approvals(chat_id)}

    @r.post("/approvals/{approval_id}")
    async def answer(approval_id: str, body: AnswerIn) -> dict[str, Any]:
        await s.control.answer(approval_id, body.decision)
        return {"approval_id": approval_id, "decision": body.decision.value}

    @r.get("/chats/{chat_id}/allow-rules")
    async def allow_rules(chat_id: str) -> Any:
        return (await s.main.management("GET", f"/chats/{chat_id}/allow-rules")).json()

    @r.delete("/chats/{chat_id}/allow-rules/{tool}", status_code=204)
    async def revoke(chat_id: str, tool: str) -> None:
        await s.main.management("DELETE", f"/chats/{chat_id}/allow-rules/{tool}")

    @r.get("/notifications")
    async def notifications(unread: bool = False, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        return {"notifications": s.read.notifications(unread, limit)}

    @r.post("/notifications/{notification_id}/read", status_code=204)
    async def mark_read(notification_id: int) -> None:
        s.read.mark_notification_read(notification_id)

    @r.get("/search")
    async def search(
        q: str = Query(min_length=2, max_length=200), limit: int = Query(50, ge=1, le=200)
    ) -> dict[str, Any]:
        return {
            "results": [
                {
                    "chat_id": m["chat_id"],
                    "chat_title": m["title"],
                    "project_id": m["project_id"],
                    "role": m["role"],
                    "text": m["text"],
                    "created_at": m["created_at"],
                }
                for m in s.read.search_messages(q, limit)
            ]
        }

    @r.get("/monitor")
    async def monitor(range_: str = Query("1h", alias="range", pattern="^(15m|1h|24h|7d)$")) -> dict[str, Any]:
        span = MONITOR_SPANS[range_]
        # Model speed and context use come from the stored model calls, so they survive restarts and
        # show when each call really happened instead of repeating the last value.
        calls = s.read.llm_calls(span)
        if s.metrics is None:
            return {"latest": None, "history": [], "llm_calls": calls}
        return {"latest": s.metrics.latest(), "history": s.metrics.history(span), "llm_calls": calls}

    @r.get("/settings/backup")
    async def backup_settings() -> dict[str, Any]:
        if s.backup is None:
            raise NotFound("backup")
        return {**s.backup.settings().model_dump(), "last_run": s.backup.last_run()}

    @r.put("/settings/backup")
    async def save_backup_settings(body: BackupSettings) -> dict[str, Any]:
        if s.backup is None:
            raise NotFound("backup")
        return s.backup.save_settings(body).model_dump()

    @r.post("/backup")
    async def backup_now() -> dict[str, Any]:
        if s.backup is None:
            raise NotFound("backup")
        return await s.backup.run()

    @r.get("/status")
    async def status() -> dict[str, Any]:
        # stream_pos lets a client join the live stream now instead of replaying all history.
        return {**(s.status.current or await s.status.check()), "stream_pos": s.read.stream_position()}

    return r
