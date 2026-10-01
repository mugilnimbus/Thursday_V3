/* Arrange the task list for Trace: grouped by chat, by project, or flat, newest or oldest first.
   Pure, so it is unit tested. */

import type { TaskRow } from '../../lib/api/types';

export type GroupBy = 'chat' | 'project' | 'none';
export type Order = 'newest' | 'oldest';

export interface TaskGroup {
  key: string;
  /** Heading shown above the group; empty for the flat list. */
  label: string;
  tasks: TaskRow[];
}

const byTime = (order: Order) => (a: TaskRow, b: TaskRow) =>
  order === 'newest' ? b.created_at.localeCompare(a.created_at) : a.created_at.localeCompare(b.created_at);

export function groupTasks(tasks: TaskRow[], by: GroupBy, order: Order): TaskGroup[] {
  const sorted = [...tasks].sort(byTime(order));
  if (by === 'none') return sorted.length ? [{ key: 'all', label: '', tasks: sorted }] : [];
  const groups = new Map<string, TaskGroup>();
  for (const task of sorted) {
    const project = task.project_name ?? 'Deleted project';
    const key = by === 'project' ? (task.project_id ?? '') : `${task.project_id ?? ''}/${task.chat_id ?? ''}`;
    const label = by === 'project' ? project : `${project} › ${task.chat_title ?? 'Deleted chat'}`;
    const group = groups.get(key) ?? { key, label, tasks: [] };
    group.tasks.push(task);
    groups.set(key, group);
  }
  // Groups follow the same order as their first task: the group with the newest (or oldest) task comes first.
  return [...groups.values()];
}
