# Thursday: Project Intention and Behavior

Status: Accepted design (planning complete 2026-09-30). Stages 1 and 2 and the push-to-talk part of stage 3 are built (2026-10-01); see "Agreed scope". Items under "Open questions" are not decided.

## Purpose and intended use

Thursday is a personal agent harness that runs on your own PC. Two always-on LLM agents cooperate:

- The **voice agent** is the conversational front. It listens to short, step-by-step instructions, answers quickly, and delegates work.
- The **main agent** has all the tools. It carries out delegated tasks on the PC through MCP tool servers and reports progress, questions, and results.

The two agents talk over the A2A protocol and each keeps its own stateful context per chat. A gateway gives a web dashboard on the PC and a native Android app (over Tailscale) the same functionality. The primary user is the project owner; the project may later be published on GitHub for others, so nothing may depend on one person's machine or accounts.

Success looks like this: you type or say a short instruction, it happens on your PC, you can see exactly what is happening live, you approve risky steps with one tap, and you are told the result. You can do all of this from the PC or from your phone.

## Agreed scope

The design covers the full system. It is built in stages:

1. **PC only:** gateway, voice agent, main agent, built-in tool server, metrics collector, web dashboard, chat input. Built.
2. **PC plus Android app**, reached over Tailscale, including notifications. Built.
3. **Voice ladder:** audio input with text output, then local speech-to-text and text-to-speech, then a full audio model that listens continuously. Built so far: push-to-talk with local speech-to-text (Whisper) and replies read aloud (Kokoro), on the dashboard and the phone. Not built: continuous listening, and audio straight into the model (the LLM endpoint does not accept audio; spike S5).

Out of scope for version 1: multiple user accounts, hosted or cloud deployment of the harness, macOS or Linux support (possible later), and cloud push services such as FCM.

## Important feature behavior

**Projects and chats.** A project is a workspace folder. Each project holds many chats. Each chat has its own voice context and its own main-agent context, so chats never leak into each other. Chat and task history can be searched and deleted. Deleting a chat or project removes its data from every service.

**Delegation.** The voice agent turns your instruction into an A2A task for the main agent and then returns to conversation. You can talk to the voice agent about something else, or ask it questions, while a task runs. To change a running task you stop it and send a new instruction in the same context.

**Live visibility.** A chat shows, for each delegated task, a card with a status dot that opens into its steps: what was delegated, each LLM call, each tool call, approvals, and the result. A stats strip shows tokens per second and context window use for each agent. The Trace screen holds the full detail.

**Voice presence.** Behind the messages a field of particles shows what the voice agent is doing: a line along the bottom that drifts as if in a breeze and pulses with sound, and a face made of particles that gathers while the agent listens, thinks, and speaks. The face can be switched off; the line stays.

**Approvals.** Risky tool calls (shell commands and deletes in the built-in server) ask you first, as a card in the chat with allow once, allow always, or deny. Allow always applies only inside that chat. If you do not answer within 300 seconds, the request is cancelled and the main agent is told the user did not respond; it may try a different approach. After two such timeouts in a row the task pauses and you are notified. The gateway raises an immediate plain notification for every approval request, and the voice agent then also says it.

**Task control.** You can pause, resume, or stop a task from the UI or by asking the voice agent. Pause takes effect after the current step finishes (a step is one LLM call plus its tool calls). Stop cancels immediately, including a running tool.

**Notifications.** The Android app keeps a connection over Tailscale and shows notifications for approvals and finished tasks, also with the phone locked.

**Phone.** The app pairs by scanning a QR code from the dashboard, and then does what the dashboard does: chats, approvals, task control, trace, tools, monitor, settings, making projects, and browsing and reading a project's files. Risky approvals and settings changes ask for the phone's fingerprint or PIN.

**Failures.** If the LLM endpoint is down, a banner shows and your messages queue. A running task retries the LLM call three times with increasing delays and then fails with a notification. If the main agent restarts mid-task it resumes from its last checkpoint; a tool call that had started but has no result is reported to the model as "outcome unknown, verify first" and is never blindly re-run.

**Model providers and loading.** Each agent has a provider setting: LM Studio or a generic OpenAI-compatible endpoint (including cloud). For LM Studio, the Settings screen shows load parameters (context length and others) with load, unload, and reload. An already-loaded model is adopted as is; otherwise the agent loads it with the configured settings. Cloud providers show no load parameters and are clearly marked as sending data off the PC.

**Context management.** The harness keeps its own full transcript as the source of truth and uses the endpoint's stateful `previous_response_id` only as an optimization. At 90% context use (configurable) older turns are automatically summarized for the model; the full transcript is kept and a marker appears in the timeline.

**System prompts.** Each agent has one global system prompt that can be read, edited, and saved in Settings on the dashboard and the app. Versions are kept.

**Monitor.** A Monitor screen shows PC CPU, RAM, VRAM, and network, tokens per second, latency per service, queue loads, and service up/down state. Metrics are kept 7 days (downsampled) by default.

**Retention and backup.** Traces and logs are kept 30 days; chat history is kept until you delete it. A manual "back up now" and an optional daily backup copy the important data to a folder you choose.

## Accepted choices and reasons

| Choice | Reason |
|---|---|
| Voice and main agents as separate services connected by A2A | A clean protocol boundary; the main agent can be replaced or reused; matches the microservices default |
| Gateway is also an A2A client for pause, stop, and approval answers | Controls must work even when the voice LLM is busy or down |
| Each service owns its data; the gateway holds a read model built from async events | No service waits on another; dashboards read one place |
| Transcript is the source of truth, `previous_response_id` is an optimization | Survives endpoint restarts and works on endpoints without stateful responses |
| Main agent stores allow-always rules; tool server has its own permission logic | Avoids making approvals depend on the gateway |
| Explicit model loading, no reliance on LM Studio JIT | JIT auto-evict keeps only one JIT-loaded model, so two agents would evict each other |
| Native processes with a launcher, no Docker for the harness | The tool server and metrics need the real host filesystem, shell, and GPU |
| Tailscale HTTPS certificates | Standard HTTPS for the app and browsers; accepted that the machine name appears in public certificate logs |
| Keys in `.env`, never written by the UI | No code path lets a phone write secrets to disk |
| PC stays awake while a task runs | A sleeping PC cannot be reached from the phone |

## Open questions

Decided during implementation: the dashboard is Svelte 5; the Android foreground service type is `remoteMessaging`; speech is faster-whisper `small` and Kokoro, both on the CPU.

Still open:

- Final URI for the task-control A2A extension.
- Details of the owner's own MCP server permission logic (owner will provide later).
- Repository visibility and license before publishing, including the licence of the picture the voice field's face was derived from.
- Continuous listening.
