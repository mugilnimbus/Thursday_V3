# Architecture model

One model of the system, drawn as a diagram you open level by level. Open `index.html` in a browser; no server or install is needed.

## Files

| File | Edit it? | What it is |
| --- | --- | --- |
| `model.js` | Yes, this one only | Every part, connection, decision, and flow |
| `check.mjs` | No | Finds mistakes in the model: `node check.mjs` |
| `index.html`, `viewer.js`, `viewer.css` | No | Draw whatever the model contains |

The field reference is the comment at the top of `model.js`.

## Reading the diagram

- **Levels.** Level 1 is the whole system. Scroll, press `+`, or pick a level number to open every box one step further. Double-click a single box to open or close just that one.
- **Moving.** Drag, use the arrow keys, or hold Shift and scroll to move sideways. `0` switches between fitting everything on screen and actual size.
- **Cards.** Click a box for what it does, its rules and numbers, the decision and why, what was rejected, and what it receives and sends. Click a line for that connection's contract.
- **Lines.** Every connection belongs to one category, shown by its colour: data flow, control flow, result, error or refusal, storage, monitoring, shown in the UI, configuration. A dashed line is a hand-off that does not wait for an answer. Click a category in the legend to hide or show it; double-click to see that category alone. The side panel lists every connection by category.
- **Flows.** Pick a flow in the bottom bar and press Next to follow one request part by part.
- **Pictures.** "Save picture" downloads the open level, whole and at full size, as a PNG for pages that cannot run the viewer.
- **Undecided.** Parts with an open question have a dashed amber border and are listed in the side panel.

## Changing the model

1. Edit `model.js`.
2. Run `node check.mjs` and fix everything under "Must fix".
3. Reload the page. Problems the check would report are also listed at the top of the side panel.

Common edits:

- **Add a part:** add an entry to its parent's `children`, then add the connections to and from it.
- **Open a part up:** give it `children` and move its connections onto the inner parts.
- **Record a decision:** fill in `decision`, `why`, and `rejected` on the part's card, and set `status: 'accepted'`.
- **Change a decision:** update the card, and set `status: 'revisit'` with a `question` on every part the change touches, so they show up as undecided until confirmed.
- **Add a flow:** list the parts a request passes through, in order. Each step needs a connection from the step before.
