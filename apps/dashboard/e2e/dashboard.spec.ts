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
  await expect(page.locator('.telemetry')).toContainText('80 tok/s · 900/32000');
  await expect(page.locator('.telemetry')).not.toContainText('gemma');
  // The status is one line resting on the message box. The particle line is drawn over the messages, which
  // scroll on behind it, the status line and the message box (smoked glass) to the bottom of the chat; the face
  // stays behind the messages.
  const [status, bar, line, thread] = await Promise.all(['.telemetry', '.composer', '.voicefield.line', '.thread'].map((css) => page.locator(css).boundingBox()));
  expect(status!.height).toBeLessThan(24);
  expect(bar!.y - (status!.y + status!.height)).toBeLessThan(16);
  expect(Math.abs(line!.y + line!.height - (bar!.y + bar!.height))).toBeLessThan(2);
  expect(Math.abs(thread!.y + thread!.height - (bar!.y + bar!.height))).toBeLessThan(2);
  expect(await page.locator('.composer').evaluate((element) => getComputedStyle(element).backgroundImage), 'see-through').toContain('gradient');
  expect(await page.locator('.composer').evaluate((element) => getComputedStyle(element).backgroundColor), 'not a solid backing').toMatch(/0\.45\)|\/ 0\.45/);
  const layer = (css: string) => page.locator(css).evaluate((element) => Number(getComputedStyle(element).zIndex));
  expect(await layer('.voicefield.line')).toBeGreaterThan(await layer('.thread'));
  expect(await layer('.voicefield:not(.line)')).toBeLessThan(await layer('.thread'));

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

test('a table in a reply is drawn as a table, and a numbered list keeps its numbers', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/chat/c1');
  const box = page.getByRole('textbox', { name: 'Message' });
  await box.fill('Show the files');
  await box.press('Enter');
  await expect.poll(() => fake.writes.find((w) => w.path === '/v1/chats/c1/messages')?.body).toBeTruthy();
  const sent = fake.writes.find((w) => w.path === '/v1/chats/c1/messages')!.body as { client_message_id: string };
  const text = '| File | Lines |\n|---|--:|\n| `a.py` | 120 |\n\n3. third step\n4. fourth step\n';
  fake.stream()?.send(JSON.stringify({ kind: 'chat_delta', chat_id: 'c1', client_message_id: sent.client_message_id, text }));
  const table = page.getByRole('table');
  await expect(table.getByRole('columnheader')).toHaveText(['File', 'Lines']);
  await expect(table.getByRole('cell')).toHaveText(['a.py', '120']);
  await expect(page.locator('.md ol')).toHaveAttribute('start', '3');
});

test('the bolt sends a chat straight to the main agent, and messages say so', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/chat/c1');
  const bolt = page.getByRole('button', { name: 'Send straight to the main agent' });
  await expect(bolt).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('textbox', { name: 'Message' })).toHaveAttribute('placeholder', 'Message Thursday…');
  await bolt.click();
  await expect(bolt).toHaveAttribute('aria-pressed', 'true');
  expect(fake.writes).toContainEqual({ method: 'PATCH', path: '/v1/chats/c1', body: { direct: true } });
  await expect(page.getByRole('textbox', { name: 'Message' })).toHaveAttribute('placeholder', 'Message the main agent…');

  const box = page.getByRole('textbox', { name: 'Message' });
  await box.fill('Delete old.log');
  await page.getByRole('button', { name: 'Send to main agent' }).click();
  await expect(page.getByText('Queued · direct')).toBeVisible();
  const sent = fake.writes.find((w) => w.path === '/v1/chats/c1/messages')!.body as { client_message_id: string; text: string };
  expect(sent.text).toBe('Delete old.log');
  fake.stream()?.send(JSON.stringify(event('user_message', { text: 'Delete old.log', client_message_id: sent.client_message_id, direct: true }, { source: 'voice', task_id: null, ts: new Date().toISOString() })));
  await expect(page.locator('.msg.user .meta', { hasText: 'You · direct' })).toBeVisible();
  await expect(page.locator('.voice-state')).not.toHaveText('Voice agent is thinking'); // nothing is coming back from the voice model

  await bolt.click();
  await expect(bolt).toHaveAttribute('aria-pressed', 'false');
  expect(fake.writes.filter((w) => w.method === 'PATCH').map((w) => w.body)).toEqual([{ direct: true }, { direct: false }]);
});

test('a right-click on Send chooses where the chat sends, even before anything is typed', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/chat/c1');
  // Playwright counts an aria-disabled button as unclickable; a real right-click on it still opens the menu.
  await page.getByRole('button', { name: 'Send', exact: true }).click({ button: 'right', force: true });
  const menu = page.getByRole('menu', { name: 'Where this chat sends' });
  await expect(menu.getByRole('menuitemradio', { name: 'Send to the voice agent' })).toHaveAttribute('aria-checked', 'true');
  await menu.getByRole('menuitemradio', { name: 'Send straight to the main agent' }).click();
  await expect(menu).toBeHidden();
  expect(fake.writes).toContainEqual({ method: 'PATCH', path: '/v1/chats/c1', body: { direct: true } });
  await page.getByRole('button', { name: 'Send to main agent' }).click({ button: 'right', force: true });
  await expect(menu.getByRole('menuitemradio', { name: 'Send straight to the main agent' })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  expect(fake.writes.filter((w) => w.method === 'PATCH')).toHaveLength(1);
});

test('a tool call shows in the task card as soon as it is requested, and turns green or red when it ends', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto('/#/chat/c1');
  await expect(page.locator('.task-head')).toContainText('Delete old.log');
  const line = (name: string) => page.locator('.timeline li', { hasText: name });
  const call = (key: string, tool: string, status: string, extra: Record<string, unknown> = {}) =>
    JSON.stringify(event('tool_call', { call_key: key, tool, arguments: { path: `${tool}.txt` }, status, ...extra }));

  fake.stream()?.send(call('t1:3:0', 'fs.read', 'requested'));
  await expect(line('fs.read').first()).toHaveClass(/tl-run/);
  const dot = await line('fs.read').first().evaluate((el) => {
    const css = getComputedStyle(el, '::before');
    return { name: css.animationName, color: css.backgroundColor };
  });
  expect(dot.name).toBe('pulse');
  expect(dot.color).toBe(await page.evaluate(() => { const probe = document.createElement('i'); probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('--accent'); document.body.append(probe); const c = getComputedStyle(probe).color; probe.remove(); return c; }));

  fake.stream()?.send(call('t1:3:0', 'fs.read', 'ok', { result: 'hello', seconds: 0.01 }));
  await expect(line('fs.read').first()).toHaveClass(/tl-ok/);
  await expect(line('fs.read').first()).toContainText('→ hello');

  fake.stream()?.send(call('t1:4:0', 'fs.edit', 'requested'));
  await expect(line('fs.edit').first()).toHaveClass(/tl-run/);
  fake.stream()?.send(call('t1:4:0', 'fs.edit', 'error', { result: 'old_string not found', seconds: 0.01 }));
  await expect(line('fs.edit').first()).toHaveClass(/tl-bad/);
  expect(await line('fs.edit').count()).toBe(1);
});

test('the full trace keeps reasoning and tools in their true chronological order', async ({ page }) => {
  const fake = await fakeGateway(page);
  fake.resolved = true;
  fake.trace = [
    event('task_state', { state: 'working', pause_state: 'none' }),
    event('llm_call', { agent: 'main', step: 1, status: 'ok', text: 'First I will inspect the folder.' }),
    event('tool_call', { call_key: 't1:1:0', tool: 'fs.list', arguments: { path: 'logs' }, status: 'requested' }),
    event('tool_call', { call_key: 't1:1:0', tool: 'fs.list', arguments: { path: 'logs' }, status: 'ok', result: 'old.log' }),
    event('llm_call', { agent: 'main', step: 2, status: 'ok', text: 'I found the old file, so I will remove it.' }),
    event('tool_call', { call_key: 't1:2:0', tool: 'fs.delete', arguments: { path: 'old.log' }, status: 'requested' }),
    event('tool_call', { call_key: 't1:2:0', tool: 'fs.delete', arguments: { path: 'old.log' }, status: 'ok', result: 'deleted' }),
    event('llm_call', { agent: 'main', step: 3, status: 'ok', text: 'The old file was deleted.' }),
    event('task_state', { state: 'completed', pause_state: 'none', summary: 'Deleted old.log.' }),
  ];

  await page.goto('/#/trace/t1');
  await expect(page.locator('.step-card')).toHaveCount(3);
  const visibleOrder = await page.locator('.steps-v .reasoning, .steps-v .toolcall, .steps-v .answer').allTextContents();
  expect(visibleOrder.map((text) => text.replace(/\s+/g, ' ').trim())).toEqual([
    'First I will inspect the folder.',
    'ok fs.list {"path":"logs"} old.log',
    'I found the old file, so I will remove it.',
    'ok fs.delete {"path":"old.log"} deleted',
    'The old file was deleted.',
    'Deleted old.log.Final result, sent to the voice agent',
  ]);
});

test('an agent can use the built-in llama.cpp, with its folder chosen from this PC', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/settings/agents');
  const voice = page.locator('.agent-card', { hasText: 'Voice agent' });
  await expect(voice.getByLabel('Endpoint')).toBeVisible();
  await voice.getByRole('button', { name: 'Built-in llama.cpp' }).click();
  await expect(voice.getByRole('button', { name: 'Built-in llama.cpp' })).toHaveAttribute('aria-pressed', 'true');
  await expect(voice.getByLabel('Models folder')).toBeVisible();
  await expect(voice.getByLabel('Endpoint')).toHaveCount(0);
  await expect(voice.getByLabel('API key')).toHaveCount(0);
  await expect(voice.getByLabel('Context length')).toHaveValue('32000');
  await expect(voice.getByLabel('Temperature').locator('option').first()).toHaveText('0.8 (default)');
  await expect(voice.getByLabel('Graphics cards').locator('option').first()).toHaveText('All cards (default)');
  await expect(voice.getByLabel('Split between the cards')).toBeVisible();
  await voice.getByLabel('A model larger than one card').selectOption('1');
  await expect(voice.getByLabel('Split between the cards')).toHaveCount(0);
  await expect(voice.getByText('Only what does not fit there goes on the next card')).toBeVisible();
  await voice.getByLabel('A model larger than one card').selectOption('');
  await voice.getByLabel('Graphics cards').selectOption('1');
  await expect(voice.getByLabel('Split between the cards')).toHaveCount(0);
  await voice.getByLabel('Layers on the cards').selectOption('24');
  await expect(voice.getByLabel('Unload when not used for')).toHaveValue('5');
  await voice.getByLabel('Unload when not used for').selectOption('0');
  await expect(voice.getByText('Save to see the models this provider offers.')).toBeVisible();
  await voice.getByRole('button', { name: 'Browse' }).click();
  await expect(voice.getByRole('button', { name: "LM Studio's models" })).toContainText('.lmstudio');
  await expect(voice.getByRole('button', { name: '.lmstudio', exact: true })).toBeVisible();
  await voice.getByRole('button', { name: 'Models', exact: true }).click();
  await voice.getByRole('button', { name: 'Use this folder' }).click();
  await expect(voice.getByLabel('Models folder')).toHaveValue('C:\\');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect.poll(() => fake.writes.find((w) => w.path === '/v1/agents/voice/llm')?.body).toMatchObject({ provider: 'llamacpp', models_dir: 'C:\\', gpu: 1, idle_unload_minutes: 0, load: { gpu_layers: '24' } });
  // The built-in llama.cpp has no address, and the PC refuses an empty one: none is sent.
  expect(fake.writes.find((w) => w.path === '/v1/agents/voice/llm')?.body).not.toHaveProperty('base_url');
  await expect(voice.getByRole('combobox', { name: 'Model', exact: true })).toBeVisible();
});

test('a model listed twice by the provider still gives a working list, and every setting is a list with its default', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await fakeGateway(page);
  await page.goto('/#/settings/agents');
  const voice = page.locator('.agent-card', { hasText: 'Voice agent' });
  const model = voice.getByRole('combobox', { name: 'Model', exact: true });
  await expect(model).toHaveValue('google/gemma-4-e2b');
  await model.selectOption('google/gemma-4-e4b');
  await expect(voice.getByLabel('Temperature').locator('option').first()).toHaveText("LM Studio's (default)");
  await voice.getByLabel('Temperature').selectOption('0.7');
  await expect(voice.getByLabel('Context length').locator('option', { hasText: '262,144' })).toHaveCount(0);
  await voice.getByRole('button', { name: 'OpenAI-compatible' }).click();
  await expect(voice.getByRole('button', { name: 'OpenAI-compatible' })).toHaveAttribute('aria-pressed', 'true');
  await expect(voice.getByRole('heading', { name: 'Load parameters' })).toHaveCount(0);
  await expect(voice.getByLabel('Temperature').locator('option').first()).toHaveText('1 (default)');
  expect(errors).toEqual([]);
});

test('an API key is typed in Settings, stored at once, and never shown again; each agent has its own context limit', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/settings/agents');
  const main = page.locator('.agent-card', { hasText: 'Main agent' });
  const key = main.getByLabel('API key');
  await expect(main.getByText('not set')).toBeVisible();
  await key.fill('sk-test-123');
  await expect(key).toHaveAttribute('type', 'password');
  await main.getByRole('button', { name: 'Save key' }).click();
  await expect.poll(() => fake.writes.find((w) => w.path === '/v1/agents/main/llm/key')?.body).toEqual({ key: 'sk-test-123' });
  await expect(key).toHaveValue('');
  await expect(main.getByRole('button', { name: 'Remove' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('sk-test-123');

  const limit = main.getByLabel('Summarise older turns when the context reaches');
  await expect(limit).toHaveAttribute('step', '1024');
  await expect(limit).toHaveAttribute('placeholder', '28672');
  await limit.fill('65536');
  await expect(page.locator('.agent-card', { hasText: 'Voice agent' }).getByLabel('Send at most this much of the conversation')).toHaveValue('');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect.poll(() => fake.writes.find((w) => w.path === '/v1/agents/main/llm')?.body).toEqual({ compact_at_tokens: 65536 });
});

test('in a narrow window a task opens its trace in place of the list, and Back returns to the list', async ({ page }) => {
  await fakeGateway(page);
  await page.setViewportSize({ width: 820, height: 900 });
  await page.goto('/#/trace');
  const task = page.locator('.task-item', { hasText: 'Delete old.log' });
  await expect(task).toBeVisible();
  await expect(page.locator('.trace-head')).toBeHidden();
  await task.click();
  await expect(page.locator('.trace-head')).toBeInViewport();
  await expect(page.locator('.task-list')).toBeHidden();
  await page.getByRole('button', { name: 'All tasks' }).click();
  await expect(task).toBeVisible();
  await expect(page.locator('.trace-head')).toBeHidden();
});

test('in a wide window the list and the trace sit side by side, and the list scrolls by itself', async ({ page }) => {
  await fakeGateway(page);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto('/#/trace');
  await expect(page.locator('.task-item', { hasText: 'Delete old.log' })).toBeVisible();
  await expect(page.locator('.trace-head')).toBeInViewport();
  await expect(page.getByRole('button', { name: 'All tasks' })).toBeHidden();
  expect(await page.locator('.task-list').evaluate((el) => getComputedStyle(el).overflowY)).toBe('auto');
});

test('Save and Discard sit at the top right of Settings, and leaving a tab offers save, discard or cancel', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto('/#/settings/agents');
  const voice = page.locator('.agent-card', { hasText: 'Voice agent' });
  const save = page.getByRole('button', { name: 'Save changes' });
  await expect(save).toHaveCount(0);
  await voice.getByLabel('Temperature').selectOption('0.7');
  const tabs = await page.getByRole('tablist').boundingBox();
  const button = await save.boundingBox();
  expect(button!.x).toBeGreaterThan(tabs!.x + 400);
  expect(Math.abs(button!.y - tabs!.y)).toBeLessThan(40);
  await page.locator('.viewport').evaluate((el) => (el.scrollTop = 2000));
  await expect(save).toBeInViewport();

  await page.getByRole('tab', { name: 'General' }).click();
  const dialog = page.getByRole('dialog', { name: 'Unsaved changes' });
  await expect(dialog.getByRole('button')).toHaveText(['Cancel', 'Discard', 'Save changes']);
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('tab', { name: 'Agents' })).toHaveAttribute('aria-selected', 'true');
  await expect(voice.getByLabel('Temperature')).toHaveValue('0.7');
  expect(fake.writes.filter((w) => w.path === '/v1/agents/voice/llm')).toHaveLength(0);

  await page.getByRole('tab', { name: 'General' }).click();
  await dialog.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true');
  expect(fake.writes.find((w) => w.path === '/v1/agents/voice/llm')?.body).toEqual({ inference: { temperature: 0.7 } });

  await page.getByRole('tab', { name: 'Prompts' }).click();
  await page.getByLabel('System prompt').fill('You are Thursday, edited.');
  await expect(page.getByRole('button', { name: 'Save as version 3' })).toBeVisible();
  await page.getByRole('tab', { name: 'Devices' }).click();
  await expect(dialog.getByRole('button')).toHaveText(['Cancel', 'Discard', 'Save as version 3']);
  await dialog.getByRole('button', { name: 'Discard' }).click();
  await expect(page.getByRole('tab', { name: 'Devices' })).toHaveAttribute('aria-selected', 'true');
  expect(fake.writes.filter((w) => w.path.endsWith('/prompt'))).toHaveLength(0);
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

test('a message in the chat can be copied', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await fakeGateway(page);
  await page.goto('/');
  const message = page.locator('.msg', { hasText: 'Please delete old.log' });
  await message.getByRole('button', { name: 'Copy message' }).click();
  await expect(message.getByRole('button', { name: 'Copied' })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('Please delete old.log');
});

test('working data is kept for a period chosen from a list, and Monitor shows how much is stored', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/settings/general');
  const keep = page.getByLabel('Keep working data for');
  await expect(keep).toHaveValue('30');
  await expect(keep.locator('option')).toHaveText(['7 days', '30 days', '3 months', '6 months', '1 year', 'Until I delete it']);
  await keep.selectOption('Until I delete it');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect.poll(() => fake.writes.find((w) => w.path === '/v1/settings/general')?.body).toMatchObject({ data_retention_days: 0 });

  await page.goto('/#/monitor');
  const stored = page.getByLabel('Stored data');
  await expect(stored).toContainText('Total');
  await expect(stored).toContainText('180 MB');
  await expect(stored).toContainText('Main agent · tasks and saved steps');
});

test('Monitor shows how long each agent took to start answering', async ({ page }) => {
  await fakeGateway(page);
  await page.goto('/#/monitor');
  const tiles = page.locator('.tile', { hasText: 'time to first token' });
  await expect(tiles).toHaveCount(2);
  await expect(tiles.nth(0)).toContainText('Main');
  await expect(tiles.nth(0)).toContainText('0.40 s');
  await expect(tiles.nth(1)).toContainText('Voice');
  await expect(tiles.nth(1)).toContainText('0.08 s');
});

test('a reply is read aloud sentence by sentence, starting while it is still being written', async ({ page }) => {
  const fake = await fakeGateway(page);
  await page.goto('/#/chat/c1');
  await page.getByRole('button', { name: 'Read replies aloud' }).click();
  const part = (text: string) => fake.stream()?.send(JSON.stringify({ kind: 'chat_delta', chat_id: 'c1', client_message_id: 'm9', text }));
  part('The folder holds three log files. ');
  part('Two of them are from last week');
  await expect.poll(() => fake.spoken).toEqual(['The folder holds three log files.']);
  part(' and one is from today.');
  const whole = 'The folder holds three log files. Two of them are from last week and one is from today.';
  fake.stream()?.send(JSON.stringify(event('assistant_message', { text: whole, client_message_id: 'm9' }, { source: 'voice', task_id: null, ts: new Date().toISOString() })));
  await expect.poll(() => fake.spoken).toEqual(['The folder holds three log files.', 'Two of them are from last week and one is from today.']);
  await page.waitForTimeout(600);
  expect(fake.spoken).toHaveLength(2); // the finished reply is not read a second time
  await expect(page.locator('.voice-error')).toHaveCount(0);
});
