import { app } from '../../lib/state/app.svelte';
import { router } from '../../lib/state/router.svelte';
import type { Section } from '../../lib/state/routes';
import { ui } from '../../lib/state/ui.svelte';

export const SECTIONS: { id: Section; label: string; icon: string }[] = [
  { id: 'chats', label: 'Chats', icon: 'chat' },
  { id: 'trace', label: 'Trace', icon: 'trace' },
  { id: 'tools', label: 'Tools', icon: 'tools' },
  { id: 'monitor', label: 'Monitor', icon: 'mon' },
  { id: 'settings', label: 'Settings', icon: 'set' },
];

/** Chats opens the chat list on a phone and the most recent chat on a wide screen. */
export function goSection(section: Section): void {
  if (section === 'chats') {
    if (ui.narrow) return router.go({ name: 'chats' });
    const chat = ui.session?.chatId ?? app.latestChat()?.chat_id;
    return router.go(chat ? { name: 'chat', chatId: chat } : { name: 'home' });
  }
  if (section === 'trace') return router.go({ name: 'trace', taskId: null });
  if (section === 'settings') return router.go({ name: 'settings', tab: 'agents' });
  router.go({ name: section });
}
