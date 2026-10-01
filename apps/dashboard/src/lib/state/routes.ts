/* Hash routes. Deep links work on reload and from notifications (for example #/chat/<id>).
   Pure parse and format, so they are unit tested. */

export const SETTINGS_TABS = ['agents', 'prompts', 'devices', 'backup', 'general', 'appearance'] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];

export type Route =
  | { name: 'home' }
  | { name: 'chats' }
  | { name: 'chat'; chatId: string }
  | { name: 'project'; projectId: string }
  | { name: 'new-project' }
  | { name: 'trace'; taskId: string | null }
  | { name: 'tools' }
  | { name: 'monitor' }
  | { name: 'settings'; tab: SettingsTab };

export type Section = 'chats' | 'trace' | 'tools' | 'monitor' | 'settings';

const ID = /^[A-Za-z0-9_-]{1,64}$/;

export function parseRoute(hash: string): Route {
  const [name = '', arg = ''] = hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent);
  switch (name) {
    case 'chats':
      return { name: 'chats' };
    case 'chat':
      return ID.test(arg) ? { name: 'chat', chatId: arg } : { name: 'home' };
    case 'project':
      return ID.test(arg) ? { name: 'project', projectId: arg } : { name: 'home' };
    case 'new-project':
      return { name: 'new-project' };
    case 'trace':
      return { name: 'trace', taskId: ID.test(arg) ? arg : null };
    case 'tools':
    case 'monitor':
      return { name };
    case 'settings':
      return { name: 'settings', tab: (SETTINGS_TABS as readonly string[]).includes(arg) ? (arg as SettingsTab) : 'agents' };
    default:
      return { name: 'home' };
  }
}

export function routeHref(route: Route): string {
  switch (route.name) {
    case 'home':
      return '#/';
    case 'chat':
      return `#/chat/${route.chatId}`;
    case 'project':
      return `#/project/${route.projectId}`;
    case 'trace':
      return route.taskId ? `#/trace/${route.taskId}` : '#/trace';
    case 'settings':
      return `#/settings/${route.tab}`;
    default:
      return `#/${route.name}`;
  }
}

export function sectionOf(route: Route): Section {
  switch (route.name) {
    case 'trace':
    case 'tools':
    case 'monitor':
    case 'settings':
      return route.name;
    default:
      return 'chats';
  }
}
