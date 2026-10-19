// Checks model.js for mistakes the diagram would otherwise hide or draw wrongly.
// Run after every edit:  node check.mjs        (exit code 1 when something must be fixed)
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const file = fileURLToPath(new URL('./model.js', import.meta.url));
const sandbox = { window: {} };
try { vm.runInNewContext(readFileSync(file, 'utf8'), sandbox, { filename: 'model.js' }); }
catch (e) { console.error(`model.js does not parse: ${e.message}`); process.exit(1); }
const M = sandbox.window.ARCH_MODEL;
if (!M) { console.error('model.js must set window.ARCH_MODEL'); process.exit(1); }

const KINDS = ['actor', 'service', 'interface', 'queue', 'policy', 'pool', 'ui', 'hardware', 'batcher', 'database', 'component'];
const LANES = ['main', 'top', 'bottom', 'left', 'right'];
const LINKS = ['data', 'control', 'result', 'error', 'store', 'monitor', 'ui', 'config'];
const STATUSES = ['accepted', 'open', 'revisit'];

const errors = [], warnings = [], parts = new Map();
const err = m => errors.push(m), warn = m => warnings.push(m);

(function walk(list, parent, depth) {
  if (!Array.isArray(list)) return err(`${parent || 'elements'}: must be a list`);
  const seen = new Set();
  for (const p of list) {
    const id = parent ? `${parent}.${p.id}` : String(p.id);
    if (!p.id || !/^[a-z][a-z0-9_]*$/.test(p.id)) err(`${id}: id must be lowercase letters, digits or _, starting with a letter`);
    if (seen.has(p.id)) err(`${id}: two parts share this id inside the same box`);
    seen.add(p.id);
    if (!p.name) err(`${id}: needs a name`);
    if (p.kind && !KINDS.includes(p.kind)) err(`${id}: unknown kind "${p.kind}" (use one of ${KINDS.join(', ')})`);
    if (p.lane && !LANES.includes(p.lane)) err(`${id}: unknown lane "${p.lane}" (use one of ${LANES.join(', ')})`);
    const c = p.card || {}, leaf = !(p.children || []).length;
    if (!c.does) warn(`${id}: card has no "does"`);
    if (c.status && !STATUSES.includes(c.status)) err(`${id}: unknown status "${c.status}" (use one of ${STATUSES.join(', ')})`);
    if (!c.status) warn(`${id}: no status, so it counts as undecided`);
    if ((c.status === 'open' || c.status === 'revisit') && !c.question) warn(`${id}: marked ${c.status} but has no "question" saying what is undecided`);
    if (leaf && p.kind !== 'actor' && !(c.rules || []).length) warn(`${id}: has no parts inside and no rules, so it is not designed yet`);
    if (c.decision && !c.why) warn(`${id}: has a decision but no "why"`);
    if (!p.headline) warn(`${id}: no headline (the one line shown on the box)`);
    parts.set(id, { id, parent, leaf, depth });
    walk(p.children || [], id, depth + 1);
  }
})(M.elements, '', 1);

const inside = (id, box) => id === box || id.startsWith(box + '.');
const links = new Set();
(M.edges || []).forEach((e, i) => {
  const at = `connection ${i + 1} (${e.from} -> ${e.to})`;
  if (!parts.has(e.from)) err(`${at}: "from" names a part that does not exist`);
  if (!parts.has(e.to)) err(`${at}: "to" names a part that does not exist`);
  if (e.async !== undefined && typeof e.async !== 'boolean') err(`${at}: async must be true or false`);
  if (e.kind && !LINKS.includes(e.kind)) err(`${at}: unknown category "${e.kind}" (use one of ${LINKS.join(', ')})`);
  if (parts.has(e.from) && parts.has(e.to)) {
    if (e.from === e.to) err(`${at}: connects a part to itself`);
    else if (inside(e.from, e.to) || inside(e.to, e.from)) err(`${at}: connects a box to something inside it; name the inner part on both ends`);
    if (links.has(`${e.from}>${e.to}>${e.kind || 'data'}`)) warn(`${at}: listed twice with the same kind`);
    links.add(`${e.from}>${e.to}>${e.kind || 'data'}`);
  }
  if (!e.label) warn(`${at}: no label saying what travels`);
});

const linked = (a, b) => (M.edges || []).some(e => e.from === a && e.to === b);
(M.flows || []).forEach(f => {
  if (!f.id || !f.name) err(`flow "${f.id || f.name || '?'}": needs an id and a name`);
  (f.steps || []).forEach((s, i) => {
    if (!parts.has(s.at)) return err(`flow "${f.id}" step ${i + 1}: "${s.at}" does not exist`);
    if (!s.note) warn(`flow "${f.id}" step ${i + 1}: no note`);
    const prev = i ? f.steps[i - 1].at : null;
    if (prev && parts.has(prev) && !linked(prev, s.at)) warn(`flow "${f.id}" step ${i + 1}: no connection from ${prev} to ${s.at}, so the walk cannot light one up`);
  });
});

const connected = new Set((M.edges || []).flatMap(e => [e.from, e.to]));
for (const p of parts.values()) if (p.leaf && !connected.has(p.id)) warn(`${p.id}: nothing connects to it`);

const undecided = [];
(function scan(list, parent) {
  for (const p of list || []) {
    const id = parent ? `${parent}.${p.id}` : p.id, c = p.card || {}, leaf = !(p.children || []).length;
    if (c.status !== 'accepted' || (leaf && p.kind !== 'actor' && !(c.rules || []).length)) undecided.push(id + (c.question ? `: ${c.question}` : ''));
    scan(p.children, id);
  }
})(M.elements, '');

const depth = Math.max(0, ...[...parts.values()].map(p => p.depth));
const byCat = LINKS.map(k => [k, (M.edges || []).filter(e => (e.kind || 'data') === k).length]).filter(([, n]) => n);
console.log(`${M.name}: ${parts.size} parts, ${(M.edges || []).length} connections, ${(M.flows || []).length} flows, ${depth} levels deep`);
console.log('Connections: ' + byCat.map(([k, n]) => `${k} ${n}`).join(', '));
if (errors.length) { console.log(`\nMust fix (${errors.length})`); errors.forEach(m => console.log('  x ' + m)); }
if (warnings.length) { console.log(`\nWorth a look (${warnings.length})`); warnings.forEach(m => console.log('  - ' + m)); }
if (undecided.length) { console.log(`\nStill undecided (${undecided.length})`); undecided.forEach(m => console.log('  ? ' + m)); }
if (!errors.length && !warnings.length) console.log('No problems found.');
process.exit(errors.length ? 1 : 0);
