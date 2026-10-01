/* Typed calls to the gateway API. One function per operation; no state here. */

import { del, get, patch, post, put, query } from './http';
import type {
  Agent,
  Approval,
  BackupSettings,
  Device,
  Chat,
  ChatMessage,
  GeneralSettings,
  LlmCall,
  LlmSettings,
  LoadParams,
  MetricsSample,
  Notification,
  PairingCode,
  PendingMessage,
  Project,
  PromptVersion,
  Status,
  TaskRow,
  TimelineMessage,
  ToolsOverview,
} from './types';

export const api = {
  projects: () => get<{ projects: Project[] }>('/v1/projects'),
  createProject: (name: string, folder: string) => post<Project>('/v1/projects', { name, folder }),
  updateProject: (id: string, changes: { name?: string; folder?: string }) => patch<Project>(`/v1/projects/${id}`, changes),
  deleteProject: (id: string) => del<{ status: string }>(`/v1/projects/${id}`),

  chats: (projectId: string) => get<{ chats: Chat[] }>(`/v1/projects/${projectId}/chats`),
  createChat: (projectId: string, title?: string) => post<Chat>(`/v1/projects/${projectId}/chats`, { title }),
  renameChat: (chatId: string, title: string) => patch<Chat>(`/v1/chats/${chatId}`, { title }),
  deleteChat: (chatId: string) => del<{ status: string }>(`/v1/chats/${chatId}`),

  messages: (chatId: string) => get<{ messages: ChatMessage[]; pending: PendingMessage[] }>(`/v1/chats/${chatId}/messages`),
  messagesBefore: (chatId: string, before: number) =>
    get<{ messages: ChatMessage[] }>(`/v1/chats/${chatId}/messages${query({ before })}`),
  send: (chatId: string, clientMessageId: string, text: string) =>
    post<{ status: string; new: boolean }>(`/v1/chats/${chatId}/messages`, { client_message_id: clientMessageId, text }),
  timeline: (chatId: string, after = 0) => get<{ events: TimelineMessage[] }>(`/v1/chats/${chatId}/timeline${query({ after, limit: 1000 })}`),
  chatTasks: (chatId: string) => get<{ tasks: TaskRow[] }>(`/v1/chats/${chatId}/tasks`),

  tasks: (state: 'all' | 'running' | 'failed', q?: string) => get<{ tasks: TaskRow[] }>(`/v1/tasks${query({ state, q })}`),
  task: (taskId: string) => get<{ task: TaskRow; trace: TimelineMessage[] }>(`/v1/tasks/${taskId}`),
  control: (taskId: string, action: 'pause' | 'resume' | 'stop') => post<unknown>(`/v1/tasks/${taskId}/${action}`),

  approvals: (chatId?: string) => get<{ approvals: Approval[] }>(`/v1/approvals${query({ chat_id: chatId })}`),
  answer: (approvalId: string, decision: 'allow_once' | 'allow_always' | 'deny') =>
    post<unknown>(`/v1/approvals/${approvalId}`, { decision }),

  notifications: () => get<{ notifications: Notification[] }>('/v1/notifications?unread=true'),
  markRead: (id: number) => post<void>(`/v1/notifications/${id}/read`),
  status: () => get<Status>('/v1/status'),
  search: (q: string) => get<{ results: { chat_id: string; chat_title: string; role: string; text: string }[] }>(`/v1/search${query({ q })}`),

  tools: () => get<ToolsOverview>('/v1/tools'),
  revokeRule: (chatId: string, tool: string) => del<void>(`/v1/chats/${chatId}/allow-rules/${encodeURIComponent(tool)}`),
  stopToolServer: (projectId: string) => post<unknown>(`/v1/tools/servers/${projectId}/stop`),

  monitor: (range: '15m' | '1h' | '24h' | '7d') => get<{ latest: MetricsSample | null; history: MetricsSample[]; llm_calls: LlmCall[] }>(`/v1/monitor${query({ range })}`),

  llm: (agent: Agent) => get<LlmSettings>(`/v1/agents/${agent}/llm`),
  updateLlm: (agent: Agent, changes: Partial<Omit<LlmSettings, 'load'>> & { load?: Partial<LoadParams> }) =>
    put<LlmSettings>(`/v1/agents/${agent}/llm`, changes),
  reloadKeys: (agent: Agent) => post<LlmSettings>(`/v1/agents/${agent}/llm/reload-keys`),
  model: (agent: Agent, action: 'load' | 'reload' | 'unload', load?: Partial<LoadParams>) =>
    post<LlmSettings>(`/v1/agents/${agent}/model/${action}`, load, 900_000),

  prompt: (agent: Agent) => get<{ version: number; text: string }>(`/v1/agents/${agent}/prompt`),
  savePrompt: (agent: Agent, text: string) => put<{ version: number }>(`/v1/agents/${agent}/prompt`, { text }),
  promptVersions: (agent: Agent) => get<{ versions: PromptVersion[]; default: string }>(`/v1/agents/${agent}/prompt/versions`),

  general: () => get<GeneralSettings>('/v1/settings/general'),
  saveGeneral: (changes: Partial<GeneralSettings>) => put<GeneralSettings>('/v1/settings/general', changes),
  backupSettings: () => get<BackupSettings>('/v1/settings/backup'),
  saveBackupSettings: (s: Omit<BackupSettings, 'last_run'>) => put<BackupSettings>('/v1/settings/backup', s),
  devices: () => get<{ devices: Device[] }>('/v1/devices'),
  pairingCode: () => post<PairingCode>('/v1/devices/pairing'),
  revokeDevice: (deviceId: string) => del<void>(`/v1/devices/${deviceId}`),

  backupNow: () => post<NonNullable<BackupSettings['last_run']>>('/v1/backup', undefined, 300_000),
};
