// The rules that check.mjs and the viewer both apply to a loaded model (window.ARCH).
// ARCH_CHECK(A, exists) returns { errors, warnings, undecided, covered }. `exists(path)` says whether a
// "code" path is in the project; the viewer cannot see the disk, so it leaves that check out.
window.ARCH_CHECK = (A, exists) => {
  'use strict';
  const { S, parts, order, data, links, journeys, isLeaf, asList } = A;
  const errors = [...A.errors], warnings = [];
  const err = m => errors.push(m), warn = m => warnings.push(m);
  const inSystem = n => { let p = n; while (p.parent && p.parent.depth) p = p.parent; return p.kind === 'group'; };

  // ---- parts: each kind has its own fields
  for (const n of order) {
    const s = n.spec;
    if (!s.name) warn(`${n.id}: no name`);
    if (!s.does && !['event', 'decision'].includes(n.kind)) warn(`${n.id}: no "does" saying what it is responsible for`);
    if (!S.statuses[n.status]) err(`${n.id}: unknown status "${n.status}" (use ${Object.keys(S.statuses).join(', ')})`);
    if ((n.status === 'open' || n.status === 'revisit') && !s.question) err(`${n.id}: marked ${n.status}, so it needs a "question" saying what is undecided`);
    if (s.choice && !s.why) warn(`${n.id}: has a "choice" but no "why"`);
    for (const f of S.kinds[n.kind].needs) {
      const v = s[f];
      if (f === 'children' ? !(v || []).length : v == null || v === '' || (Array.isArray(v) && !v.length)) {
        err(`${n.id}: a ${n.kind} needs "${f}"` + (f === 'children' ? '. A group holds parts; if it has none, it is a step, decision, store, or queue' : ''));
      }
    }
    if ((n.children || []).length && !['group', 'ui', 'external'].includes(n.kind)) err(`${n.id}: a ${n.kind} cannot hold parts; make it a group`);
    for (const f of ['in', 'out', 'keeps']) {
      for (const d of asList(s[f])) if (d !== 'none' && !data.has(d)) err(`${n.id}: "${f}" names "${d}", which is not a data item. Add it to data`);
    }
    if (n.kind === 'decision' && s.branches) {
      const keys = Object.keys(s.branches);
      if (keys.length < 2) err(`${n.id}: a decision needs at least two branches`);
      if (!keys.includes('otherwise')) err(`${n.id}: add an "otherwise" branch, so every case goes somewhere`);
    }
    // A condition written as text in a leaf hides a decision that the diagram cannot show.
    if (isLeaf(n) && n.kind !== 'decision') {
      for (const r of asList(s.rules)) {
        if (/^\s*(if|when|unless|otherwise)\b|\b(if|unless|otherwise)\b/i.test(r)) {
          warn(`${n.id}: the rule "${r}" is a condition. Make it a decision part with branches, so the diagram shows it`);
        }
      }
    }
    if (isLeaf(n) && ['step', 'decision'].includes(n.kind) && n.depth <= 2 && inSystem(n)) {
      warn(`${n.id}: a ${n.kind} at level ${n.depth}. Level ${n.depth} shows ${S.levels[n.depth - 1].toLowerCase()}; put steps and decisions inside a component (level 3 or deeper)`);
    }
    if (n.kind === 'group' && n.children.length === 1) warn(`${n.id}: a group with one part inside. Merge them, or add the parts that are missing`);
    if (n.children.length > 8) warn(`${n.id}: ${n.children.length} parts directly inside it. Group them into another level (about 7 or fewer per box)`);
    if (/\.[a-z0-9]{1,5}$/i.test(n.name)) warn(`${n.id}: named after a file ("${n.name}"). Name the responsibility; put the file in "code"`);
    if (exists) for (const c of asList(s.code)) if (!exists(c)) warn(`${n.id}: "code" names ${c}, which does not exist in the project`);
  }

  // ---- links
  const top = n => { let p = n; while (p.parent && p.parent.depth) p = p.parent; return p; };
  const labelUse = new Map(), seen = new Set();
  for (const l of links) {
    const at = `${l.from} -> ${l.to}`;
    if (l.source === 'links' && l.a.kind === 'decision') err(`${at}: a decision's lines come from its "branches". Remove this link and add a branch`);
    if (!l.label) warn(`${at}: no label saying what travels`);
    if (/\b(dependenc(y|ies)|depends? on|imports?|wiring|wired|inject(s|ed|ion)?)\b/i.test(l.label)) {
      err(`${at}: labelled "${l.label}", a code dependency. A line is something that happens while the system runs`);
    }
    const key = `${l.from}>${l.to}>${l.kind}>${l.label}`;
    if (seen.has(key)) warn(`${at}: listed twice`);
    seen.add(key);
    if (!l.branch && !l.carries) labelUse.set(l.label, (labelUse.get(l.label) || 0) + 1);
    if (top(l.a) !== top(l.b) && !S.noCardNeeded.includes(l.kind) && !l.contract) {
      warn(`${at}: crosses from ${top(l.a).name} to ${top(l.b).name} without a contract. Use the object form with contract: { mode, timeout, retry }`);
    }
  }
  for (const [label, n] of labelUse) if (label && n > 3) warn(`"${label}" labels ${n} lines. A label says what travels on that one line`);
  for (const [id, d] of data) {
    for (const [f, t] of Object.entries(d.fields)) {
      const ref = String(t).replace(/\[\]$/, '');
      if (/^[a-z][a-z0-9_]*$/.test(ref) && !data.has(ref) && !/^(string|text|number|integer|int|float|boolean|bool|date|time|datetime|timestamp|bytes|json|ulid|uuid|id|url|path|enum|list|map|any)$/.test(ref)) {
        warn(`data ${id}.${f}: type "${t}" is not a known type or a data item`);
      }
    }
  }

  // ---- journeys: every line, branch, event and part must be on at least one
  const onJourney = new Set(), partOnJourney = new Set(), starts = new Set();
  for (const j of journeys) {
    if (!j.type || !S.journeyTypes[j.type]) err(`journey ${j.id}: "type" must be one of ${Object.keys(S.journeyTypes).join(', ')}`);
    if (!j.paths.length) err(`journey ${j.id}: needs at least one path`);
    for (const m of j.missing) err(`journey ${j.id}: no line ${m}. Add it to links (or to the decision's branches)`);
    j.links.forEach(l => onJourney.add(l.i));
    j.paths.flat().forEach(id => partOnJourney.add(id));
    if (j.start) starts.add(j.start);
    // Each path must end somewhere a journey can end.
    const ends = new Set(j.paths.map(p => p[p.length - 1]));
    for (const p of j.paths) for (const id of p.slice(0, -1)) ends.delete(id);
    for (const id of ends) {
      const n = parts.get(id);
      const ok = ['external', 'store', 'ui'].includes(n.kind) || (n.parent && n.parent.kind === 'ui') || top(n).kind !== 'group' || n.spec.stops;
      if (!ok) warn(`journey ${j.id}: ends at ${id}, ${/^[aeiou]/.test(n.kind) ? 'an' : 'a'} ${n.kind}. Carry it on to where it ends (an outside party, a store, the UI), or say why it stops there with stops: '...'`);
    }
    for (const k of Object.keys(j.notes)) if (!j.paths.flat().includes(k)) warn(`journey ${j.id}: a note for ${k}, which is not on the journey`);
  }
  if (!journeys.length) err('no journeys. List every journey (user actions, incoming calls, timers, signals, data arriving) and trace each one');
  for (const l of links) {
    if (onJourney.has(l.i) || S.offJourney.includes(l.kind)) continue;
    warn(l.branch ? `${l.from}: no journey takes the branch "${l.branch}". Add a journey or a path that does`
      : `${l.from} -> ${l.to} (${l.label || l.kind}): on no journey. Add it to the journey it belongs to, or remove it`);
  }
  for (const n of order) {
    if (!isLeaf(n)) continue;
    if (n.kind === 'event' && !starts.has(n.id)) warn(`${n.id}: an event that starts no journey. Add the journey it starts`);
    else if (!partOnJourney.has(n.id) && !links.some(l => (l.a === n || l.b === n) && S.offJourney.includes(l.kind))) warn(`${n.id}: on no journey`);
  }
  for (const [id] of data) {
    const used = links.some(l => l.carries === id) || order.some(n => ['in', 'out', 'keeps'].some(f => asList(n.spec[f]).includes(id)));
    if (!used) warn(`data ${id}: nothing carries, reads, writes, or keeps it`);
  }

  const undecided = order.filter(n => n.status !== 'accepted').map(n => `${n.id}: ${n.spec.question || '(no question)'}`);
  const covered = links.filter(l => onJourney.has(l.i) || S.offJourney.includes(l.kind)).length;
  return { errors, warnings, undecided, covered };
};
