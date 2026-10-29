# Architecture

This page gives the shape of Thursday and the decisions that the rest depends on. The [architecture model](architecture/index.html) holds the detail: every part down to each condition, every line, and 54 journeys from start to end. The model is the source. If this page and the model do not agree, the model is correct.

## The system

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="images/architecture-dark.svg">
  <img alt="Thursday and what is around it: the owner, the dashboard and Android app, model servers, Tailscale, the credential store and download sources" src="images/architecture.svg">
</picture>

Thursday runs on one PC. The owner uses it from a dashboard in a browser on the PC, or from the Android app over the owner's own Tailscale network. Each agent calls a model server: LM Studio, the built-in llama.cpp, or an OpenAI-compatible endpoint. API keys stay in the operating system's credential store. Two downloads happen once: the llama.cpp build at setup, and the speech models at the first use of voice.

## Containers

All services are native processes on localhost. The launcher starts them, checks their health, and restarts a service that stops.

| Container | Responsibility | Owns |
|---|---|---|
| Gateway | The one door for clients: projects, chats, settings, pairing, task control, event ingest, the read model, notifications, file views, the speech relay, backup | Projects, chats, devices (token hashes), the read model, the metrics history, the retention setting |
| Voice agent | Talks with the owner, delegates tasks, reports task updates, recognises a spoken yes or no to an approval in code | Voice transcripts, delegated tasks, its prompt and model settings, its outbox |
| Main agent | Runs tasks: the agent loop, approvals, pause and stop, context, the MCP client | Main transcripts, task checkpoints, allow-always rules, call marks, its prompt and model settings, its outbox |
| Tool server | Runs tools inside the project folder, and asks first for risky ones | Its call and audit log, one file for each project |
| Speech service | Speech to text (faster-whisper) and text to speech (Kokoro), on the CPU | The downloaded speech models. It stores no audio |
| Metrics collector | Reads CPU, RAM, VRAM and network, reads each service's `/metrics`, and sends the readings to the gateway | Readings in memory only |
| Built-in llama.cpp | Serves one model to one agent while that model is loaded | Nothing. The model files are the owner's |
| Launcher | `thursday up`, `down`, `status`, `check` and `setup` | A pid file while it runs, and the installed llama.cpp build |
| Dashboard, Android app | The screens. They read only the gateway | Preferences on each device; on the phone, the device token in the Android Keystore |

Ports, all on localhost: gateway 8700 (dashboard) and 8701 (phone, through Tailscale Serve), voice agent 8710, main agent 8711, metrics collector 8720, speech 8730. Each built-in `llama-server` takes a free port when its model loads.

## The main flow

An instruction that needs an approval goes through these steps. The model shows them as the journey `send_task`, with each branch.

1. The client sends the message to the gateway with a `client_message_id`. The gateway queues the message for the chat.
2. The gateway sends the message to the voice agent as a chat turn. The reply streams back to the client.
3. The voice agent gives the instruction to the main agent as an A2A task, and returns to the conversation.
4. The main agent calls the model, then calls a tool on the project's tool server through MCP.
5. The tool asks first. The main agent saves its step and publishes an approval request.
6. The gateway shows an approval card and a notification, on the dashboard and on the phone.
7. The owner allows the call. The main agent runs it and continues the loop.
8. When the task ends, the main agent tells the voice agent. The voice agent reports the result in the chat.

## Decisions everything depends on

| Decision | Reason | Detail in |
|---|---|---|
| Each service owns its data. No service reads the tables of another service. Clients read only the gateway | A service that is down does not stop the others. The screens read one place | The model, level 2 |
| Agents write events to their own outbox. A sender delivers them to the gateway at least once. The gateway ignores a repeated `event_id` and keeps order by `seq` for each source | An agent never waits on the gateway. A restart loses no event | Journey `event_dropped_or_repeated` |
| The read model is a projection of the events. Each agent can replay its events | The gateway's database can be rebuilt | [API.md](API.md) |
| Only the gateway's relay marks a message delivered. A message that the voice agent did not answer goes back to the queue and is sent again | A message is not lost when the voice agent stops in the middle of a turn | Journey `user_message_after_stop` |
| The main agent saves every step (a LangGraph checkpoint). A pause takes effect between steps | A pause, an approval or a restart continues from the last step | Journey `pause_task` |
| A tool call has a mark for its task, step and position. A finished call is answered from its stored result. A call that started with no result is reported as "outcome unknown" | A tool call runs at most once | Journey `run_again_after_restart` |
| Tasks take turns on the model, one at a time | The tasks share one context window | Journey `send_task` |
| The voice agent is a plain loop with no saved steps. A repeated turn returns its stored reply | A turn is short. Low delay matters more than saved steps | Journey `message_repeated` |
| Risky tools ask first. An answer of "always" applies only to that chat. A shell command on the deny list is refused before anyone is asked | The owner sees every risky step | [SECURITY.md](SECURITY.md) |
| Nothing loads at start. A model loads on Load or on first use, and unloads after an idle time (five minutes by default) | The GPU stays free while Thursday is not in use | Journey `unload_idle_model` |
| Deleting a chat is a saga that repeats until every service confirms. Each agent remembers the deleted chat for a week | No data about the chat stays in any database, and late work cannot write to it | Journey `delete_chat` |

## Inside a service

Each Python service has four layers: transport, application, domain and infrastructure. The application layer reaches a database, another service or a tool server only through the interfaces in its own `application/ports.py`. Only `bootstrap` connects an interface to its adapter. `tests/test_layers.py` reads every import and fails when one points the wrong way.

Both agents use the shared package `packages/llm` for their model provider. The table gives how each provider works.

| Provider | Chat call | Model list | Load and unload |
|---|---|---|---|
| LM Studio | `/v1/responses` | LM Studio's own list | LM Studio's native API |
| Built-in llama.cpp | `/v1/chat/completions` on the agent's own `llama-server` | The `.gguf` files in the chosen folder | The agent starts and stops one `llama-server` process |
| OpenAI-compatible | `/v1/responses` | The endpoint's `/v1/models` | None. The endpoint decides |

A setting change and a model call never overlap. A change that comes while the model answers is refused. The [README](../README.md#models-and-api-keys) lists the settings.

## Data that is kept

- **Chats, messages, transcripts and the task list** stay until the owner deletes them.
- **Working data** is how a task was done: traces, saved steps, delivered events and the tool call log. The owner sets how long it stays: 7 days to 1 year, or until deleted. The default is 30 days. The gateway sends the period to each agent, and each service cleans its own data.
- **Metrics history** is kept every 5 seconds for 24 hours, and once a minute for the retention period.
- **Backups** copy each service's SQLite files into one dated folder. A backup never holds `.env` or API keys. [OPERATIONS.md](OPERATIONS.md) has the steps.

## Runtime

- Every service has its own health and readiness checks, and continues when another service is down. The gateway shows a banner from the second missed readiness check in a row.
- Every service keeps an unused connection open for 30 seconds, longer than the five seconds its callers keep one. With five seconds on both sides, 6 of 40 readiness checks against a test service failed on a connection that was closing.
- The PC stays awake while a task runs or waits for an approval: a power request on Windows, a systemd inhibitor lock on Linux.
- Each service writes JSON-lines logs with rotation, outside the repository. Each line carries the chat, task and event ids.
- The [README benchmark](../README.md#benchmark) gives the measured speed of the gateway, the outbox and the events.

## Technology

| Area | Choice | Reason |
|---|---|---|
| Services | Python 3.12, FastAPI, Pydantic, a `uv` workspace, SQLite for each service | One PC, one owner |
| Main agent | LangChain `ChatOpenAI` and LangGraph | Saved steps, and an approval or a pause that survives a restart |
| Agent protocol | A2A 1.0 (`a2a-sdk`) | An open protocol to give a task to another agent, with push notifications |
| Tools | MCP over stdio (`mcp`) | An open protocol for tools, which can ask the owner during a call |
| Speech | faster-whisper `small` and Kokoro (ONNX), on the CPU | The GPU stays free for the models |
| Dashboard | Svelte 5, Vite, TypeScript, WebGL for the voice field | Static files that the gateway serves |
| Android | Kotlin, Jetpack Compose, OkHttp | A native app keeps a connection and notifies with the phone locked |
| Phone connection | Tailscale Serve in front of port 8701 | HTTPS inside the tailnet only. Nothing is open to the internet |
| API keys | The operating system's credential store, through `keyring` | No key in a file |
