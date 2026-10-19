# Project Documents

These pages describe the system as built: all PC services, the web dashboard, the Android app, push-to-talk voice, and the three model providers with their settings.

Every diagram in these pages is a picture rendered from the Mermaid text folded under it. The Mermaid text is the editable source; the SVG files in [diagrams/](diagrams/) are generated from it in the dashboard's colours and are never edited by hand (see [Diagrams](#diagrams)). [diagrams/system-overview.svg](diagrams/system-overview.svg) is the one the root README shows.

| Diagram | Page |
|---|---|
| [system-context](diagrams/system-context.svg) | ARCHITECTURE.md, system context |
| [system-overview](diagrams/system-overview.svg) | ARCHITECTURE.md, containers |
| [data-flow](diagrams/data-flow.svg) | ARCHITECTURE.md, events, logs, and metrics flow |
| [main-agent-components](diagrams/main-agent-components.svg) | ARCHITECTURE.md, main agent |
| [main-agent-loop](diagrams/main-agent-loop.svg) | ARCHITECTURE.md, main agent, the agent loop |
| [voice-agent-loop](diagrams/voice-agent-loop.svg) | ARCHITECTURE.md, voice agent |
| [gateway-components](diagrams/gateway-components.svg) | ARCHITECTURE.md, gateway |
| [navigation](diagrams/navigation.svg) | FLOWS.md, screens |
| [main-flow](diagrams/main-flow.svg) | FLOWS.md, instruction with an approval |
| [voice-flow](diagrams/voice-flow.svg) | FLOWS.md, push-to-talk and read aloud |
| [direct-flow](diagrams/direct-flow.svg) | FLOWS.md, direct mode |
| [model-settings](diagrams/model-settings.svg) | FLOWS.md, model settings and loading |
| [task-control](diagrams/task-control.svg) | FLOWS.md, pause and stop |
| [approval-states](diagrams/approval-states.svg) | FLOWS.md, approval states |
| [trust-boundaries](diagrams/trust-boundaries.svg) | SECURITY.md, trust boundaries |

## What lives where

- **Root `README.md`**: the front page. What the project is, does, and solves, how it works and integrates, requirements, installation, and the folder structure.
- **`docs/` (this folder)**: the design. Architecture (C4), flow and control-flow diagrams, API and event contracts, and the security overview, with the reasons behind important choices; and the operations guide for running and maintaining it.

Pages:

- [Project brief](PROJECT.md): purpose, users, intended use, scope, key behavior, and choices with reasons.
- [Architecture model](architecture/index.html): every part of the system, its rules and decisions, and the main flows, as a diagram that opens level by level (open the file in a browser; [how to read it](architecture/README.md)). What is decided and what is still open is recorded there, on the part it belongs to.
- [Architecture](ARCHITECTURE.md): C4 context, container, and component views, data ownership, layers, dependency rules, and runtime.
- [Flows](FLOWS.md): UX flows, navigation, data flows, and control-flow (sequence) diagrams with failure paths.
- [Contracts](CONTRACTS.md): API and event contracts between components and with external systems, including integration notes and known mismatches.
- [Security](SECURITY.md): trust boundaries, roles, sensitive operations, and enforceable guarantees.
- [Operations](OPERATIONS.md): setting up, first run, everyday commands, where data is kept, updating, backups and restore, checks, and troubleshooting.
- [Diagrams](diagrams/): exported SVG copies of diagrams used in the README or elsewhere. Mermaid in the pages is the editable source.

## Diagrams

Each diagram is a Mermaid block whose first line is `%% svg: <name>`. In the page the block sits folded under the picture it produces:

- Edit the Mermaid text, never the SVG.
- Regenerate the pictures with `node docs/diagrams/render.mjs` (it reads every `docs/*.md`, renders each named block with the dashboard's dark theme, and writes `docs/diagrams/<name>.svg`). It needs Mermaid's browser bundle (`MERMAID_JS=<path to mermaid.min.js>`, version 11) and a Chromium for Playwright (`THURSDAY_E2E_CHROMIUM` if Playwright's own is not installed); neither is a dependency of this project.
- Colours come from the `classDef` lines in each block and follow the dashboard: blue for clients, teal for the gateway, violet for the agents, green for tools, pink for speech, amber for stored data, lavender dashed for things outside Thursday, red for danger.
- Keep labels short and avoid two labelled arrows between the same pair of boxes (use one two-way arrow), so labels never overlap. Look at the rendered picture before committing.
