// Checks model.js for mistakes, missing detail, and anything no journey covers.
// Run after every edit:  node check.mjs        (exit code 1 while something must be fixed)
// It reads schema.js, load.js and checks.js, the same files the viewer reads.
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, '..', '..');   // check.mjs lives in <project>/docs/architecture/
const sandbox = { window: {} };
for (const name of ['schema.js', 'model.js', 'load.js', 'checks.js']) {
  try { vm.runInNewContext(readFileSync(path.join(here, name), 'utf8'), sandbox, { filename: name }); }
  catch (e) { console.error(`${name} does not parse: ${e.message}`); process.exit(1); }
}
const A = sandbox.window.ARCH;
if (!sandbox.window.ARCH_MODEL) { console.error('model.js must set window.ARCH_MODEL'); process.exit(1); }
const { M, parts, links, journeys, data, order } = A;
const { errors, warnings, undecided, covered } = sandbox.window.ARCH_CHECK(A, c => existsSync(path.resolve(projectRoot, c)));

// ---- summary
const depth = Math.max(0, ...order.map(n => n.depth));
console.log(`${M.name}: ${parts.size} parts, ${links.length} lines, ${journeys.length} journeys, ${data.size} data items, ${depth} levels deep`);
console.log(`Lines on a journey: ${covered} of ${links.length}`);
if (errors.length) { console.log(`\nMust fix (${errors.length})`); errors.forEach(m => console.log('  x ' + m)); }
if (warnings.length) { console.log(`\nWorth a look (${warnings.length})`); warnings.forEach(m => console.log('  - ' + m)); }
if (undecided.length) { console.log(`\nStill undecided (${undecided.length})`); undecided.forEach(m => console.log('  ? ' + m)); }
if (!errors.length && !warnings.length) console.log('No problems found.');
process.exit(errors.length ? 1 : 0);
