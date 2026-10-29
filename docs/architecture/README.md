# Architecture model

One model of the system, drawn in one page. Open `index.html` in a browser. It needs no server and no install.

## The three views

| View | Shows |
|---|---|
| Structure | The system, level by level: 1 System, 2 Containers, 3 Components, 4 and deeper Detail |
| Journeys | One journey, one data item's flow, or a trace, drawn alone from its start to its end |
| Data | Every data item as a table, and the steps that turn one item into another |

## Reading the Structure view

- **Zoom.** Scroll to open one level deeper. The box under the pointer opens, and the spot under the pointer stays where it is. Scroll back to close a level. `+`, `-`, and the level numbers do the same for everything in view.
- **Step inside.** Double-click a box, or select it and press Enter, to make it fill the screen. Lines to parts outside the box end at stubs on the edges: "FROM" on the left, "TO" on the right. Click a stub to go to that part. The path at the top and Backspace step back out.
- **Shapes.** Each kind of part has one shape:

  | Shape | Kind | Meaning |
  |---|---|---|
  | Box with a title band | Group | Holds other parts; it opens when you zoom in |
  | Rectangle | Step | Does one thing to the data |
  | Diamond | Decision | Tests one condition and sends the data down one branch |
  | Cylinder | Store | Keeps data |
  | Box with bars | Queue | Holds items in order |
  | Pill with a dot | Event | Starts a journey |
  | Rectangle with double sides | External | A person, a caller, or an outside service |
  | Screen | UI | What a person sees and does |

- **Lines.** The colour is the category. The arrowhead repeats it: a filled arrow for things that move forward, an open arrow for a result, a bar for a refusal or an error, and a dot for monitoring. **A dotted line means the sender waits for an answer. A solid line means the sender does not wait.** Click a category in the legend to hide or show it. Double-click it to see that category alone.
- **Cards.** Click a part for what it does, its conditions or its data, its rules, the choices and why, what was rejected, the journeys through it, and its lines. Click a line for what it carries and its contract.
- **Light up a journey.** Pick a journey in the bottom bar and press Next. Each part lights up in turn on this view.
- **Undecided.** A part with an open question has a dashed amber border, and the side panel lists it.

## Reading the Journeys view

- Pick a journey, a data flow, or a trace in the bottom bar.
- Each top-level part is a band. Inside the bands, the journey reads from left to right.
- Decisions are diamonds. Each branch line shows its condition.
- Press Next to walk the journey one step at a time. A note explains a step where one is written.
- **Trace.** On any part's card, "Trace forward" draws everything the part reaches, and "Trace back" draws everything that reaches it. Use a trace to see where a control signal comes from, and which parts it changes.
- Scroll to zoom where the pointer is. Drag to move. "Fit all" shows everything.

## Reading the Data view

- Each table is one data item, with its fields and types.
- A solid arrow is a step that turns one item into another. Its label names the step.
- A long-dashed grey arrow is a field that refers to another item.
- "Kept in" names the stores that keep the item. Click a table for the parts that make, use, carry, and keep it.

## Links

| Link | Opens |
|---|---|
| `index.html#in:<box id>` | The Structure view, inside that box |
| `index.html#<part id>` | The Structure view, with that part selected |
| `index.html#journey:<journey id>` | That journey, drawn alone |
| `index.html#dataflow:<data id>` | The flow of that data item |
| `index.html#trace:<part id>:fwd` | Everything that part reaches (`:back` for everything that reaches it) |
| `index.html#data:<data id>` | The Data view, with that item selected |

## Pictures

"Save SVG" saves what is on screen as an SVG picture in the current theme. "PNG" saves a bitmap. For the README, save level 1 of the Structure view in light mode and in dark mode as `docs/images/architecture.svg` and `docs/images/architecture-dark.svg`, and show them with a `<picture>` element.

## Changing the model

1. Edit `model.js`.
2. Run `node check.mjs` and fix everything under "Must fix".
3. Reload the page. The side panel lists the same problems as the check.

## Files

| File | Edit it? | What it is |
| --- | --- | --- |
| `model.js` | Yes, this one only | Every part, line, journey, and data item |
| `check.mjs` | No | Finds mistakes: `node check.mjs` |
| `schema.js`, `load.js`, `checks.js` | No | The kinds, the loader, and the check rules |
| `index.html`, `viewer.js`, `flow.js`, `viewer.css` | No | Draw whatever the model contains |

## Field reference

### The model

`window.ARCH_MODEL = { name, note, palette, lanes, data, parts, links, journeys }`

- `palette` is one of `violet` (default), `graphite`, `slate`, `stone`, `amber`, or `lime`.
- `lanes` can rename the side bands of level 1, for example `{ right: 'Hardware' }`.

### Parts (`parts`)

`{ id, kind, name, does, lane, children, ... }`. The full id is the dotted path: `gate.mcp.read.parse`.

| Kind | Needs |
|---|---|
| `external` | `does` |
| `group` | `children`, `does` |
| `step` | `in`, `out` (data ids, or `'none'`), `does` |
| `decision` | `test`, `branches: { 'condition': 'target id (kind, async)', otherwise: '...' }` |
| `store` | `keeps` (data ids), `does` |
| `queue` | `capacity`, `when_full`, `does` |
| `event` | `trigger` |
| `ui` | `does`, and `children` for its screens and events |

Every kind can also have: `headline`, `lane` (top-level parts only), `rules`, `choice`, `why`, `rejected`, `failure`, `exposes`, `stops` (why a journey can end here), `code` (where it is built), `status` (`open` or `revisit`; leave it out when agreed), and `question` (needed with `open` or `revisit`).

### Data (`data`)

`{ id, name, fields: { field: 'type' }, note }`. A type can be another data item's id, or a list of them: `'policy_rule[]'`.

### Lines (`links`)

- Short form: `'from -> to : label (kind, async)'`. The part in parentheses is optional. If the label is a data id, the line carries that item.
- Object form: `{ from, to, label, kind, async, contract: { mode, timeout, retry } }`. A line between two top-level parts needs a contract, except `ui`, `config`, and `monitor` lines.
- Categories: `data` (default), `control`, `result`, `error`, `store`, `monitor`, `ui`, `config`.
- Lines join the innermost parts. A decision's lines come from its `branches`.

### Journeys (`journeys`)

`{ id, name, type, paths: ['a -> b -> c', 'b -> d'], notes: { 'part id': 'note' } }`

- `type` is `user`, `call`, `timer`, `signal`, or `data`.
- Each step in a path needs a line from the step before it.
- A second path that starts at an earlier part is a split or a branch.
- A path ends at an external, a store, the UI, or a part with `stops`.
