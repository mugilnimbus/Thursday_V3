import { expect, test } from '@playwright/test';
import { event, fakeGateway } from './gateway';

test('approving from the chat answers the gateway and the task finishes live', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto('/');
  await expect(page).toHaveURL(/#\/chat\/c1$/);
  await expect(page.getByText('Please delete old.log')).toBeVisible();
  await expect(page.locator('.task-head')).toContainText('Delete old.log');
  const card = page.getByRole('alertdialog');
  await expect(card).toContainText('Approval needed · delete');
  await expect(page.getByRole('group', { name: 'Running task' })).toContainText('waiting for you');
  await expect(page.locator('.telemetry')).toContainText('gemma-4-26b');

  await card.getByRole('button', { name: 'Allow once' }).click();
  await expect(card).toBeHidden();
  expect(fake.writes).toContainEqual({ method: 'POST', path: '/v1/approvals/ap1', body: { decision: 'allow_once' } });

  fake.stream()?.send(JSON.stringify(event('approval_resolved', { approval_id: 'ap1', call_key: 't1:1:0', outcome: 'allowed', by: 'gateway' })));
  fake.stream()?.send(JSON.stringify(event('task_state', { state: 'completed', pause_state: 'none', summary: 'Deleted old.log.' })));
  await expect(page.locator('.task .dot')).toHaveAttribute('title', 'Completed');
  await expect(page.getByRole('group', { name: 'Running task' })).toBeHidden();
});

test('sending a message streams the reply and clears the message bar', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/chat/c1');
  const box = page.getByRole('textbox', { name: 'Message' });
  await box.fill('List the files');
  await box.press('Enter');
  await expect.poll(() => fake.writes.find((w) => w.path === '/v1/chats/c1/messages')?.body).toMatchObject({ text: 'List the files' });
  const sent = fake.writes.find((w) => w.path === '/v1/chats/c1/messages')!.body as { client_message_id: string };
  fake.stream()?.send(JSON.stringify({ kind: 'chat_delta', chat_id: 'c1', client_message_id: sent.client_message_id, text: 'Two files: ' }));
  fake.stream()?.send(JSON.stringify({ kind: 'chat_delta', chat_id: 'c1', client_message_id: sent.client_message_id, text: 'a and b.' }));
  await expect(page.getByText('Two files: a and b.')).toBeVisible();
  await expect(box).toHaveValue('');
});

test('deleting a chat asks first and removes it', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto('/#/chat/c1');
  await page.locator('.sidebar').getByRole('button', { name: 'Actions for chat Clean up logs' }).click();
  await page.getByRole('menuitem', { name: 'Delete chat…' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Delete chat “Clean up logs”?');
  await dialog.getByRole('button', { name: 'Delete chat' }).click();
  await expect(dialog).toBeHidden();
  expect(fake.writes.map((w) => `${w.method} ${w.path}`)).toContain('DELETE /v1/chats/c1');
  await expect(page.locator('.sidebar')).not.toContainText('Clean up logs');
  // It was the last chat: the app settles on the chat list and stays usable (it once looped between two redirects).
  await expect(page).toHaveURL(/#\/chats$/);
  await expect(page.getByRole('region', { name: 'Chats' })).toBeVisible();
  await page.locator('.sidebar').getByRole('button', { name: 'Settings' }).click();
  await expect(page).toHaveURL(/#\/settings/);
});

test('talking sends what was heard, and replies are read aloud when that is on', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/chat/c1');
  const mic = page.getByRole('button', { name: 'Talk to Thursday' });
  await expect(mic).toBeEnabled();
  await mic.click();
  await expect(page.locator('.voice-state')).toHaveText('Listening');
  await page.waitForTimeout(700);
  await page.getByRole('button', { name: 'Stop and send what you said' }).click();
  await expect.poll(() => fake.writes.find((w) => w.path === '/v1/chats/c1/messages')?.body).toMatchObject({ text: 'List the files in logs' });
  expect(fake.recordings[0]).toBeGreaterThan(100);

  await page.getByRole('button', { name: 'Read replies aloud' }).click();
  fake.stream()?.send(JSON.stringify(event('assistant_message', { text: 'There are three files.' }, { source: 'voice', task_id: null, ts: new Date().toISOString() })));
  await expect.poll(() => fake.spoken).toEqual(['There are three files.']);
  await expect(page.locator('.voice-state')).toHaveText('Voice agent is replying');
  await expect(page.locator('.voice-state')).not.toHaveText('Voice agent is replying', { timeout: 5000 }); // playback ended
  await expect(page.locator('.voice-error')).toHaveCount(0);
});

test('revoking a device asks in the app and then removes it', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/settings/devices');
  await page.getByRole('button', { name: 'Revoke' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Revoke Pixel 9?');
  await dialog.getByRole('button', { name: 'Revoke' }).click();
  await expect.poll(() => fake.writes.map((w) => `${w.method} ${w.path}`)).toContain('DELETE /v1/devices/dev-1');
});

const SCREENS = ['#/chat/c1', '#/chats', '#/project/p1', '#/new-project', '#/trace/t1', '#/tools', '#/monitor',
  '#/settings/agents', '#/settings/prompts', '#/settings/devices', '#/settings/backup', '#/settings/general', '#/settings/appearance'];

for (const [label, width, height] of [['phone', 390, 844], ['tablet', 820, 1080], ['desktop', 1440, 900]] as const) {
  test(`no screen scrolls sideways on ${label}`, async ({ page }) => {
    await fakeGateway(page);
    await page.setViewportSize({ width, height });
    for (const screen of SCREENS) {
      await page.goto(`/${screen}`);
      await page.waitForLoadState('networkidle');
      await expect(page.locator('.view.on')).toBeVisible();
      const overflow = await page.evaluate(() => {
        const viewport = document.querySelector('.viewport')!;
        const wide = [...document.querySelectorAll<HTMLElement>('.viewport *')].filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.right > viewport.getBoundingClientRect().right + 1 && !el.closest('pre, .tabs');
        });
        return { page: document.documentElement.scrollWidth - innerWidth, viewport: viewport.scrollWidth - viewport.clientWidth, offenders: wide.slice(0, 3).map((el) => el.className) };
      });
      expect(overflow, `${screen} at ${width}px`).toEqual({ page: 0, viewport: 0, offenders: [] });
    }
    const narrow = width <= 760;
    await expect(page.locator('.tabbar')).toBeVisible({ visible: narrow });
    await expect(page.locator('.sidebar')).toBeVisible({ visible: !narrow });
  });
}
