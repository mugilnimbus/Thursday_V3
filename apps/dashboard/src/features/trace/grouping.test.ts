import { describe, expect, it } from 'vitest';
import type { TaskRow } from '../../lib/api/types';
import { groupTasks } from './grouping';

const task = (id: string, minute: number, project: string, chat: string): TaskRow => ({
  task_id: id, chat_id: `c-${chat}`, project_id: `p-${project}`, state: 'completed', pause_state: 'none', instruction: id, summary: '',
  created_at: `2026-10-01T10:${String(minute).padStart(2, '0')}:00+00:00`, updated_at: '', chat_title: chat, project_name: project,
});

const tasks = [task('a', 1, 'Demo', 'Logs'), task('b', 5, 'Test', 'Game'), task('c', 3, 'Demo', 'Logs'), task('d', 4, 'Demo', 'Notes')];

describe('trace grouping', () => {
  it('groups by chat with the most recent group first', () => {
    const groups = groupTasks(tasks, 'chat', 'newest');
    expect(groups.map((g) => g.label)).toEqual(['Test › Game', 'Demo › Notes', 'Demo › Logs']);
    expect(groups[2].tasks.map((t) => t.task_id)).toEqual(['c', 'a']);
  });

  it('groups by project and can run oldest first', () => {
    const groups = groupTasks(tasks, 'project', 'oldest');
    expect(groups.map((g) => [g.label, g.tasks.map((t) => t.task_id)])).toEqual([['Demo', ['a', 'c', 'd']], ['Test', ['b']]]);
  });

  it('gives one unlabelled list when grouping is off, and nothing for no tasks', () => {
    expect(groupTasks(tasks, 'none', 'newest')[0].tasks.map((t) => t.task_id)).toEqual(['b', 'd', 'c', 'a']);
    expect(groupTasks([], 'chat', 'newest')).toEqual([]);
  });

  it('labels tasks whose chat or project was deleted', () => {
    const orphan = { ...task('x', 9, 'Demo', 'Logs'), chat_title: null, project_name: null };
    expect(groupTasks([orphan], 'chat', 'newest')[0].label).toBe('Deleted project › Deleted chat');
  });
});
