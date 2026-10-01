// Renders the diagrams of the design pages to SVG files in this folder, in the dashboard's colours.
//
// Every Mermaid block in docs/*.md whose first line is `%% svg: <name>` becomes docs/diagrams/<name>.svg.
// The Mermaid text in the pages is the source; never edit the SVG files by hand.
//
// Needs two things that are already on a development machine and are not dependencies of this project:
//   - Mermaid's browser bundle: set MERMAID_JS to a `mermaid.min.js` (version 11).
//   - A Chromium for Playwright (the dashboard's dev dependency): set THURSDAY_E2E_CHROMIUM to a chrome.exe
//     if Playwright's own browser is not installed.
//
//   MERMAID_JS=/path/to/mermaid.min.js node docs/diagrams/render.mjs [--preview <folder for PNG copies>]

import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const docs = resolve(here, '..');
const require = createRequire(resolve(docs, '../apps/dashboard/package.json'));
const { chromium } = require('@playwright/test');

const mermaidPath = process.env.MERMAID_JS;
if (!mermaidPath) throw new Error('Set MERMAID_JS to a mermaid.min.js file.');
const previewAt = process.argv.indexOf('--preview');
const previewDir = previewAt > 0 ? resolve(process.argv[previewAt + 1]) : null;

// The dashboard's black theme: near-black panels, violet accent, light text.
const PAGE = '#07060c';
const config = {
  startOnLoad: false,
  securityLevel: 'strict',
  theme: 'base',
  htmlLabels: false, // plain SVG text: renders the same in every viewer
  fontFamily: '"Segoe UI", Inter, system-ui, sans-serif',
  flowchart: { htmlLabels: false, curve: 'basis', nodeSpacing: 46, rankSpacing: 62, padding: 14, useMaxWidth: false },
  sequence: { useMaxWidth: false, mirrorActors: false, messageMargin: 34, actorMargin: 56, boxMargin: 12, boxTextMargin: 6, noteMargin: 12 },
  state: { useMaxWidth: false },
  themeVariables: {
    fontSize: '15px',
    background: PAGE,
    primaryColor: '#24163f',
    primaryTextColor: '#f6f3fb',
    primaryBorderColor: '#9b63ff',
    secondaryColor: '#0b2b2a',
    tertiaryColor: '#120f1c',
    lineColor: '#b39cf0',
    textColor: '#e9e4f5',
    titleColor: '#bdb5cb',
    edgeLabelBackground: '#171329',
    clusterBkg: '#0d0b16',
    clusterBorder: '#463d5c',
    nodeBorder: '#9b63ff',
    actorBkg: '#24163f',
    actorBorder: '#9b63ff',
    actorTextColor: '#f6f3fb',
    actorLineColor: '#463d5c',
    signalColor: '#c9a8ff',
    signalTextColor: '#f6f3fb',
    labelBoxBkgColor: '#171329',
    labelBoxBorderColor: '#463d5c',
    labelTextColor: '#f6f3fb',
    loopTextColor: '#bdb5cb',
    noteBkgColor: '#2e2410',
    noteBorderColor: '#f5b544',
    noteTextColor: '#ffeccb',
    activationBkgColor: '#33274f',
    activationBorderColor: '#9b63ff',
    sequenceNumberColor: '#07060c',
    transitionColor: '#b39cf0',
    transitionLabelColor: '#e9e4f5',
    stateLabelColor: '#f6f3fb',
    stateBkg: '#24163f',
    compositeBackground: '#0d0b16',
    altBackground: '#120f1c',
    specialStateColor: '#c9a8ff',
  },
};

/** The blocks to render: [name, mermaid text]. */
function blocks() {
  const found = [];
  for (const file of readdirSync(docs).filter((name) => name.endsWith('.md')).sort()) {
    const text = readFileSync(join(docs, file), 'utf8');
    for (const match of text.matchAll(/```mermaid\r?\n%% svg: ([a-z0-9-]+)\r?\n([\s\S]*?)```/g)) found.push([match[1], match[2], file]);
  }
  return found;
}

const browser = await chromium.launch({ executablePath: process.env.THURSDAY_E2E_CHROMIUM || undefined });
const page = await browser.newPage({ deviceScaleFactor: 1, viewport: { width: 2400, height: 1800 } });
await page.setContent(`<!doctype html><html><body style="margin:0;background:${PAGE}"><div id="stage"></div></body></html>`);
await page.addScriptTag({ path: mermaidPath });
await page.evaluate((cfg) => window.mermaid.initialize(cfg), config);
if (previewDir) mkdirSync(previewDir, { recursive: true });

let failed = false;
const names = new Set();
for (const [name, code, file] of blocks()) {
  if (names.has(name)) throw new Error(`Two diagrams are named ${name}.`);
  names.add(name);
  try {
    const svg = await page.evaluate(
      async ({ name, code, PAGE }) => {
        const { svg } = await window.mermaid.render(`d-${name}`, code);
        const stage = document.getElementById('stage');
        stage.innerHTML = svg;
        const el = stage.querySelector('svg');
        // Frame the drawing as a card: padding, a dark rounded background, and a fixed size.
        // Mermaid's own frame is the drawing's true size (a sequence diagram's lifelines run on past it).
        const own = el.viewBox.baseVal;
        const box = own && own.width ? own : el.getBBox();
        const pad = 22;
        const [x, y, w, h] = [box.x - pad, box.y - pad, box.width + pad * 2, box.height + pad * 2].map((v) => Math.round(v));
        el.setAttribute('viewBox', `${x} ${y} ${w} ${h}`);
        el.setAttribute('width', String(w));
        el.setAttribute('height', String(h));
        el.removeAttribute('style');
        el.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        const card = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        for (const [key, value] of Object.entries({ x: x + 1, y: y + 1, width: w - 2, height: h - 2, rx: 18, fill: PAGE, stroke: '#2b2637', 'stroke-width': 1.5 })) card.setAttribute(key, String(value));
        el.insertBefore(card, el.firstChild);
        // A soft violet glow around the boxes, like the dashboard's panels.
        const glow = document.createElementNS('http://www.w3.org/2000/svg', 'style');
        glow.textContent = '.node .label-container, .node > rect, .node > path, .node > polygon, rect.actor { filter: drop-shadow(0 0 5px rgba(155, 99, 255, 0.35)); }';
        el.appendChild(glow);
        return new XMLSerializer().serializeToString(el);
      },
      { name, code, PAGE },
    );
    writeFileSync(join(here, `${name}.svg`), `<?xml version="1.0" encoding="UTF-8"?>\n<!-- Generated by render.mjs from ${file}; edit the Mermaid there. -->\n${svg}\n`);
    if (previewDir) await (await page.$('#stage svg')).screenshot({ path: join(previewDir, `${name}.png`) });
    console.log(`ok   ${name}  (${file})`);
  } catch (error) {
    failed = true;
    console.error(`FAIL ${name}  (${file}): ${String(error.message ?? error).split('\n')[0]}`);
  }
}
await browser.close();
if (failed) process.exit(1);
