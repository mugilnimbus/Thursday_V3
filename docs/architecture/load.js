// Reads model.js into one structure that the viewer and the checker both use (window.ARCH).
// It expands the short forms: link strings, decision branches, and journey paths.
// Problems that stop the model from being read correctly go in `errors`; check.mjs adds the rest.
(() => {
  'use strict';
  const S = window.ARCH_SCHEMA, M = window.ARCH_MODEL || {};
  const errors = [];
  const err = m => errors.push(m);
  const asList = v => (v == null || v === '' ? [] : Array.isArray(v) ? v : [v]);
  const ID = /^[a-z][a-z0-9_]*$/;

  // The old format used elements, edges, flows and cards. It is not read any more.
  for (const [old, now] of [['elements', 'parts'], ['edges', 'links'], ['flows', 'journeys']]) {
    if (M[old]) err(`model.js uses "${old}" from the old format. Write the model again with "${now}" (see README.md).`);
  }
  if (M.palette && !S.palettes[M.palette]) err(`palette "${M.palette}" is not one of ${Object.keys(S.palettes).join(', ')}`);

  // ---- data items
  const data = new Map();
  for (const d of asList(M.data)) {
    if (!d || !d.id || !ID.test(d.id)) { err(`data item "${d && d.id}": id must be lowercase letters, digits or _`); continue; }
    if (data.has(d.id)) err(`data item ${d.id}: two data items share this id`);
    data.set(d.id, { id: d.id, name: d.name || d.id, fields: d.fields || {}, note: d.note || '' });
  }
  const dataName = id => (data.get(id) || {}).name || id;
  const names = v => asList(v).map(dataName).join(', ');

  // ---- parts
  const root = { id: '', key: '', name: M.name || 'Architecture', kind: 'group', children: [], parent: null, depth: 0, lane: 'main', spec: {}, status: 'accepted' };
  const parts = new Map(), order = [];
  const OLD_KINDS = { actor: 'external', module: 'group', service: 'group', component: 'group or step', interface: 'step',
    policy: 'decision', pool: 'queue or step', batcher: 'queue', database: 'store', hardware: 'external' };

  const headlineOf = (s, kind) => {
    if (s.headline) return s.headline;
    if (kind === 'step') return `${names(s.in) || '?'} → ${names(s.out) || '?'}`;
    if (kind === 'decision') return s.test ? `${s.test}?` : '';
    if (kind === 'store') return s.keeps ? `Keeps ${names(s.keeps)}` : '';
    if (kind === 'queue') return [s.capacity != null ? `Capacity ${s.capacity}` : '', s.when_full ? `full: ${s.when_full}` : ''].filter(Boolean).join(' · ');
    if (kind === 'event') return s.trigger || '';
    return '';
  };

  (function build(specs, parent) {
    if (!Array.isArray(specs)) return err(`${parent.id || 'parts'}: children must be a list`);
    for (const s of specs) {
      if (!s || typeof s !== 'object') { err(`${parent.id || 'parts'}: a part must be an object`); continue; }
      const id = parent.id ? `${parent.id}.${s.id}` : String(s.id);
      if (!s.id || !ID.test(s.id)) err(`${id}: id must be lowercase letters, digits or _, starting with a letter`);
      if (parts.has(id)) err(`${id}: two parts share this id inside the same box`);
      let kind = s.kind;
      if (!S.kinds[kind]) {
        err(`${id}: unknown kind "${kind}"` + (OLD_KINDS[kind] ? ` (old format; use ${OLD_KINDS[kind]})` : ` (use one of ${Object.keys(S.kinds).join(', ')})`));
        kind = (s.children || []).length ? 'group' : 'step';
      }
      if (s.card) err(`${id}: "card" is from the old format. Put its fields on the part itself`);
      let lane = 'main';
      if (s.lane) {
        if (!S.lanes.includes(s.lane)) err(`${id}: unknown lane "${s.lane}" (use one of ${S.lanes.join(', ')})`);
        else if (parent !== root) err(`${id}: only a top-level part can have a lane`);
        else lane = s.lane;
      }
      const n = { id, key: s.id, parent, depth: parent.depth + 1, kind, name: s.name || s.id, headline: headlineOf(s, kind),
        lane, spec: s, status: s.status || 'accepted', children: [] };
      parts.set(id, n);
      order.push(n);
      parent.children.push(n);
      build(s.children || [], n);
    }
  })(M.parts || [], root);

  const isLeaf = n => !n.children.length;
  const within = (n, box) => { for (let p = n; p; p = p.parent) if (p === box) return true; return false; };
  const levelName = depth => S.levels[Math.min(Math.max(depth, 1), S.levels.length) - 1];

  // ---- links: the short form is 'from -> to : label (kind, async)'
  const LINK = /^\s*([\w.]+)\s*->\s*([\w.]+)\s*(?::\s*(.*?))?\s*(?:\(([^()]*)\))?\s*$/;
  const TARGET = /^\s*([\w.]+)\s*(?:\(([^()]*)\))?\s*$/;
  const links = [];
  const flagsOf = (text, where) => {
    const out = { kind: 'data', async: false };
    for (const f of String(text || '').split(',').map(x => x.trim()).filter(Boolean)) {
      if (f === 'async') out.async = true;
      else if (S.links[f]) out.kind = f;
      else err(`${where}: unknown flag "${f}" (use a category: ${Object.keys(S.links).join(', ')}; or async)`);
    }
    return out;
  };
  const addLink = (spec, where) => {
    const a = parts.get(spec.from), b = parts.get(spec.to);
    if (!a) return err(`${where}: "${spec.from}" is not a part`);
    if (!b) return err(`${where}: "${spec.to}" is not a part`);
    if (a === b) return err(`${where}: connects a part to itself`);
    if (within(a, b) || within(b, a)) return err(`${where}: connects a box to something inside it`);
    if (!isLeaf(a) || !isLeaf(b)) err(`${where}: lines join the innermost parts. "${!isLeaf(a) ? a.id : b.id}" has parts inside it; name the part inside that sends or receives`);
    const label = spec.label || '';
    const carries = data.has(label) ? label : spec.carries && data.has(spec.carries) ? spec.carries : null;
    if (spec.carries && !data.has(spec.carries)) err(`${where}: carries "${spec.carries}", which is not a data item`);
    links.push({ from: a.id, to: b.id, a, b, label, text: data.has(label) ? dataName(label) : label, carries,
      kind: spec.kind, async: !!spec.async, contract: spec.contract || null, branch: spec.branch || null,
      source: spec.source, i: links.length });
  };

  asList(M.links).forEach((l, i) => {
    const where = `link ${i + 1}`;
    if (typeof l === 'string') {
      const m = l.match(LINK);
      if (!m) return err(`${where}: "${l}" is not in the form 'from -> to : label (kind, async)'`);
      const f = flagsOf(m[4], `${where} (${l})`);
      return addLink({ from: m[1], to: m[2], label: m[3] || '', ...f, source: 'links' }, `${where} (${m[1]} -> ${m[2]})`);
    }
    if (!l || typeof l !== 'object') return err(`${where}: must be a string or an object`);
    if (l.card) err(`${where}: "card" is from the old format; use "contract"`);
    if (l.kind && !S.links[l.kind]) err(`${where}: unknown category "${l.kind}"`);
    addLink({ ...l, kind: S.links[l.kind] ? l.kind : 'data', async: !!l.async, source: 'links' }, `${where} (${l.from} -> ${l.to})`);
  });

  // A decision's lines come from its branches: { 'condition': 'target (flags)' }.
  for (const n of order) {
    if (n.kind !== 'decision' || !n.spec.branches || typeof n.spec.branches !== 'object') continue;
    for (const [cond, target] of Object.entries(n.spec.branches)) {
      const m = String(target).match(TARGET), where = `${n.id} branch "${cond}"`;
      if (!m) { err(`${where}: "${target}" must be a part id, optionally followed by (kind, async)`); continue; }
      addLink({ from: n.id, to: m[1], label: cond, ...flagsOf(m[2], where), branch: cond, source: 'branch' }, where);
    }
  }

  // ---- journeys: each path is 'a -> b -> c'; every step must have a link from the step before
  const linkBetween = (a, b) => links.filter(l => l.from === a && l.to === b);
  const journeys = [];
  asList(M.journeys).forEach((j, i) => {
    const id = j && j.id ? j.id : `journey_${i + 1}`;
    const J = { id, name: (j && j.name) || id, type: j && j.type, notes: (j && j.notes) || {}, paths: [], links: [], missing: [], steps: [] };
    if (!j || !j.id || !ID.test(j.id)) err(`journey ${i + 1}: needs an id of lowercase letters, digits or _`);
    if (j && j.steps) err(`journey ${id}: "steps" is from the old format; use "paths"`);
    const seenLinks = new Set();
    for (const p of asList(j && j.paths)) {
      const ids = String(p).split('->').map(x => x.trim()).filter(Boolean);
      const bad = ids.filter(x => !parts.has(x));
      if (bad.length) { err(`journey ${id}: ${bad.map(x => `"${x}"`).join(', ')} ${bad.length > 1 ? 'are not parts' : 'is not a part'}`); continue; }
      if (ids.length < 2) { err(`journey ${id}: the path "${p}" needs at least two parts`); continue; }
      J.paths.push(ids);
      for (let k = 1; k < ids.length; k++) {
        const found = linkBetween(ids[k - 1], ids[k]);
        if (!found.length) J.missing.push(`${ids[k - 1]} -> ${ids[k]}`);
        for (const l of found) if (!seenLinks.has(l.i)) { seenLinks.add(l.i); J.links.push(l); }
      }
    }
    // Order the steps: rank by the longest path from the start, ignoring lines that loop back.
    const nodes = [...new Set(J.paths.flat())], out = new Map(nodes.map(x => [x, new Set()]));
    for (const ids of J.paths) for (let k = 1; k < ids.length; k++) out.get(ids[k - 1]).add(ids[k]);
    const state = new Map(), preds = new Map(nodes.map(x => [x, []]));
    const dfs = u => { state.set(u, 1); for (const v of out.get(u)) { if (state.get(v) === 1) continue; preds.get(v).push(u); if (!state.get(v)) dfs(v); } state.set(u, 2); };
    nodes.forEach(x => { if (!state.get(x)) dfs(x); });
    const rank = new Map();
    const rankOf = v => rank.has(v) ? rank.get(v) : (rank.set(v, 0), rank.set(v, preds.get(v).length ? Math.max(...preds.get(v).map(rankOf)) + 1 : 0), rank.get(v));
    nodes.forEach(rankOf);
    J.steps = nodes.map((x, k) => ({ id: x, rank: rank.get(x), k })).sort((p, q) => p.rank - q.rank || p.k - q.k).map(s => ({ id: s.id, rank: s.rank }));
    J.start = J.paths.length ? J.paths[0][0] : null;
    journeys.push(J);
  });

  window.ARCH = { S, M, root, parts, order, data, links, journeys, errors, isLeaf, within, levelName, dataName, asList };
})();
