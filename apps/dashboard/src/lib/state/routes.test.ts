import { describe, expect, it } from 'vitest';
import { parseRoute, routeHref, sectionOf, type Route } from './routes';

describe('routes', () => {
  it('round-trips every route through the hash', () => {
    const routes: Route[] = [
      { name: 'home' },
      { name: 'chats' },
      { name: 'chat', chatId: 'c-1' },
      { name: 'project', projectId: 'p_2' },
      { name: 'new-project' },
      { name: 'trace', taskId: null },
      { name: 'trace', taskId: 't9' },
      { name: 'tools' },
      { name: 'monitor' },
      { name: 'settings', tab: 'backup' },
    ];
    for (const route of routes) expect(parseRoute(routeHref(route))).toEqual(route);
  });

  it('falls back safely on unknown or unsafe input', () => {
    expect(parseRoute('#/chat/../../x')).toEqual({ name: 'home' });
    expect(parseRoute('#/settings/nope')).toEqual({ name: 'settings', tab: 'agents' });
    expect(parseRoute('#/whatever')).toEqual({ name: 'home' });
    expect(parseRoute('')).toEqual({ name: 'home' });
  });

  it('maps chat screens to the Chats section', () => {
    expect(sectionOf({ name: 'project', projectId: 'p' })).toBe('chats');
    expect(sectionOf({ name: 'monitor' })).toBe('monitor');
  });
});
