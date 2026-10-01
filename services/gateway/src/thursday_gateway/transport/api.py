"""Client REST API (`/v1`), event ingest, and the WebSocket stream.

Errors are `application/problem+json` with stable codes. The same router serves the
trusted localhost listener and the proxy listener; only the auth dependency differs.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from thursday_contracts.approvals import ApprovalDecision
from thursday_contracts.events import EventBatch, IngestResult
from thursday_contracts.metrics import MetricsSample
from thursday_contracts.problems import PROBLEM_MEDIA_TYPE, Problem, ProblemCode

from thursday_gateway.application.backup import BackupService, BackupSettings
from thursday_gateway.application.control import TaskControl
from thursday_gateway.application.deletion import DeletionSaga
from thursday_gateway.application.devices import DeviceService, RateLimited
from thursday_gateway.application.files import ProjectFiles, list_folders
from thursday_gateway.application.hub import Hub, event_message, row_message
from thursday_gateway.application.projects import NotFound, ProjectService
from thursday_gateway.application.relay import MessageRelay
from thursday_gateway.application.status import DependencyStatus
from thursday_gateway.domain.model import InvalidInput, valid_id
from thursday_gateway.infrastructure.agents import AgentRefused, AgentUnavailable, MainAgentClient, VoiceAgentClient
from thursday_gateway.infrastructure.metrics_store import MetricsStore
from thursday_gateway.infrastructure.store import Store

BACKLOG_BATCH = 500
AGENT_CODES = {
    -32041: (409, ProblemCode.APPROVAL_ALREADY_RESOLVED),
    -32040: (409, ProblemCode.TASK_NOT_PAUSABLE),
    -32002: (409, ProblemCode.CONFLICT),
    -32001: (404, ProblemCode.NOT_FOUND),
    -32004: (409, ProblemCode.CONFLICT),
}


@dataclass
class Services:
    store: Store
    projects: ProjectService
    relay: MessageRelay
    control: TaskControl
    deletion: DeletionSaga
    status: DependencyStatus
    main: MainAgentClient
    hub: Hub
    metrics: MetricsStore | None = None
    metrics_hub: Hub = field(default_factory=Hub)
    backup: BackupService | None = None
    voice: VoiceAgentClient | None = None
    devices: DeviceService = field(init=False)

    def __post_init__(self) -> None:
        # One instance shared by both listeners: pairing codes and revocation signals live here.
        self.devices = DeviceService(self.store)


def problem(status: int, code: ProblemCode, title: str, detail: str = "") -> JSONResponse:
    body = Problem(title=title, status=status, code=code, detail=detail).model_dump(mode="json")
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return problem(404, ProblemCode.NOT_FOUND, "Not found", str(exc))

    @app.exception_handler(InvalidInput)
    async def invalid(_: Request, exc: InvalidInput) -> JSONResponse:
        return problem(422, ProblemCode.INVALID_INPUT, "Invalid input", str(exc))

    @app.exception_handler(RateLimited)
    async def limited(_: Request, exc: RateLimited) -> JSONResponse:
        response = problem(429, ProblemCode.RATE_LIMITED, "Too many attempts", str(exc))
        response.headers["Retry-After"] = "60"
        return response

    @app.exception_handler(AgentUnavailable)
    async def down(_: Request, exc: AgentUnavailable) -> JSONResponse:
        return problem(503, ProblemCode.DEPENDENCY_DOWN, "A service is unavailable", str(exc))

    @app.exception_handler(AgentRefused)
    async def refused(_: Request, exc: AgentRefused) -> JSONResponse:
        if 400 <= exc.code <= 599:  # an agent's own HTTP answer, passed through
            http_codes = {404: ProblemCode.NOT_FOUND, 422: ProblemCode.INVALID_INPUT, 503: ProblemCode.DEPENDENCY_DOWN}
            return problem(
                exc.code, http_codes.get(exc.code, ProblemCode.CONFLICT), "The agent refused the request", str(exc)
            )
        status, code = AGENT_CODES.get(exc.code, (502, ProblemCode.CONFLICT))
        return problem(status, code, "The agent refused the request", str(exc))


class ProjectIn(BaseModel):
    name: str
    folder: str


class ProjectPatch(BaseModel):
    name: str | None = None
    folder: str | None = None


class ChatIn(BaseModel):
    title: str | None = None


class ChatPatch(BaseModel):
    title: str


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
        return {"projects": [project_json(p) for p in s.store.projects()]}

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
                }
                for c in s.store.chats(project_id)
            ]
        }

    @r.post("/projects/{project_id}/chats", status_code=201)
    async def create_chat(project_id: str, body: ChatIn) -> dict[str, Any]:
        chat = s.projects.create_chat(project_id, body.title)
        changed()
        return {"chat_id": chat.chat_id, "project_id": chat.project_id, "title": chat.title}

    @r.patch("/chats/{chat_id}")
    async def rename_chat(chat_id: str, body: ChatPatch) -> dict[str, Any]:
        chat = s.projects.rename_chat(chat_id, body.title)
        changed()
        return {"chat_id": chat.chat_id, "title": chat.title}

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
        rows = s.store.query(
            "select * from messages where chat_id = ? and id < ? order by id desc limit ?",
            (chat_id, before or 2**62, limit),
        )
        pending = [
            {"client_message_id": o.client_message_id, "text": o.text, "status": o.status.value, "error": o.error}
            for o in s.store.pending_outgoing(chat_id)
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
                }
                for m in reversed(rows)
            ],
            "pending": pending,
        }

    @r.post("/chats/{chat_id}/messages", status_code=202)
    async def send(chat_id: str, body: MessageIn) -> dict[str, Any]:
        s.projects.get_chat(chat_id)
        status, new = s.relay.accept(chat_id, body.client_message_id, body.text)
        return {"status": status.value, "new": new}

    @r.get("/chats/{chat_id}/timeline")
    async def timeline(chat_id: str, after: int = 0, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
        s.projects.get_chat(chat_id)
        return {"events": [row_message(e) for e in s.store.events_after(after, limit, chat_id)]}

    @r.get("/chats/{chat_id}/tasks")
    async def tasks(chat_id: str) -> dict[str, Any]:
        rows = s.store.query("select * from tasks where chat_id = ? order by created_at desc limit 100", (chat_id,))
        return {"tasks": [dict(t) for t in rows]}

    @r.get("/tasks/{task_id}")
    async def task(task_id: str) -> dict[str, Any]:
        rows = s.store.query("select * from tasks where task_id = ?", (task_id,))
        if not rows:
            raise NotFound(task_id)
        return {"task": dict(rows[0]), "trace": [row_message(e) for e in s.store.task_events(task_id)]}

    @r.post("/tasks/{task_id}/{action}")
    async def control(task_id: str, action: str) -> dict[str, Any]:
        handlers = {"pause": s.control.pause, "resume": s.control.resume, "stop": s.control.stop}
        if action not in handlers:
            raise NotFound(action)
        return await handlers[action](task_id)

    @r.get("/approvals")
    async def approvals(chat_id: str | None = None) -> dict[str, Any]:
        # Only fixed fragments are concatenated; values are bound parameters.
        sql = "select * from approvals where status = 'pending'" + (" and chat_id = ?" if chat_id else "")  # noqa: S608
        rows = s.store.query(sql + " order by requested_at", (chat_id,) if chat_id else ())
        return {"approvals": [{**dict(a), "arguments": json.loads(a["arguments"])} for a in rows]}

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
        rows = s.store.query(
            "select * from notifications" + (" where read = 0" if unread else "") + " order by id desc limit ?",  # noqa: S608
            (limit,),
        )
        return {"notifications": [dict(n) for n in rows]}

    @r.post("/notifications/{notification_id}/read", status_code=204)
    async def mark_read(notification_id: int) -> None:
        with s.store.tx() as db:
            db.execute("update notifications set read = 1 where id = ?", (notification_id,))

    @r.get("/search")
    async def search(
        q: str = Query(min_length=2, max_length=200), limit: int = Query(50, ge=1, le=200)
    ) -> dict[str, Any]:
        like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
        rows = s.store.query(
            "select m.*, c.title, c.project_id from messages m join chats c using (chat_id) "
            "where c.state = 'active' and m.text like ? escape '\\' order by m.id desc limit ?",
            (like, limit),
        )
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
                for m in rows
            ]
        }

    @r.get("/monitor")
    async def monitor(range_: str = Query("1h", alias="range", pattern="^(15m|1h|24h|7d)$")) -> dict[str, Any]:
        spans = {
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
        }
        # Model speed and context use come from the stored model calls, so they survive restarts and
        # show when each call really happened instead of repeating the last value.
        calls = s.store.llm_calls(spans[range_])
        if s.metrics is None:
            return {"latest": None, "history": [], "llm_calls": calls}
        return {"latest": s.metrics.latest(), "history": s.metrics.history(spans[range_]), "llm_calls": calls}

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
        return {**(s.status.current or await s.status.check()), "stream_pos": s.store.last_pos()}

    return r


def build_ingest_router(s: Services, service_auth: Callable[..., Awaitable[None]]) -> APIRouter:
    r = APIRouter(prefix="/v1", dependencies=[Depends(service_auth)])

    @r.post("/events")
    async def ingest(request: Request) -> IngestResult:
        try:
            batch = EventBatch.model_validate_json(await request.body())
        except ValidationError as exc:
            raise InvalidInput(f"invalid event batch: {exc.error_count()} errors") from exc
        accepted, duplicates = s.store.ingest(batch.events)
        for pos, event in accepted:
            s.hub.publish(event_message(pos, event))
        return IngestResult(accepted=len(accepted), duplicates=duplicates, last_seq=s.store.last_seq())  # pyright: ignore[reportArgumentType]

    @r.post("/metrics", status_code=204)
    async def ingest_metrics(request: Request) -> None:
        try:
            sample = MetricsSample.model_validate_json(await request.body())
        except ValidationError as exc:
            raise InvalidInput("invalid metrics sample") from exc
        if s.metrics is not None:
            s.metrics.add(sample)
        s.metrics_hub.publish({"kind": "metrics", "sample": sample.model_dump(mode="json")})

    return r


async def metrics_stream(websocket: WebSocket, s: Services) -> None:
    """Live metrics, only while a Monitor screen keeps this socket open."""
    await websocket.accept()
    subscriber = s.metrics_hub.subscribe()
    try:
        latest = s.metrics.latest() if s.metrics else None
        if latest:
            await websocket.send_json({"kind": "metrics", "sample": latest})
        while not subscriber.overflowed:
            await websocket.send_json(await subscriber.queue.get())
        await websocket.close(code=1013)
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        s.metrics_hub.unsubscribe(subscriber)


async def stream(websocket: WebSocket, s: Services, after: int, chat_id: str | None) -> None:
    """Replay everything after the client's cursor, then stay live. Server to client only."""
    if chat_id is not None and not valid_id(chat_id):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    subscriber = s.hub.subscribe()  # subscribe first, so nothing falls between backlog and live
    last = after
    try:
        while True:
            rows = s.store.events_after(last, BACKLOG_BATCH, chat_id)
            for row in rows:
                await websocket.send_json(row_message(row))
                last = row["pos"]
            if len(rows) < BACKLOG_BATCH:
                break
        if s.status.current.get("banners"):
            await websocket.send_json({"kind": "status_banner", "banners": s.status.current["banners"]})
        while not subscriber.overflowed:
            message = await subscriber.queue.get()
            pos = message.get("pos")
            if pos is not None and pos <= last:
                continue
            if chat_id is not None and message.get("chat_id", (message.get("event") or {}).get("chat_id")) != chat_id:
                continue
            await websocket.send_json(message)
            if pos is not None:
                last = pos
        await websocket.close(code=1013)  # too far behind: reconnect with the cursor
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        s.hub.unsubscribe(subscriber)
