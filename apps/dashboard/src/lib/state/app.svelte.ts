/* App-wide state: projects and chats, pending approvals, running tasks, service status, the live
   stream, and toasts. Screens read from here; per-chat detail lives in ChatSession. */

import { api } from '../api/gateway';
import { ApiError } from '../api/http';
import type { Approval, Banner, Chat, Project, Status, StreamMessage, TaskRow } from '../api/types';
import { Poller } from '../live/poll';
import { StreamClient, type ConnectionState } from '../live/stream';
import { router } from './router.svelte';

export type Dot = 'warn' | 'run' | 'bad' | '';

export interface Toast {
  id: number;
  text: string;
  tone: 'info' | 'ok' | 'warn' | 'bad';
  action?: { label: string; run: () => void };
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong.';
}

class AppState {
  projects = $state<Project[]>([]);
  chats = $state<Record<string, Chat[]>>({});
  collapsed = $state<Record<string, boolean>>({});
  loaded = $state(false);
  loadError = $state<string | null>(null);
  approvals = $state<Approval[]>([]);
  running = $state<TaskRow[]>([]);
  status = $state<Status | null>(null);
  banners = $state<Banner[]>([]);
  connection = $state<ConnectionState>('offline');
  toasts = $state<Toast[]>([]);

  readonly stream = new StreamClient();
  private started = false;
  private toastId = 0;
  private refreshTimers = new Map<string, ReturnType<typeof setTimeout>>();

  private statusPoll = new Poller<Status>({
    fetch: () => api.status(),
    intervalMs: 15_000,
    onData: (status) => {
      this.status = status;
      this.banners = status.banners;
      if (!this.started) {
        this.started = true;
        this.stream.start(status.stream_pos);
        void this.loadAll();
      }
    },
    onError: (error) => {
      if (!this.loaded) this.loadError = errorText(error);
    },
  });

  private taskPoll = new Poller<[TaskRow[], Approval[]]>({
    fetch: () => Promise.all([api.tasks('running').then((r) => r.tasks), api.approvals().then((r) => r.approvals)]),
    intervalMs: 30_000,
    onData: ([running, approvals]) => {
      this.running = running;
      this.approvals = approvals;
    },
  });

  start(): void {
    this.stream.onState((state) => (this.connection = state));
    this.stream.subscribe((message) => this.onStream(message));
    document.addEventListener('visibilitychange', () => this.stream.visibility(document.hidden));
    this.statusPoll.start();
    this.taskPoll.start();
  }

  retryNow(): void {
    this.loadError = null;
    this.statusPoll.refresh();
  }

  async loadAll(): Promise<void> {
    try {
      const { projects } = await api.projects();
      const lists = await Promise.all(projects.map((p) => api.chats(p.project_id).then((r) => r.chats)));
      this.projects = projects;
      this.chats = Object.fromEntries(projects.map((p, i) => [p.project_id, lists[i]]));
      this.loaded = true;
      this.loadError = null;
    } catch (error) {
      this.loadError = errorText(error);
    }
  }

  async refreshChats(projectId: string): Promise<void> {
    try {
      const { chats } = await api.chats(projectId);
      this.chats[projectId] = chats;
    } catch {
      /* the next refresh fixes it */
    }
  }

  project(projectId: string): Project | undefined {
    return this.projects.find((p) => p.project_id === projectId);
  }

  chat(chatId: string): { chat: Chat; project: Project } | undefined {
    for (const project of this.projects) {
      const chat = this.chats[project.project_id]?.find((c) => c.chat_id === chatId);
      if (chat) return { chat, project };
    }
    return undefined;
  }

  latestChat(): Chat | undefined {
    return Object.values(this.chats)
      .flat()
      .sort((a, b) => b.last_activity.localeCompare(a.last_activity))[0];
  }

  dot(chatId: string): Dot {
    if (this.approvals.some((a) => a.chat_id === chatId)) return 'warn';
    const task = this.running.find((t) => t.chat_id === chatId);
    if (!task) return '';
    return task.state === 'input_required' ? 'warn' : 'run';
  }

  chatLine(chat: Chat): string {
    const dot = this.dot(chat.chat_id);
    if (dot === 'warn') return 'Waiting for your approval';
    if (dot === 'run') return 'Working';
    return relativeTime(chat.last_activity);
  }

  /* ---------- projects and chats ---------- */

  async createProject(name: string, folder: string): Promise<Project> {
    const project = await api.createProject(name, folder);
    this.projects = [...this.projects, project];
    this.chats[project.project_id] = [];
    return project;
  }

  async updateProject(projectId: string, changes: { name?: string; folder?: string }): Promise<void> {
    const updated = await api.updateProject(projectId, changes);
    this.projects = this.projects.map((p) => (p.project_id === projectId ? updated : p));
  }

  async deleteProject(projectId: string): Promise<void> {
    await api.deleteProject(projectId);
    const chatIds = new Set((this.chats[projectId] ?? []).map((c) => c.chat_id));
    this.projects = this.projects.filter((p) => p.project_id !== projectId);
    delete this.chats[projectId];
    const route = router.route;
    if ((route.name === 'project' && route.projectId === projectId) || (route.name === 'chat' && chatIds.has(route.chatId)))
      router.go({ name: 'home' }, true);
  }

  async createChat(projectId: string): Promise<void> {
    const created = await api.createChat(projectId);
    const now = new Date().toISOString();
    const chat: Chat = { chat_id: created.chat_id, title: created.title, created_at: now, last_activity: now };
    this.chats[projectId] = [chat, ...(this.chats[projectId] ?? [])];
    this.collapsed[projectId] = false;
    router.go({ name: 'chat', chatId: chat.chat_id });
  }

  async renameChat(chatId: string, title: string): Promise<void> {
    const renamed = await api.renameChat(chatId, title);
    for (const list of Object.values(this.chats)) {
      const chat = list.find((c) => c.chat_id === chatId);
      if (chat) chat.title = renamed.title;
    }
  }

  async deleteChat(chatId: string): Promise<void> {
    await api.deleteChat(chatId);
    for (const [projectId, list] of Object.entries(this.chats)) this.chats[projectId] = list.filter((c) => c.chat_id !== chatId);
    this.approvals = this.approvals.filter((a) => a.chat_id !== chatId);
    if (router.route.name === 'chat' && router.route.chatId === chatId) router.go({ name: 'home' }, true);
  }

  /* ---------- approvals and tasks ---------- */

  async answer(approval: Approval, decision: 'allow_once' | 'allow_always' | 'deny'): Promise<void> {
    try {
      await api.answer(approval.approval_id, decision);
      this.approvals = this.approvals.filter((a) => a.approval_id !== approval.approval_id);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        this.toast('This approval was already answered or has expired.', 'warn');
        this.taskPoll.refresh();
        return;
      }
      throw error;
    }
  }

  async control(taskId: string, action: 'pause' | 'resume' | 'stop'): Promise<void> {
    try {
      await api.control(taskId, action);
    } catch (error) {
      this.toast(errorText(error), 'bad');
    } finally {
      this.soon('tasks', () => this.taskPoll.refresh());
    }
  }

  /* ---------- live stream ---------- */

  private onStream(message: StreamMessage): void {
    switch (message.kind) {
      case 'catalog_changed': // a project or chat was added, renamed or deleted, here or on another device
        this.soon('projects', () => void this.loadAll());
        break;
      case 'status_banner':
        this.banners = message.banners;
        this.soon('status', () => this.statusPoll.refresh());
        break;
      case 'approval_requested': {
        this.soon('tasks', () => this.taskPoll.refresh());
        const chatId = message.event.chat_id;
        const here = router.route.name === 'chat' && router.route.chatId === chatId;
        if (chatId && !here)
          this.toast(`Approval needed · ${message.event.payload.summary ?? ''}`, 'warn', {
            label: 'Open',
            run: () => router.go({ name: 'chat', chatId }),
          });
        break;
      }
      case 'approval_resolved':
      case 'task_state':
        this.soon('tasks', () => this.taskPoll.refresh());
        break;
      case 'notification': {
        const p = message.event.payload;
        const chatId = message.event.chat_id;
        const here = router.route.name === 'chat' && router.route.chatId === chatId;
        if (!here) {
          const tone = p.kind === 'failed' ? 'bad' : p.kind === 'completed' ? 'ok' : 'info';
          this.toast([p.title, p.body].filter(Boolean).join(' · '), tone, chatId ? { label: 'Open', run: () => router.go({ name: 'chat', chatId }) } : undefined);
        }
        break;
      }
      case 'timeline_event':
        if (message.event.chat_id && ['user_message', 'assistant_message'].includes(message.event.type)) this.touch(message.event.chat_id, message.event.ts);
        break;
    }
  }

  private touch(chatId: string, ts: string): void {
    const found = this.chat(chatId);
    if (found) found.chat.last_activity = ts;
    else this.soon('projects', () => void this.loadAll()); // a chat made elsewhere (for example the phone)
  }

  /** Coalesce bursts of stream events into one refresh. */
  private soon(key: string, fn: () => void, ms = 300): void {
    if (this.refreshTimers.has(key)) return;
    this.refreshTimers.set(
      key,
      setTimeout(() => {
        this.refreshTimers.delete(key);
        fn();
      }, ms),
    );
  }

  /* ---------- toasts ---------- */

  toast(text: string, tone: Toast['tone'] = 'info', action?: Toast['action']): void {
    const toast = { id: ++this.toastId, text, tone, action };
    this.toasts = [...this.toasts.slice(-3), toast];
    setTimeout(() => this.dismiss(toast.id), action ? 12_000 : 5_000);
  }

  dismiss(id: number): void {
    this.toasts = this.toasts.filter((t) => t.id !== id);
  }
}

export function relativeTime(iso: string, now = Date.now()): string {
  const seconds = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (!Number.isFinite(seconds)) return '';
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 172_800) return 'Yesterday';
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export const app = new AppState();
