# Contracts and Integrations

Status: Accepted design (2026-09-30), updated to the system as built (2026-10-01). Shapes and field lists are the agreed contract; the exact schemas are in the `contracts` package, guarded by snapshot tests. Flows are in [FLOWS.md](FLOWS.md).

## Boundary overview

| Boundary | Contract | Style | Auth | Timeout, retry, idempotency |
|---|---|---|---|---|
| Client to gateway | REST `/v1` plus one WebSocket | sync plus server push | Device token (bearer); the PC dashboard uses the trusted localhost listener | Clients reconnect with backoff; sends carry `client_message_id`; creates take `Idempotency-Key` |
| Gateway to voice agent | Internal chat API (streaming) | sync stream | Service token | Message queues at the gateway if the voice agent is down |
| Voice agent to main agent | A2A 1.0 `SendMessage` with `returnImmediately` and a push webhook | async | Service token | Push retried a few times; reconcile with `GetTask` and `ListTasks` after restart |
| Gateway to main agent | A2A (`CancelTask`, approval answers), task-control extension, Management API | sync | Service token | Short timeout; safe to repeat |
| Agents to gateway | Event ingest `POST /v1/events` (batched) | async | Service token | At-least-once from the outbox, deduplicated by `event_id` |
| Gateway to speech service | `POST /v1/transcribe`, `POST /v1/speak`, `GET /v1/voices` | sync | Service token | Long timeout for the first use (models load or download); a failure is `503` to the client, typing still works |
| Collector and services | `GET /metrics` (JSON map) scrape, then `POST /v1/metrics` (`MetricsSample`) to the gateway | async | Local only; push needs the service token | Missed scrapes are gaps |
| Main agent to tool server | MCP over stdio, including the input-required retry | sync | Process boundary | Tool timeout, MCP cancellation |
| Agents to LLM endpoint | OpenAI-compatible `/v1/responses`; LM Studio native API for model lifecycle | sync stream | API key from `.env` | Three retries with increasing delay |

Versioning: REST prefix `/v1`, `schema_version` on every event, A2A 1.0, a versioned extension URI, MCP version negotiation. Only the gateway is reachable from the tailnet; all other services bind to localhost.

## A2A usage

- The main agent is an A2A server with an Agent Card; the voice agent and the gateway are A2A clients.
- Each new instruction is a new task in the chat's `contextId`. Finished tasks cannot accept further messages (the protocol returns an unsupported-operation error), so amending a running task means stopping it and sending a new task.
- The voice agent sends with `returnImmediately` and a task push-notification config. The main agent pushes on terminal states and on `INPUT_REQUIRED` and `AUTH_REQUIRED`. Push payloads carry a short summary message; full output travels as artifacts and is fetched with `GetTask`.
- Approval answers continue an `INPUT_REQUIRED` task with a message carrying the same `taskId` and `contextId` and a data part `{approval_id, decision: allow_once | allow_always | deny}`.
- **Task-control extension** (versioned URI, placeholder): declared in the Agent Card, activated with the `A2A-Extensions` header. Adds `PauseTask` and `ResumeTask` (both repeatable; errors on finished tasks). The task stays `WORKING` with a metadata flag `none | pausing | paused`. Stop is the standard `CancelTask`.

Implementation details of this contract (as built):

- Transport is JSON-RPC at `POST /a2a` on the main agent, with `Authorization: Bearer <service token>` and `A2A-Version: 1.0` (a missing version header is treated as 0.3 and refused).
- A new task's message carries `contextId` = chat id and metadata `thursday.project_id` and `thursday.project_folder` (an existing absolute folder). The voice agent's code sets these from the gateway request; the model never does.
- The approval request is a data part `{kind: "thursday.approval_request", approval_id, task_id, chat_id, tool, summary, arguments, expires_at}` on the `INPUT_REQUIRED` status message. The answer is a data part `{kind: "thursday.approval_answer", approval_id, decision}`, with optional metadata `thursday.answered_by`.
- JSON-RPC errors: `-32041` approval already resolved, `-32040` task not pausable (extension), `-32004` a text message to a running task, `-32602` missing project metadata or a forbidden part, `-32601` extension not activated, `-32001` task or approval not found.
- Pushes go only to the voice agent's `POST /v1/push`, checked with the per-task `X-A2A-Notification-Token` that the voice agent chose.

## Gateway to voice agent (internal chat API)

- `POST /v1/chats/{chat_id}/turns` with the service token and `{client_message_id, text, project_id, project_folder}`. The reply streams as NDJSON lines: `{"type": "delta", "text"}`, then `{"type": "done", "text"}`, or `{"type": "error", "message"}`.
- Idempotent on `client_message_id`: a repeated turn returns the stored reply without calling the model.
- `503` when the voice model endpoint is unreachable, so the gateway keeps the message queued and retries.
- `DELETE /v1/chats/{chat_id}` (delete saga participant, repeatable). Replay (`GET /v1/replay?after=`) and prompts (`GET`/`PUT /v1/prompt`) use the service token.
- Spoken approvals are recognised by code only while an approval is pending and only for a whole-message phrase (for example "yes", "allow always", "no"); the voice model has no approval tool.

## Event envelope

Every service sends events to the gateway in this shape:

- `event_id` (unique, used for deduplication) and `schema_version`
- `source` (`voice`, `main`, `collector`, `tool`), `seq` (per-source counter for ordering and gap detection), `ts`
- `project_id`, `chat_id`, optional `task_id` (project and chat are absent only for global events such as a model load)
- `type`: user message, assistant message (voice agent replies, including spoken task updates), delegation, LLM call, tool call, approval requested, approval resolved, task state, compaction, model load, notification, error
- `payload`: JSON specific to the type

Delivery is at-least-once with per-source ordering. Large bodies (full LLM requests and responses, tool output) are size-capped and marked truncated. Bodies are stored; headers are never stored.

Tool-call events carry a `status`: `requested` (the model asked for it), `running` (the executing call starts after approval), then `ok`, `error`, or `unknown` (the call started before a restart and its result was lost). Each agent serves its own events for rebuilds at `GET /v1/replay?after=<seq>` (service token).

## Client REST and WebSocket

All under `/v1` with `Authorization: Bearer <device token>`, except pairing claim.

| Group | Operations |
|---|---|
| Projects | List, create; read, rename, change folder, delete (gateway checks the folder exists) |
| Chats | List and create per project; read, rename, delete; page through messages; search across chats |
| Sending | `POST` a message with `client_message_id`; returns `202` (delivered or queued); the reply arrives on the WebSocket |
| Tasks and trace | Timeline after an event number; task with its trace (LLM request and response logs, tool call logs); pause, resume, stop |
| Approvals | List pending; answer with `allow_once`, `allow_always`, or `deny` |
| Tools | Tool server status per project; list and revoke a chat's allow-always rules |
| Monitor | `GET /v1/monitor?range=15m|1h|24h|7d` (latest and history); live values on `/v1/metrics/stream`, opened only while Monitor is visible |
| Settings | Provider, endpoint, model, load parameters, compaction threshold, voice mode; system prompt read and write with versions; model load, unload, reload and state; API key status only (never values); backup now and backup schedule (`POST /v1/backup`, `GET`/`PUT /v1/settings/backup`) |
| Devices | Create a pairing code (localhost listener only); claim a code; list and revoke devices (details below) |

**WebSocket** (`/v1/stream?after=<n>`, optional `chat_id`), server to client only; actions use REST. Message kinds: `catalog_changed` (a project or chat was created, renamed, or deleted; clients reload their lists), `chat_delta`, `timeline_event`, `task_state`, `approval_requested`, `approval_resolved`, `notification`, `metrics`, `status_banner`, plus `outgoing` (queued, delivered, or failed state of a sent message). Messages from stored events carry `pos`, the gateway's event position; on reconnect the client passes the last `pos` seen and the gateway replays what was missed. A client that falls too far behind is disconnected (close code 1013) and reconnects with its cursor. `GET /v1/status` includes `stream_pos`, the newest position, so a client that loads its screens over REST can join the stream from there.

Messages returned by `GET /v1/chats/{id}/messages` carry `pos`, the position of the event that stored them, so a client can merge stored and live messages without showing one twice.

**Folders and files (read-only).** `GET /v1/fs/folders?path=` lists the sub-folders of an absolute folder on the PC (names only; an empty path lists the drives) so a client can pick a project folder. `GET /v1/projects/{id}/files?path=` lists a folder inside the project, and with `q=` searches file and folder names in the whole project (dependency and build folders skipped; at most 200 results). `GET /v1/projects/{id}/file?path=` returns `{text, size, truncated, binary}` for the first 200 kB of a text file. Project paths are resolved, including links, and anything outside the project folder is refused with `422`.

**Deleting.** Deleting a chat or project removes every record of it from every service; only the folder on disk is left alone. The gateway first stops the chat's running tasks, then asks the main agent (`DELETE /v1/chats/{id}`, and `DELETE /v1/projects/{id}` for a project) and the voice agent (`DELETE /v1/chats/{id}`) to delete, repeating until each confirms, then purges its own rows. The main agent removes tasks, approvals, allow-always rules, call marks, transcript, chat summary, LangGraph checkpoints, A2A task and push records, and the chat's events in its outbox; for a project it also stops the tool server and removes the project's tool audit log. The voice agent removes transcript, task records, turn records, and the chat's outbox events. The gateway refuses events that arrive later for a deleted chat or project (they are acknowledged so the sender moves on, and not stored), and at start removes rows whose chat or project no longer exists.

**Pairing.** `POST /v1/devices/pairing` (localhost listener only) returns `{code, expires_at, address, pairing_uri}`: an 8-character code shown as `ABCD-EFGH` (no 0/O or 1/I), valid once for five minutes; a new code replaces the previous one. `address` is this PC's tailnet HTTPS URL (`GATEWAY_PUBLIC_URL`, else read from `tailscale status`); `pairing_uri` is `thursday://pair?url=<address>&code=<code>`, the text a QR code will carry. `POST /v1/devices/claim {code, name}` needs no token and returns `201 {device_id, token}`; the token is shown once and only its SHA-256 hash is stored. A wrong or expired code is `422`; after 5 failed claims in a minute every claim is `429 rate_limited` with `Retry-After: 60`, and 10 failures burn the current code. `GET /v1/devices` lists `{device_id, name, created_at, last_seen}`; `DELETE /v1/devices/{id}` revokes at once: the token stops working and the device's open WebSockets close with code 1008.

**Speech.** `GET /v1/speech` returns `{available, voices}`. `POST /v1/speech/transcribe` takes the recorded audio as the request body (webm, m4a, or wav; at most 15 MB) and returns `{text, language, audio_seconds, seconds}`. `POST /v1/speech/speak {text, voice?}` returns WAV audio (24 kHz, 16-bit, mono); markdown marks are removed and long text is cut at a sentence near 2000 characters. The gateway forwards these to the local speech service with the service token and stores no audio. The client sends the transcribed text as a normal chat message, so delegation, spoken yes/no approvals, and the timeline are unchanged. `503` when the speech service is not running or a model cannot load; `422` for an empty recording or an unknown voice.

Event ingest (`POST /v1/events`, service token) is served only on the localhost listener.

**Errors** use `application/problem+json` with a stable `code`: `401` unauthenticated, `404`, `409` (approval already resolved, task not pausable), `422` invalid input, `429` rate limited (pairing claims), `503` with the reason when a dependency is down.

## MCP contract (main agent and tool server)

- The LLM never calls the tool server. It names a tool and arguments; the main agent (MCP client) sends `tools/call` and returns the result to the model.
- When a tool needs approval the server returns an input-required result containing an elicitation request (a yes or no form) and a `requestState`. The client asks the user and retries the same call with the answer and `requestState`. The user's answer is `accept`, `decline`, or `cancel`; a 300 second timeout is reported as `cancel` ("user did not respond"), a refusal as `decline`.
- The project folder is passed to the server as its root (MCP roots; verified in spike S2).
- MCP has no session concept: the shell session tool returns an explicit session handle and takes it on later calls. Handles are lost if the server process stops, so the main agent does not stop a server with an open session.
- Tool results with `isError` go to the model so it can correct itself.
- The server enforces the workspace sandbox and the permission policy itself; nothing in a prompt can widen them. Allow-always rules are kept by the main agent, keyed by chat, and answer repeat requests.

## LLM endpoint contract

- Chat uses `/v1/responses` with streaming. The harness keeps its own transcript; `previous_response_id` is an optimization and the chain is rebuilt from the transcript when it is lost or after compaction.
- Token counts come from standard usage (input, output, cached, and reasoning tokens). Time to first token and tokens per second are measured by the harness from its own stream timing, so they work for every provider. Context window comes from the LM Studio provider and shows as unknown otherwise.
- **Provider interface:** LM Studio provider (chat, list models, load with `context_length`, `flash_attention`, `offload_kv_cache_to_gpu`, `eval_batch_size`, `num_experts`, unload, loaded context length, speed stats) and generic OpenAI-compatible provider (chat only).
- Model loading is explicit (adopt a loaded model or load with configured parameters). JIT loading is not relied on.
- Raw request and response bodies are kept for traces; `Authorization` and other headers never are.

## External integrations: verified findings and mismatches

| System | Verified | Mismatch or unknown | Handling |
|---|---|---|---|
| LM Studio REST and OpenAI-compatible API | Spike S4 (2026-09-30): `/v1/responses` stateful and streaming with standard Responses events; `POST /api/v1/models/load` applies the load parameters above; `GET /api/v1/models` returns `max_context_length` and each loaded instance's config; reasoning arrives as standard `reasoning` output items; usage includes cached and reasoning tokens | No speed stats in `/v1/responses` (only the native chat API has them); loading an already-loaded model creates a second instance; JIT loading is on by default and loads unloaded models silently with a 10 minute TTL; no audio documented | Measure speed from the stream; adopt checks loaded instances before loading; explicit loading only; audio decided by spike S5 |
| A2A protocol | Version 1.0; extensions are declared in the Agent Card, activated by a header, carry data in metadata, and can add methods; `returnImmediately` and push config exist; finished tasks reject new messages (verified in spike S1) | Push docs recommend HTTPS webhooks and SSRF checks | The SDK's URL screening is opt-in; our localhost webhook is accepted |
| `a2a-sdk` (Python) | Spike S1 (version 1.2.1): server with SQLite task and push-config stores that survive restarts, `returnImmediately`, localhost push with a notification token, `INPUT_REQUIRED` continuation with a data part, `CancelTask` | Pushes every state change; task stores are scoped by caller identity; a task running at a crash stays `WORKING` (the SDK does not resume it); custom JSON-RPC methods are not pluggable | Filter pushes to terminal and input states; one owner scope for the single-owner system; the main agent reconciles open tasks at startup; `PauseTask`/`ResumeTask` served by a thin wrapper in front of the SDK dispatcher |
| MCP | Spec 2026-07-28 multi round-trip elicitation (input-required result, client retries with `inputResponses` and `requestState`); accept, decline, and cancel are distinct (verified in spike S2) | `requestState` is sealed by the server with a per-process key, so it does not survive a tool-server restart | After a restart the main agent re-issues the call and answers from its stored decision (nothing runs before approval) |
| `mcp` Python SDK | Spike S2 (version 2.2.0): negotiates 2026-07-28 over stdio; manual input-required driving (`allow_input_required=True`); roots; client cancellation reaches the tool and its child process is killed | The client must register an elicitation callback to declare the capability | Register a guard callback; process-tree kill for shell commands on Windows |
| LangChain `ChatOpenAI` | Spike S3 (version 1.6.7): Responses API on LM Studio; reasoning items kept and sent back with function calls; `use_previous_response_id`; tool calls; usage; raw request and response bodies captured through an httpx transport wrapper (bodies only) | Its stream folds reasoning into one chunk | Live reasoning deltas, if wanted, come from the captured raw stream |
| LangGraph | Spike S3 (version 1.2.12): SQLite checkpoints; `interrupt()` and `Command(resume=...)` survive a process restart; step-level pause via an interrupt at the start of the LLM step; stop by task cancellation | A resume value is lost if the process dies inside the tool step; provider tool-call IDs are not unique across endpoint restarts | Approvals and call-started marks live in the main agent's own store, keyed by our own IDs; dangling tool calls get a canceled result after stop |
| Tailscale | Node-to-node traffic is end-to-end encrypted; HTTPS certificates need MagicDNS and an admin toggle, renew every 90 days, and machine names appear in public certificate transparency logs. As built: `tailscale serve --bg http://127.0.0.1:8701` forwards REST and WebSocket traffic from the phone to the proxy listener | Certificate renewal over months not observed yet | The dashboard reads this PC's tailnet address from `tailscale status`; `GATEWAY_PUBLIC_URL` overrides it |
| Android background connection | From Android 14 each foreground service declares a type; `dataSync` is capped at 6 hours per 24 on Android 15. As built: a foreground service of type `remoteMessaging` keeps the WebSocket; approvals and finished tasks notify with the phone locked (checked on one Android 15 phone) | Long-run behaviour under OEM battery limits not measured | "Stay connected" can be turned off; the app shows "PC unreachable" and replays missed events when it reconnects |
| Audio into the model, spike S5 (2026-10-01) | LM Studio rejects audio parts on `/v1/chat/completions`, `/v1/responses`, and its native `/api/v1/chat` (only text and images are accepted); Gemma 4 models are listed with vision but no audio capability | Audio in through LM Studio is not possible today | Speech-to-text in front of the text model |
| faster-whisper and Kokoro (2026-10-01) | Whisper `small` (int8) and Kokoro (ONNX) both run on the CPU fast enough for push-to-talk; models download on first use (about 0.5 GB and 0.35 GB) | faster-whisper needs PyAV below version 17 | The version is pinned; the first transcription or reply after a start is slower while a model loads |

## Compatibility and change

Supported: A2A 1.0, MCP 2026-07-28 and earlier as negotiated, LM Studio as verified at implementation time. Breaking changes to events use a new `schema_version`; to the extension a new URI; to REST a new prefix. Contracts are verified by consumer and provider contract tests in the contracts package. No real keys, tokens, or private endpoints appear in this page.
