"""Projects (a workspace folder each) and their chats."""

import os
import uuid
from datetime import UTC, datetime

from thursday_gateway.domain.model import Chat, InvalidInput, Project, RecordState, clean_name
from thursday_gateway.infrastructure.store import Store


class NotFound(Exception):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def checked_folder(folder: str) -> str:
    if not os.path.isabs(folder) or not os.path.isdir(folder):
        raise InvalidInput("folder must be an existing absolute path on this PC")
    return os.path.normpath(folder)


class ProjectService:
    def __init__(self, store: Store) -> None:
        self._store = store

    def create_project(self, name: str, folder: str) -> Project:
        project = Project(new_id("prj"), clean_name(name, "project name"), checked_folder(folder), datetime.now(UTC))
        self._store.add_project(project)
        return project

    def get_project(self, project_id: str) -> Project:
        project = self._store.project(project_id)
        if project is None or project.state is not RecordState.ACTIVE:
            raise NotFound(project_id)
        return project

    def update_project(self, project_id: str, name: str | None, folder: str | None) -> Project:
        project = self.get_project(project_id)
        if name is not None:
            project.name = clean_name(name, "project name")
        if folder is not None:
            project.folder = checked_folder(folder)
        self._store.save_project(project)
        return project

    def create_chat(self, project_id: str, title: str | None) -> Chat:
        self.get_project(project_id)
        chat = Chat(new_id("chat"), project_id, clean_name(title or "New chat", "chat title"), datetime.now(UTC))
        self._store.add_chat(chat)
        return chat

    def get_chat(self, chat_id: str) -> Chat:
        chat = self._store.chat(chat_id)
        if chat is None or chat.state is not RecordState.ACTIVE:
            raise NotFound(chat_id)
        return chat

    def rename_chat(self, chat_id: str, title: str) -> Chat:
        chat = self.get_chat(chat_id)
        chat.title = clean_name(title, "chat title")
        self._store.save_chat(chat)
        return chat

    def mark_chat_deleting(self, chat_id: str) -> None:
        chat = self._store.chat(chat_id)
        if chat is None:
            return
        chat.state = RecordState.DELETING
        self._store.save_chat(chat)

    def mark_project_deleting(self, project_id: str) -> None:
        project = self._store.project(project_id)
        if project is None:
            return
        for row in self._store.chats(project_id):
            self.mark_chat_deleting(row["chat_id"])
        project.state = RecordState.DELETING
        self._store.save_project(project)
