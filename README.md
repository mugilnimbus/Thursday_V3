# Thursday

A personal agent harness for your own PC: a fast voice agent takes your short instructions and hands them to a main agent that carries them out with tools, with a dashboard and an Android app to watch and control it.

## What problem it solves

Running a capable local agent on your own machine usually means one chat box and a long wait. Thursday splits the work: a small, quick voice agent keeps the conversation going while a larger main agent works through your instructions step by step, asks before doing anything risky, and tells you what happened, from the PC or from your phone.

## What it does

- Chat or talk with a voice agent that delegates tasks to a main agent over the A2A protocol.
- Or switch a chat to **Direct** and send your words straight to the main agent, unchanged; the voice agent only reports the result.
- The main agent runs tools on your PC through MCP tool servers, including a built-in one for files and shell.
- Each task shows as a card that opens into its steps, live: every delegation, LLM call, tool call (purple while it runs, then green or red), approval, and result. A Trace screen keeps the full detail, with each model call's request and response laid out as a readable conversation.
- Risky actions ask you first: allow once, allow always for that chat, or deny.
- Pause, resume, and stop a running task from the UI or by asking the voice agent.
- Projects with their own folders, each holding many chats, with search and history. Deleting a chat or project removes every record of it.
- A web dashboard on the PC and a native Android app for phones and tablets, upright or lying down, reached over Tailscale, with notifications when the device is locked.
- Talk instead of typing: push-to-talk and replies read aloud (Kokoro) piece by piece, so the voice starts within about half a second of the reply's first words, all running locally. When the voice agent's model can hear (a built-in llama.cpp model with an audio projector), it writes down what you said itself; otherwise Whisper does, on the CPU.
- A voice field behind the chat: a line of particles that drifts like a breeze and pulses with sound, and a face made of particles that gathers while Thursday listens, thinks, and speaks (it can be switched off).
- Monitoring: tokens per second and time to first token for each agent, context use, latency, VRAM, RAM, CPU, network, queues, and how much data is stored.
- You choose how long working data is kept (task steps, traces, tool call logs): from 7 days to a year, or until you delete it. Chats stay until you delete them.
- A model provider per agent, chosen in Settings: **LM Studio**, the **built-in llama.cpp** (Thursday starts and stops it), or any **OpenAI-compatible** endpoint. The model is picked from the provider's own list, with load settings, answer settings, and a context limit for each agent. Nothing is loaded until you load it or first use it, Unload frees the hardware, and a model nobody has used for five minutes (your choice per agent) is unloaded by itself.
- API keys are typed in Settings and kept in the operating system's credential store, never in a file.

## How it works

You talk to the voice agent through the gateway. It turns your instruction into an A2A task for the main agent, which plans and calls tools through MCP. Progress and approval requests flow back as events to the gateway, which feeds the dashboard and the phone. Each service owns its own data; the gateway keeps a read model of events for the screens. Speech is a separate local service: the gateway has your recording transcribed and the text is sent as a normal message.

![System overview](docs/diagrams/system-overview.svg)

Detailed design: [architecture](docs/ARCHITECTURE.md), [flows](docs/FLOWS.md), [contracts](docs/CONTRACTS.md), [security](docs/SECURITY.md). Running and maintaining it: [operations](docs/OPERATIONS.md).

## How it integrates

- An LLM endpoint for each agent: LM Studio on the PC, the built-in llama.cpp (downloaded by setup, serving `.gguf` files from a folder you choose), or any OpenAI-compatible service (a cloud provider, or a llama.cpp server you run yourself). A cloud provider sends everything in the model context off your PC.
- The operating system's credential store for API keys (Windows Credential Manager).
- MCP tool servers started as local stdio processes.
- Tailscale for the phone connection, with HTTPS certificates enabled on your tailnet.
- Local speech models (Whisper and Kokoro), downloaded once on first use.

Contracts and integration notes are in [docs/CONTRACTS.md](docs/CONTRACTS.md).

## Requirements

- A Windows 11 PC with a GPU suitable for the models you choose
- A model source: LM Studio, or `.gguf` model files for the built-in llama.cpp, or an OpenAI-compatible endpoint
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if needed)
- Node.js 20 or newer to build the dashboard
- Disk space: about 0.9 GB for the speech models on first use of voice, and about 650 MB for the built-in llama.cpp on a PC with an NVIDIA card (about 35 MB otherwise)
- For the phone: Tailscale on the PC and the phone, and an Android phone (Android 11 or newer)
- To build the Android app yourself: a JDK 21 and the Android SDK

## Installation

### Windows 11

1. Install the Python packages:

```bash
uv sync
```

2. Run setup. It creates `.env` from `.env.example` and generates the service token. It then asks whether you want the built-in llama.cpp, saying how large it is; a yes downloads the official build for this PC (CUDA for an NVIDIA card, otherwise Vulkan, otherwise CPU), checked against the SHA-256 the release publishes. Say no if you will only use LM Studio or a cloud endpoint. It ends with a list of what Thursday needs on this PC and what is still missing, with what to do about each.

```bash
uv run thursday setup
```

3. Build the dashboard (and again after updating Thursday):

```bash
npm ci --prefix apps/dashboard
```

```bash
npm run build --prefix apps/dashboard
```

4. Start everything:

```bash
uv run thursday up
```

This starts the gateway, voice agent, main agent, metrics collector, and speech service as native processes on localhost, checks their health, and restarts any that crash. The main agent starts the built-in tool server for each project on demand. No model is loaded at start.

5. Open the dashboard at http://127.0.0.1:8700 and go to **Settings, Agents**. For each agent choose the provider, then the address (LM Studio or a cloud endpoint) or the models folder (built-in llama.cpp), save, and pick the model from the list. If the endpoint needs a key, type it in the API key box. Then add a project folder under Chats and send a message.

If something is missing (the dashboard was not built, a port is taken), `up` says so before it starts. To see the whole list at any time:

```bash
uv run thursday check
```

To stop everything, press Ctrl+C in that terminal, or run this from any terminal:

```bash
uv run thursday down
```

It asks the running supervisor to shut the services down cleanly, force-stops any service left behind, and stops any built-in llama.cpp server an agent left running. To check them once from another terminal:

```bash
uv run thursday status
```

Data and logs go to `%LOCALAPPDATA%\Thursday` unless `THURSDAY_DATA_DIR` is set. Updating, backups, logs, and troubleshooting are covered in [docs/OPERATIONS.md](docs/OPERATIONS.md).

macOS and Linux are not supported targets for version 1.

### Reaching Thursday from your phone

The phone connects over Tailscale to the gateway's proxy port, which always requires a paired device token. With HTTPS certificates enabled on your tailnet, publish the proxy port inside your tailnet (not to the internet):

```bash
tailscale serve --bg http://127.0.0.1:8701
```

Then open Settings, Devices in the dashboard and make a pairing code. The code is made only on the PC, works once, and expires after five minutes; the dashboard shows it as text and as a QR code. The dashboard shows this PC's tailnet address, found with `tailscale status`; set `GATEWAY_PUBLIC_URL` in `.env` to override it.

### Android app

The signed APK of the current version is in this repository: [apps/android/release/Thursday-1.0.0.apk](apps/android/release/Thursday-1.0.0.apk). Copy it to a phone that is on your tailnet and install it (Android asks you to allow installing from this source the first time), open Thursday, and scan the pairing code from the dashboard. Each phone pairs separately and can be revoked in Settings, Devices.

To build the APK yourself, from `apps/android` with a JDK 21 in `JAVA_HOME`:

```bash
./gradlew :app:assembleRelease
```

The signed APK is written to `app/build/outputs/apk/release/app-release.apk`. Signing reads `apps/android/keystore.properties` (`storeFile`, `storePassword`, `keyAlias`, `keyPassword`), which is ignored by git along with the key file; without it the release build is left unsigned. Keep the key and its password backed up somewhere safe: a phone only accepts an update signed with the same key. A debug build (`./gradlew :app:assembleDebug`) needs no key but cannot replace a release build on a phone without uninstalling it first.

## Models and API keys

Each agent (voice and main) has its own provider, model, and settings, changed in **Settings, Agents** on the dashboard or in **Settings, Main agent / Voice agent** on the phone. `VOICE_LLM_*` and `MAIN_LLM_*` in `.env` only give the starting values.

| Provider | What you give it | Loading |
|---|---|---|
| LM Studio | Its server address | Thursday loads and unloads the model through LM Studio, with your load settings |
| Built-in llama.cpp | The folder that holds your `.gguf` files | Thursday starts one `llama-server` per agent when the model is loaded and stops it on unload, which frees the GPU. A projector file (`mmproj*.gguf`) beside the model is used automatically. A model too large for one graphics card is split across the cards by layer, and what does not fit runs on the CPU. You can have one card filled first, so a model that fits one card leaves the other card free |
| OpenAI-compatible | The endpoint address and, usually, a key | Nothing to load; a cloud endpoint is always marked as sending data off the PC |

**API keys** are not kept in a file. Type a key in the agent's API key box and save; it goes into the operating system's credential store (Windows Credential Manager), encrypted for your account, and is never shown again. Settings only says whether one is set. Each agent keeps one key per provider, so switching an agent from LM Studio to a cloud endpoint never sends one's key to the other. On the phone, saving asks for your fingerprint or PIN first.

**Settings per agent.** Load settings (context length, batch size, flash attention, KV cache, and for llama.cpp which graphics cards to use, whether to spread a model over them or fill one card first, how many layers go on them, and the expert layers kept off them) apply the next time the model loads. **Unload when not used for** sets how long a loaded model may sit idle before it is unloaded (five minutes unless you change it; Never keeps it loaded). Answer settings (temperature, top p, output limit, thinking or reasoning effort) apply to the next call. Each list names the engine's default first. The **context limit** says how many tokens of conversation an agent sends before the main agent summarises older turns, or the voice agent leaves them out; a cloud endpoint does not report its window, so this is the only limit there.

`THURSDAY_SERVICE_TOKEN` in `.env` is generated by setup and is used only between Thursday's own services; do not share it.

## Status and limitations

- The services, the dashboard, and the Android app work end to end on Windows 11 and Android 15 with LM Studio.
- The built-in llama.cpp has been run on a PC with two NVIDIA cards (CUDA build, Gemma 4 E4B and 12B): install, model list, load and unload on a chosen GPU, text, tool calls, and a spoken question through Whisper to the voice agent and on to the main agent. The Vulkan and CPU builds have not been run.
- Voice is push-to-talk with replies read aloud, on the dashboard and the phone; the first use downloads the speech models (about 0.5 GB for Whisper `small` and 0.35 GB for Kokoro). Continuous listening is not built. A model that hears writes down what you said and then answers that text; it does not answer the audio in one step.
- Across several graphics cards, llama.cpp splits a model by layer (the cards work one after the other). Its two parallel split modes do not load on NVIDIA cards in the build setup installs, so they are not offered.
- OpenAI's server-side context compaction is not used; Thursday summarises with the model itself.
- On the phone the speaking face moves to a speech-like pattern, not the actual audio; on the dashboard it follows the audio.
- Restoring from a backup has not been tried end to end.
- Windows and Android are the supported targets for version 1.

## Project structure

Thursday is one repository with a folder for each part. The Python parts form a single [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) that shares one `uv.lock`; each is its own package with one job and a short list of things it may depend on. Services never import each other: they talk over HTTP, A2A, and MCP, and share only the small packages marked below.

```text
thursday/
├── README.md                    this page
├── LICENSE                      Apache License 2.0
├── pyproject.toml               the uv workspace: lists every Python package below
├── uv.lock                      pinned versions of all Python dependencies
├── .python-version              Python 3.12
├── .env.example                 every setting with example values; copied to .env by setup (never committed)
├── .gitignore  .gitattributes   what git leaves out; line endings and binary files
├── thursday_logo.png            the logo (the apps carry resized copies)
│
├── contracts/                   the messages services send each other (shared)
│   ├── src/thursday_contracts/      event envelope, approvals, health, metrics, problems, task control
│   ├── schemas/                     committed JSON Schema of each message (guards against accidents)
│   └── tests/
│
├── packages/                    shared plumbing, used by the services
│   ├── runtime/                     settings from .env, data and log folders, JSON logging, health routes,
│   │                                service-token auth, the event outbox, backups, the credential store
│   └── llm/                         talking to a model: the three providers (LM Studio, built-in llama.cpp,
│                                    OpenAI-compatible), model loading, per-agent settings and keys,
│                                    request capture, reading a streamed response, stream timing
│
├── services/                    the programs that run (each: src/<name>/ with the layers it needs out of
│   │                            transport, application, domain, infrastructure, bootstrap; plus tests/)
│   ├── gateway/                     the one door for clients: projects, chats, pairing, task control,
│   │                                read model, live stream, file views; serves the dashboard
│   ├── voice_agent/                 the conversation: answers quickly and delegates tasks
│   ├── main_agent/                  does the work: agent loop, approvals, context, MCP client
│   ├── tool_server/                 the built-in tools (files, shell) with sandbox and permission policy;
│   │                                started by the main agent, one per project
│   ├── speech/                      speech to text (Whisper) and text to speech (Kokoro), on the CPU
│   └── metrics_collector/           reads CPU, RAM, GPU, and network and pushes them to the gateway
│
├── launcher/                    `uv run thursday up | down | status | check | setup`: starts the services,
│                                restarts a crashed one, prints the report you see in the terminal,
│                                checks what the PC is missing, installs the built-in llama.cpp, and
│                                stops model servers an agent left behind
│
├── apps/
│   ├── dashboard/               the PC web app (Svelte 5, Vite, TypeScript)
│   │   ├── src/lib/                 api (gateway calls), live (stream and polling), state, ui (shared
│   │   │                            components, markdown, the voice field), styles
│   │   ├── src/features/            one folder per screen: shell, chat, projects, trace, tools, monitor, settings
│   │   ├── public/                  logo and icons
│   │   ├── e2e/                     browser tests against a fake gateway
│   │   └── dev/                     pages for trying one part without a chat (dev server only):
│   │                                voicefield.html, taskline.html
│   └── android/                 the phone app (Kotlin, Jetpack Compose)
│       ├── app/src/main/java/app/thursday/
│       │   ├── ui/                  screens: pair, chats, chat, projects, trace, tools, monitor, settings
│       │   ├── live/                the live connection, app state, background service, notifications
│       │   ├── domain/              pure logic with unit tests: timeline, grouping, charts, markdown,
│       │   │                        voice field, agent settings, trace bodies, sentences to read aloud
│       │   ├── data/                gateway client, pairing link, secure token storage
│       │   ├── security/            fingerprint or PIN checks
│       │   └── voice/               push-to-talk recording and spoken replies
│       ├── app/src/main/assets/     the voice field's face data
│       ├── app/src/test/            unit tests
│       └── release/                 the signed APK, ready to install
│
└── docs/                        the design, in pages
    ├── README.md                    index of the pages and how diagrams are made
    ├── PROJECT.md  ARCHITECTURE.md  FLOWS.md  CONTRACTS.md  SECURITY.md  OPERATIONS.md
    └── diagrams/                    the pictures (generated from the Mermaid in the pages by render.mjs)
```

### What `contracts/` is for

Services must not import each other's code, yet they have to agree exactly on the shape of what they send: an event, an approval request and its answer, a health report, a metrics sample, an error. `contracts/` is the one small package that holds those shapes and nothing else: no business rules and no service internals. Every service imports it, so they all speak the same language.

- It defines the event envelope (what the agents send the gateway, with its ID and per-source order), the approval request and answer, health and readiness reports, the metrics sample, the problem format for errors, and the constants of the pause and resume extension.
- `contracts/schemas/` holds a JSON Schema of every message. A test compares each message with its committed schema, so a message cannot change by accident. After an intended, versioned change, regenerate them with `THURSDAY_UPDATE_SCHEMAS=1 uv run pytest contracts` and commit the result.
- Breaking changes need a new `schema_version` (events), a new extension URI, or a new REST prefix, as set out in [docs/CONTRACTS.md](docs/CONTRACTS.md), which also describes how the services use these messages.

### Created on your machine, not in the repository

| Path | What it is |
|---|---|
| `.env` | Your settings and the service token (from `.env.example`). No API keys |
| Windows Credential Manager, entries for `Thursday` | The API keys typed in Settings |
| `.venv/` | Python environment made by `uv sync` |
| `apps/dashboard/node_modules/`, `apps/dashboard/dist/` | Dashboard dependencies and the built dashboard the gateway serves |
| `apps/android/app/build/`, `apps/android/.gradle/` | Android build output |
| `apps/android/keystore.properties`, `apps/android/*.jks` | The key that signs the Android app: keep it safe and backed up |
| `%LOCALAPPDATA%\Thursday\` | Databases, logs, the built-in llama.cpp, and downloaded speech models (or `THURSDAY_DATA_DIR`) |

## Documentation

- [Design documents](docs/README.md)
- [Operations: setting up, updating, backing up, and troubleshooting](docs/OPERATIONS.md)

## License

Apache License 2.0; see [LICENSE](LICENSE).
