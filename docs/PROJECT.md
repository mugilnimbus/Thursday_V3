# Thursday: Project Intention and Behavior

## Purpose and intended use

Thursday is a personal agent harness that runs on your own PC. Two always-on LLM agents cooperate:

- The **voice agent** is the conversational front. It listens to short, step-by-step instructions, answers quickly, and delegates work.
- The **main agent** has all the tools. It carries out delegated tasks on the PC through MCP tool servers and reports progress, questions, and results.

The two agents talk over the A2A protocol and each keeps its own stateful context per chat. A gateway gives a web dashboard on the PC and a native Android app (over Tailscale) the same functionality. The primary user is the project owner; the project is public, so nothing may depend on one person's machine or accounts.

Success looks like this: you type or say a short instruction, it happens on your PC, you can see exactly what is happening live, you approve risky steps with one tap, and you are told the result. You can do all of this from the PC or from your phone.

## Scope

The system has four parts:

1. **PC only:** gateway, voice agent, main agent, built-in tool server, metrics collector, web dashboard, chat input.
2. **PC plus Android app**, reached over Tailscale, including notifications.
3. **Voice ladder:** audio input with text output, then local speech-to-text and text-to-speech, then a full audio model that listens continuously. Today: push-to-talk with local speech-to-text (Whisper) and replies read aloud (Kokoro), on the dashboard and the phone. A built-in llama.cpp model that can hear writes down the recording itself, with Whisper as the fallback (LM Studio does not accept audio). Continuous listening, and answering the audio in one step, are not part of it.
4. **Model hosting and hardware control:** each agent chooses LM Studio, the built-in llama.cpp, or an OpenAI-compatible endpoint; nothing loads at start; models load and unload on request. It includes the three providers, the settings on both clients, key storage, the llama.cpp installer, unloading a model that has been idle (five minutes by default, per agent), cleaning up a model server an agent left behind, and splitting a model across graphics cards by layer.

Out of scope for version 1: multiple user accounts, hosted or cloud deployment of the harness, macOS or Linux support (possible later), and cloud push services such as FCM.

## Important feature behavior

**Projects and chats.** A project is a workspace folder. Each project holds many chats. Each chat has its own voice context and its own main-agent context, so chats never leak into each other. Chat and task history can be searched and deleted. Deleting a chat or project removes its data from every service.

**Delegation.** The voice agent turns your instruction into an A2A task for the main agent and then returns to conversation. You can talk to the voice agent about something else, or ask it questions, while a task runs. To change a running task you stop it and send a new instruction in the same context.

**Direct mode.** A chat can send its messages straight to the main agent, word for word, skipping the voice agent: a switch beside Send, or a right-click (dashboard) or long-press (app) on Send. The voice agent still reports the result in a sentence or two, without being able to start anything, and code falls back to the main agent's own words if that report cannot be trusted. The switch is kept on the PC, so every device agrees.

**Live visibility.** A chat shows, for each delegated task, a card with a status dot that opens into its steps: what was delegated, each LLM call, each tool call (shown the moment it is requested, purple and pulsing, then green or red), approvals, and the result. A stats strip shows tokens per second and context window use for each agent. The Trace screen holds the full detail.

**Voice presence.** Behind the messages a field of particles shows what the voice agent is doing: a line along the bottom that drifts as if in a breeze and pulses with sound, and a face made of particles that gathers while the agent listens, thinks, and speaks. The face can be switched off; the line stays.

**Approvals.** Risky tool calls (shell commands and deletes in the built-in server) ask you first, as a card in the chat with allow once, allow always, or deny. Allow always applies only inside that chat. If you do not answer within 300 seconds, the request is cancelled and the main agent is told the user did not respond; it may try a different approach. After two such timeouts in a row the task pauses and you are notified. The gateway raises an immediate plain notification for every approval request, and the voice agent then also says it.

**Task control.** You can pause, resume, or stop a task from the UI or by asking the voice agent. Pause takes effect after the current step finishes (a step is one LLM call plus its tool calls). Stop cancels immediately, including a running tool.

**Notifications.** The Android app keeps a connection over Tailscale and shows notifications for approvals and finished tasks, also with the phone locked.

**Phone.** The app pairs by scanning a QR code from the dashboard, and then does what the dashboard does: chats, approvals, task control, trace, tools, monitor, settings, making projects, and browsing and reading a project's files. Settings changes ask for the phone's fingerprint or PIN, and so does pressing Allow on an approval unless that check is turned off in the app's settings.

**Failures.** If the LLM endpoint is down, a banner shows and your messages queue. A running task retries the LLM call three times with increasing delays and then fails with a notification. If the main agent restarts mid-task it resumes from its last checkpoint; a tool call that had started but has no result is reported to the model as "outcome unknown, verify first" and is never blindly re-run.

**Model providers and loading.** Each agent has its own provider: LM Studio, the built-in llama.cpp (Thursday starts it for a `.gguf` file from a folder you choose, and stops it on unload), or a generic OpenAI-compatible endpoint (a cloud provider, or a llama.cpp server you run yourself). The model is picked from the provider's list. Providers that Thursday can load show load settings with load, unload, and reload; an already-loaded LM Studio model is adopted as is. Every provider shows answer settings (temperature, top p, output limit, thinking or reasoning effort), offered only as the values it accepts. Nothing is loaded when Thursday starts. Cloud providers show no load settings and are clearly marked as sending data off the PC.

**API keys.** A key is typed in Settings on the dashboard or the phone and kept in the operating system's credential store, one per agent and provider. It is never shown again.

**Context management.** The harness keeps its own transcript as the source of truth and sends the full input on every call (the endpoint's `previous_response_id` chaining is not used). A finished task is kept in the transcript as its instruction, a log of the tools it ran and how each ended, and its final message; the full detail stays in the task trace. When the main agent's context reaches its limit (a token count set per agent, and never later than 90% of the loaded window) older turns are automatically summarized for the model, and a marker appears in the timeline. The voice agent leaves out the oldest messages instead. Tasks run one at a time on the model so they never share its window, and a full window is handled by compacting harder and retrying once.

**Trace.** Each model call's request and response can be read as a conversation (who said what, thinking, tool calls, results), or as stored.

**System prompts.** Each agent has one global system prompt that can be read, edited, and saved in Settings on the dashboard and the app. Versions are kept.

**Monitor.** A Monitor screen shows PC CPU, RAM, VRAM, and network, tokens per second and time to first token for each agent, latency per service, queue loads, and service up/down state. Metrics are kept 7 days (downsampled) by default.

**Retention and backup.** Working data (traces, the saved state of finished tasks, tool call logs) is kept for a period chosen in Settings: 7 days to 1 year, or until you delete it; 30 days by default. Chat history is kept until you delete it. A manual "back up now" and an optional daily backup copy the important data to a folder you choose.

## Choices and reasons

| Choice | Reason |
|---|---|
| Voice and main agents as separate services connected by A2A | A clean protocol boundary; the main agent can be replaced or reused; matches the microservices default |
| Gateway is also an A2A client for pause, stop, and approval answers | Controls must work even when the voice LLM is busy or down |
| Each service owns its data; the gateway holds a read model built from async events | No service waits on another; dashboards read one place |
| Transcript is the source of truth; every call sends its full input | Survives endpoint restarts and works on endpoints without stateful responses |
| Main agent stores allow-always rules; tool server has its own permission logic | Avoids making approvals depend on the gateway |
| Explicit model loading, no reliance on LM Studio JIT | JIT auto-evict keeps only one JIT-loaded model, so two agents would evict each other |
| Native processes with a launcher, no Docker for the harness | The tool server and metrics need the real host filesystem, shell, and GPU |
| Tailscale HTTPS certificates | Standard HTTPS for the app and browsers; accepted that the machine name appears in public certificate logs |
| API keys in the operating system's credential store, typed in Settings, never shown again | No key sits in a plain file; a client can replace a key but never read one. Replaces the earlier "keys only in `.env`" rule |
| PC stays awake while a task runs | A sleeping PC cannot be reached from the phone |
| Three providers per agent, with the built-in llama.cpp as one process per agent | The hardware can be freed while the services keep running; a process that is stopped really releases the GPU, which llama.cpp's own idle sleep does not |
| llama.cpp is downloaded by setup, not chosen as a folder | One less thing to set up; the official build for the PC is picked and checked. `LLAMACPP_DIR` remains for an own build |
| A context limit in tokens per agent, in place of one percentage | A cloud endpoint reports no window, so a percentage could never trigger there |
| Traces store the response, not the token stream | The stream was unreadable and was cut before the answer |
| A model idle for five minutes is unloaded, on every provider Thursday can unload | The hardware is free while the services keep running; the cost is a reload on the next message |
| A hearing model writes the words down first, then answers the text | The chat still shows what was said, and spoken yes or no approvals and direct mode work unchanged; it costs one short extra call |
| Setup asks before downloading llama.cpp | It is 650 MB that someone on LM Studio or a cloud endpoint never needs |
| The shell is not confined to the project folder; approval is its control, with a deny list that approval cannot lift | Real work needs the real shell; the deny list stops the commands that could not be undone or that move files off the PC |
| A stored key goes only to the address it was typed for | Pointing an agent at another server must not hand that server the old one's key |
| Trace bodies are stored as sent, not redacted | A trace has to show what the model really saw; how long it is kept is a setting |
