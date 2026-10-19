// The architecture model. This is the only file edited for a project: index.html, viewer.js and
// viewer.css draw whatever is written here. After every edit run:  node check.mjs
//
// PARTS (elements)
//   { id, kind, name, headline, lane, card, children }
//   id        short, lowercase, unique among its siblings. The full id is the dotted path: mcp.gate.ask
//   kind      actor | service | interface | queue | policy | pool | batcher | database | component | ui | hardware
//   name      what is written on the box
//   headline  one line under the name: the most important rule or number
//   lane      leave out for parts on the main data-flow line (ordered left to right by their connections).
//             'top' | 'bottom' | 'left' | 'right' places a part on that side instead.
//             Usual placing: the UI and its users on top, whatever calls the system on the left,
//             hardware and outside services on the right, monitoring below.
//   children  the parts inside this one. Keep opening a part until nothing inside it is still a decision.
//   card      does      what it is responsible for, one sentence
//             rules     list of rules and numbers ("4 slots", "waits 300 s then returns not_run")
//             decision  what was chosen            why  the reason
//             rejected  list of options that were turned down, each with its reason
//             failure   what happens when it goes wrong
//             exposes   what it reports (metrics, logs)
//             status    accepted | open | revisit   question  what is undecided (required for open and revisit)
//
// CONNECTIONS (edges)
//   { from, to, label, kind, async, card }
//   from, to  full ids. Name the innermost parts; the diagram folds a connection up to whichever box is open.
//   label     what travels
//   kind      the category. Every connection has exactly one:
//               data     (default) the thing being processed moves along it
//               control  a signal with no payload: a trigger, a check, an acknowledgement, a kill
//               result   the answer on its way back
//               error    a refusal or failure path
//               store    written to or read from something that persists
//               monitor  metrics and logs
//               ui       data a person sees in the UI
//               config   a setting a person can change
//   async     true when the sender hands off and does not wait for an answer (drawn dashed)
//   card      carries, mode, timeout, retry: the contract for this connection
//
// FLOWS
//   { id, name, steps: [{ at, note }] }   one request followed through the system, a part at a time.
//   Each step should have a connection from the step before it.
//
// To add a part: add it to its parent's children, connect it, run the check.
// To change a decision: edit the card, set status to revisit on every part the change touches, run the check.
window.ARCH_MODEL = {
 "name": "Thursday",
 "note": "A personal agent harness on your own PC: a quick voice agent hands work to a main agent with tools, and a dashboard and a phone app show everything live.",
 "elements": [
  {
   "id": "person",
   "kind": "actor",
   "name": "You",
   "headline": "On the PC or the phone",
   "lane": "top",
   "card": {
    "does": "Types or says an instruction, approves risky steps, watches the result.",
    "status": "accepted"
   }
  },
  {
   "id": "ui",
   "kind": "ui",
   "name": "Dashboard and Android app",
   "headline": "Two clients, one API",
   "lane": "top",
   "card": {
    "does": "What a person sees and changes, on the PC in a browser and on the phone. Both talk to the gateway only.",
    "status": "accepted"
   },
   "children": [
    {
     "id": "chat",
     "kind": "ui",
     "name": "Chat",
     "headline": "Messages, task cards, voice",
     "card": {
      "does": "Send a message by typing or talking, follow each task live, hear replies.",
      "rules": [
       "A message carries an id made by the client; sending it again is the same message",
       "Stored history over REST, everything newer from the stream, merged by event position",
       "Push-to-talk recording stops by itself at 2 minutes"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "approvals",
     "kind": "ui",
     "name": "Approvals",
     "headline": "Allow once, allow always, deny",
     "card": {
      "does": "Answer a risky step.",
      "rules": [
       "The first answer wins; a later one is told it was already answered",
       "On the phone, Allow can ask for the fingerprint first (a setting of the device, on by default)"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "trace",
     "kind": "ui",
     "name": "Trace",
     "headline": "Every step of every task",
     "card": {
      "does": "Read what a task did: each model call, tool call, approval and the result.",
      "rules": [
       "A very long task shows its start and its end and says how many events were left out"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "tools",
     "kind": "ui",
     "name": "Tools",
     "headline": "Tool servers and allow-always rules",
     "card": {
      "does": "See the tool servers and take back an allow-always rule.",
      "rules": [
       "An allow-always rule belongs to one chat and one tool"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "monitor",
     "kind": "ui",
     "name": "Monitor",
     "headline": "Hardware, speed, services",
     "card": {
      "does": "See CPU, RAM, VRAM, network, tokens per second, time to first token, queue loads and which services are up.",
      "rules": [
       "Live values stream only while the screen is open"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "settings",
     "kind": "ui",
     "name": "Settings",
     "headline": "Models, prompts, retention, backup, devices",
     "card": {
      "does": "Change each agent's provider, model and settings, the system prompts, how long data is kept, backups, and paired devices.",
      "rules": [
       "A change to a model in use is refused with the reason and can be made again when it has finished",
       "On the phone every settings change asks for the fingerprint or PIN"
      ],
      "status": "accepted"
     }
    }
   ]
  },
  {
   "id": "gateway",
   "kind": "service",
   "name": "Gateway",
   "headline": "The one door for clients; owns the read model",
   "card": {
    "does": "Everything a client asks goes through here: projects, chats, sending, task control, settings, pairing, and the live stream.",
    "exposes": "/health, /ready, /metrics; JSON-lines log",
    "status": "accepted"
   },
   "children": [
    {
     "id": "doors",
     "kind": "interface",
     "name": "Two listeners",
     "headline": "Localhost is trusted, the tailnet needs a device token",
     "card": {
      "does": "Accepts client requests.",
      "rules": [
       "Localhost listener: the dashboard on the PC, no pairing; Host and Origin must be its own, writes need a client header",
       "Tailnet listener behind Tailscale Serve: a device token on every call except claiming a pairing code",
       "A pairing code is 8 characters, valid once for 5 minutes, and can only be made on the localhost listener",
       "A proxied request can never reach the localhost listener"
      ],
      "decision": "Two listeners in place of one with rules",
      "why": "Which door a request came through cannot be forged by a header.",
      "failure": "401 without a valid token; 403 for a browser request from another origin.",
      "status": "accepted"
     }
    },
    {
     "id": "relay",
     "kind": "queue",
     "name": "Message relay",
     "headline": "One message at a time, queued while the voice agent is down",
     "card": {
      "does": "Takes a sent message and delivers it to the voice agent in order.",
      "rules": [
       "Idempotent on chat and client message id",
       "Retries with a delay doubling from 1 s to 30 s while the voice agent is unreachable",
       "A failed message that is sent again is queued again",
       "Nothing is sent into a chat that is not active; its waiting messages fail with 'The chat was deleted.'",
       "Direct mode sends the words straight to the main agent through the voice agent's direct route"
      ],
      "decision": "Queue in the gateway's own database",
      "why": "The person's message is safe the moment it is accepted, whatever is down.",
      "failure": "Refused by the agent: the message is marked failed with the reason and can be sent again.",
      "exposes": "Queue length on /metrics and in the status banner",
      "status": "accepted"
     }
    },
    {
     "id": "control",
     "kind": "component",
     "name": "Task control",
     "headline": "Pause, resume, stop, approval answers",
     "card": {
      "does": "Sends a person's control of a task to the main agent.",
      "rules": [
       "Works when the voice model is busy or down: the gateway is its own A2A client",
       "Pause takes effect after the current step; stop cancels at once, a running tool included",
       "An approval answer that arrives second gets 409"
      ],
      "decision": "Gateway talks to the main agent directly for control",
      "why": "Controls must work even when the voice agent cannot.",
      "status": "accepted"
     }
    },
    {
     "id": "ingest",
     "kind": "component",
     "name": "Event ingest",
     "headline": "Dedupes by event id, keeps each source in order",
     "card": {
      "does": "Receives events from the agents and the tool calls they report.",
      "rules": [
       "Deduplicates by event_id; orders by seq per source",
       "Drops an event for a chat that is deleted or being deleted",
       "Raises the plain approval notification itself, without waiting for the voice agent"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "read",
     "kind": "database",
     "name": "Read model",
     "headline": "A projection that can be rebuilt",
     "card": {
      "does": "Holds what clients read: timeline, messages, tasks, approvals, notifications, metrics history.",
      "rules": [
       "Clients read only this; no client reads an agent",
       "Can be rebuilt from each agent's replay",
       "A task's trace returns at most 2,000 events: the first and the last half, with the number left out",
       "Search matches text as typed, Windows paths included",
       "Working data is kept 30 days by default (7 days to 1 year, or until deleted); chat history until deleted"
      ],
      "decision": "One read model in the gateway",
      "why": "Dashboards read one place, and no service waits on another.",
      "rejected": [
       "Clients query each agent: every screen would depend on every service being up"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "hub",
     "kind": "interface",
     "name": "Live stream",
     "headline": "One WebSocket, replay from a cursor",
     "card": {
      "does": "Pushes stored events and passing messages (reply text, sending state) to clients.",
      "rules": [
       "A client joins at the position /v1/status gave it and replays what it missed",
       "Reply text streams as passing messages that are not stored"
      ],
      "failure": "A client reconnects with a delay doubling from 1 s to 30 s and catches up from its cursor.",
      "status": "accepted"
     }
    },
    {
     "id": "lifecycle",
     "kind": "component",
     "name": "Projects, chats and deletion",
     "headline": "Deleting removes it from every service",
     "card": {
      "does": "Creates projects and chats, and deletes them everywhere.",
      "rules": [
       "Delete: stop the chat's tasks, mark it deleting and fail its waiting messages in one step, ask each service (repeatable), then remove own records",
       "Retries until every service confirms",
       "The project folder on disk is never touched"
      ],
      "decision": "A repeatable saga",
      "why": "Any service may be down in the middle; asking again must finish the job, never start it twice.",
      "status": "accepted"
     }
    },
    {
     "id": "status",
     "kind": "component",
     "name": "Dependency status",
     "headline": "An agent counts as down from the second miss",
     "card": {
      "does": "Tells clients which parts are up.",
      "rules": [
       "Readiness is asked every 5 seconds",
       "One missed check shows nothing; two in a row raise the banner",
       "Services keep an unused connection for 30 seconds, longer than any caller does"
      ],
      "decision": "Two misses, and a longer keep-alive",
      "why": "A check that landed on a connection the agent had just closed raised a false 'not running' banner.",
      "status": "accepted"
     }
    },
    {
     "id": "keep",
     "kind": "component",
     "name": "Retention and backup",
     "headline": "One retention setting; backup is chats and projects",
     "card": {
      "does": "Cleans old working data and copies the databases on request.",
      "rules": [
       "Owns the retention setting and sends it to each agent until each confirms",
       "A backup is a timestamped folder with a manifest; complete when every service copied its chats and projects",
       "Keeps the newest 7 copies by default, and never removes the newest complete one",
       "Monitor history and tool call logs are not in a backup; .env and API keys never are"
      ],
      "decision": "Backup holds chats and projects only",
      "why": "That is what cannot be made again; the rest is working data.",
      "question": "Restoring from a backup has not been tried end to end.",
      "status": "open"
     }
    }
   ]
  },
  {
   "id": "voice",
   "kind": "service",
   "name": "Voice agent",
   "headline": "The quick conversational front; delegates the work",
   "card": {
    "does": "Answers quickly, turns an instruction into a task for the main agent, and tells the person how it went.",
    "exposes": "/health, /ready, /metrics",
    "status": "accepted"
   },
   "children": [
    {
     "id": "turn",
     "kind": "component",
     "name": "Conversation turn",
     "headline": "Short, plain loop; a repeated turn returns its stored reply",
     "card": {
      "does": "Runs one message through the voice model and streams the reply.",
      "rules": [
       "Idempotent on the client message id",
       "The model sees at most the last 60 messages, fewer when a context limit is set",
       "The window moves forward 20 messages at a time so the model server can reuse its work",
       "A turn or direct message for a deleted chat is refused with 410"
      ],
      "decision": "A plain loop without saved steps",
      "why": "A turn is short; a repeated turn is answered from the stored reply.",
      "rejected": [
       "The same checkpointed graph as the main agent: latency for no benefit"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "yes",
     "kind": "policy",
     "name": "Spoken approval",
     "headline": "Recognised in code, never by the model",
     "card": {
      "does": "Answers a waiting approval from a typed or spoken yes or no.",
      "rules": [
       "Only a whole-message phrase counts ('yes', 'allow always', 'no', ...)",
       "Only while an approval is waiting in that chat",
       "The voice model has no approval tool"
      ],
      "decision": "Code decides, not the model",
      "why": "An approval must never come out of model output.",
      "status": "accepted"
     }
    },
    {
     "id": "delegate",
     "kind": "component",
     "name": "Delegation",
     "headline": "A named request: a retry gets the same task",
     "card": {
      "does": "Starts, pauses, resumes and stops tasks on the main agent.",
      "rules": [
       "Each request to start a task has a name worked out from the chat, the message and its position",
       "The push token is worked out from the name, so a repeat carries the same one",
       "A task that is already known is added once and announced once",
       "Any task that has not ended can be chosen for pause, resume or stop, however old it is"
      ],
      "decision": "Named requests",
      "why": "When the main agent's answer is lost, sending again must not start the work twice.",
      "rejected": [
       "A fresh id per attempt: a lost answer created a duplicate task"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "report",
     "kind": "component",
     "name": "Task reports",
     "headline": "Says the result in a sentence or two",
     "card": {
      "does": "Receives task updates from the main agent and puts them into the chat.",
      "rules": [
       "Updates arrive on a push webhook with the task's token",
       "For a direct task the voice model only reports; code falls back to the main agent's own words",
       "A report that finishes after its chat was deleted is dropped"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "store",
     "kind": "database",
     "name": "Voice store",
     "headline": "Transcripts, delegated tasks, prompt versions",
     "card": {
      "does": "Keeps what the voice agent owns.",
      "rules": [
       "SQLite, owned by this service alone",
       "A 'this chat was deleted' note is kept 7 days; nothing is written for that chat again",
       "Versioned forward-only migrations with a backup before each"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "outbox",
     "kind": "queue",
     "name": "Event outbox",
     "headline": "At least once, in order, never waits for the gateway",
     "card": {
      "does": "Holds the voice agent's events until the gateway has them.",
      "rules": [
       "Every event is written to the outbox's own SQLite file first",
       "A background sender delivers in order and retries with backoff",
       "The gateway can ask for 'my events since N' again (replay)",
       "Nothing is stored for a chat that was deleted",
       "Delivered events are removed after the retention period"
      ],
      "decision": "Outbox with a sender",
      "why": "A service must never wait on the gateway to do its own work.",
      "rejected": [
       "Call the gateway directly: an agent would stall whenever the gateway was down"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "llm",
     "kind": "component",
     "name": "Model runtime",
     "headline": "One provider, one model, settings changeable while running",
     "card": {
      "does": "Holds the voice agent's model settings and its provider, and is the only way the agent calls a model.",
      "status": "accepted"
     },
     "children": [
      {
       "id": "settings",
       "kind": "policy",
       "name": "Effective settings",
       "headline": ".env, then saved changes, then the key",
       "card": {
        "does": "Works out the settings in force.",
        "rules": [
         "Starting values come from .env; changes saved from Settings are kept in the agent's own database",
         "The model and the address are remembered per provider: switching provider never carries them over",
         "Load settings apply at the next load; answer settings apply to the next call"
        ],
        "decision": "Each agent owns its settings",
        "why": "An agent keeps working, with the right settings, while the gateway is down.",
        "status": "accepted"
       }
      },
      {
       "id": "busy",
       "kind": "policy",
       "name": "Change guard",
       "headline": "No change while the model is in use",
       "card": {
        "does": "Keeps a settings change and a model call from overlapping.",
        "rules": [
         "A save, a new key, Unload or Reload while a call is running is refused with 409 and the words 'The model is in use right now. Try again when it has finished.'",
         "A call that starts while a change is being applied waits for the change to finish",
         "Nothing is changed by a refused request"
        ],
        "decision": "Refuse, do not queue the change",
        "why": "Rebuilding closes the provider, and for the built-in llama.cpp that stops the server under the running call.",
        "rejected": [
         "Apply the change after the call: the person would not know when it took effect",
         "Let the change through: it killed the model server in the middle of an answer"
        ],
        "status": "accepted"
       }
      },
      {
       "id": "keys",
       "kind": "policy",
       "name": "Key rule",
       "headline": "One key per agent, provider and address",
       "card": {
        "does": "Decides which stored key, if any, goes with a call.",
        "rules": [
         "Keys live in the operating system's credential store, never in a file or a database",
         "A key is stored for one agent and one provider",
         "A key is sent only to the address it was typed for; after the address changes it is held back until typed again",
         "The .env key goes only to the .env provider at the .env address",
         "A key is never returned: clients learn only 'set' or 'held back'"
        ],
        "decision": "Tie the key to its address",
        "why": "Pointing an agent at another server must not hand that server the old one's key.",
        "rejected": [
         "Tie the key to the provider only: a changed address received the stored key"
        ],
        "status": "accepted"
       }
      },
      {
       "id": "idle",
       "kind": "policy",
       "name": "Idle unload",
       "headline": "Unloads after 5 minutes without use",
       "card": {
        "does": "Frees the hardware when nobody is using the model.",
        "rules": [
         "A model counts as in use for the whole of every call, loading included",
         "Default 5 minutes per agent; 0 keeps the model loaded",
         "Checked every 15 seconds",
         "Nothing is loaded when the service starts"
        ],
        "decision": "Unload by the agent, not by the model server",
        "why": "A stopped llama.cpp process really releases the GPU; llama.cpp's own idle sleep does not.",
        "failure": "A failed unload is tried again on the next pass.",
        "status": "accepted"
       }
      },
      {
       "id": "timing",
       "kind": "component",
       "name": "Call timing",
       "headline": "Time to first token and tokens per second",
       "card": {
        "does": "Measures each streamed call.",
        "rules": [
         "Time to first token: from the request to the first piece that carries text or a tool call",
         "Tokens per second: output tokens over the time the model was generating, thinking included",
         "A trace stores the response the stream carried, not the stream"
        ],
        "exposes": "ttft_seconds and tokens_per_second on every llm_call event",
        "status": "accepted"
       }
      }
     ]
    }
   ]
  },
  {
   "id": "main",
   "kind": "service",
   "name": "Main agent",
   "headline": "Carries out tasks with tools, one step at a time",
   "card": {
    "does": "Runs each delegated task: model call, tool calls, approvals, until there is a result.",
    "exposes": "/health, /ready, /metrics",
    "status": "accepted"
   },
   "children": [
    {
     "id": "door",
     "kind": "interface",
     "name": "A2A server",
     "headline": "One task per request name; no task in a deleted chat",
     "card": {
      "does": "Accepts tasks and task control over the A2A protocol.",
      "rules": [
       "A request name that was already accepted is answered with the existing task",
       "The name is stored with the task in one transaction; if two arrive at once the second ends failed without running",
       "A new task for a deleted chat is refused",
       "Pause and resume are an extension to the protocol"
      ],
      "decision": "A2A between the agents",
      "why": "A clean protocol boundary: the main agent can be replaced or used by another front.",
      "status": "accepted"
     }
    },
    {
     "id": "line",
     "kind": "queue",
     "name": "Task turns",
     "headline": "One task on the model at a time",
     "card": {
      "does": "Lets tasks take turns on the model.",
      "rules": [
       "One task runs; the rest wait in order",
       "A task waiting for an approval has let go of its turn"
      ],
      "decision": "One at a time",
      "why": "Tasks would otherwise share one context window.",
      "exposes": "Queue length on /metrics; task_state.queued in events",
      "status": "accepted"
     }
    },
    {
     "id": "loop",
     "kind": "component",
     "name": "Agent loop",
     "headline": "A step is one model call and its tool calls; saved after every step",
     "card": {
      "does": "Runs a task step by step until the model gives a result.",
      "status": "accepted"
     },
     "children": [
      {
       "id": "call",
       "kind": "component",
       "name": "Model call",
       "headline": "3 tries, then the task fails with a notification",
       "card": {
        "does": "Sends the task's view to the model and reads the answer.",
        "rules": [
         "Retries a failed call 3 times with growing delays",
         "A full context window: compact harder and try once more"
        ],
        "failure": "After the last try the task fails and the person is notified.",
        "status": "accepted"
       }
      },
      {
       "id": "compact",
       "kind": "policy",
       "name": "Context limit",
       "headline": "Summarise at the limit, never later than 90% of the window",
       "card": {
        "does": "Keeps the task's view inside the model's window.",
        "rules": [
         "Older turns are summarised when the view reaches the agent's token limit",
         "Never later than 90 percent of the loaded window",
         "A cloud endpoint reports no window, so the token limit is the only trigger there",
         "A finished task stays in the transcript as its instruction, a log of its tools, and its final message"
        ],
        "decision": "A token limit per agent",
        "why": "A percentage could never trigger on an endpoint that reports no window.",
        "rejected": [
         "OpenAI's server-side compaction: not available on local endpoints"
        ],
        "status": "accepted"
       }
      },
      {
       "id": "tools",
       "kind": "component",
       "name": "Tool step",
       "headline": "Each call runs at most once",
       "card": {
        "does": "Runs the tool calls the model asked for.",
        "rules": [
         "Each call has a mark keyed by task, step and position",
         "A call that finished is answered from its stored result",
         "A call that started without a result is reported as 'outcome unknown, verify first' and never re-run blindly"
        ],
        "decision": "Run-once marks",
        "why": "After a restart the loop must not repeat a command that may already have run.",
        "status": "accepted"
       }
      },
      {
       "id": "ask",
       "kind": "policy",
       "name": "Approval wait",
       "headline": "300 s; two timeouts in a row pause the task",
       "card": {
        "does": "Waits for a person's answer when a tool asks.",
        "rules": [
         "No answer in 300 seconds: the request is cancelled and the model is told the person did not respond",
         "Two such timeouts in a row pause the task and notify the person",
         "An allow-always answer is kept per chat and tool, and answered here without asking again",
         "The first answer wins"
        ],
        "decision": "Allow-always rules live in the main agent",
        "why": "Approvals must not depend on the gateway being up.",
        "status": "accepted"
       }
      },
      {
       "id": "save",
       "kind": "database",
       "name": "Saved steps",
       "headline": "A checkpoint per step",
       "card": {
        "does": "Saves everything the loop knows after every step.",
        "rules": [
         "One saved thread per task",
         "A pause takes effect at the top of a step, never in the middle",
         "After a restart a task continues from its last step",
         "Removed with the chat, and for finished tasks after the retention period"
        ],
        "status": "accepted"
       }
      }
     ]
    },
    {
     "id": "mcp",
     "kind": "component",
     "name": "Tool server manager",
     "headline": "One tool server process per project",
     "card": {
      "does": "Starts and talks to tool servers over MCP.",
      "rules": [
       "The project folder is given to the server as its root",
       "The chat id travels beside the arguments and is only recorded",
       "A server with an open shell session is not stopped"
      ],
      "question": "A second MCP server of your own can join or replace the built-in one later; its permission rules are not defined yet.",
      "status": "open"
     }
    },
    {
     "id": "store",
     "kind": "database",
     "name": "Main store",
     "headline": "Tasks, approvals, rules, transcripts, request names",
     "card": {
      "does": "Keeps what the main agent owns.",
      "rules": [
       "SQLite, owned by this service alone",
       "Deleting a chat: note it as deleted, remove saved steps, then remove the task records last, so asking again can finish a delete that failed half-way",
       "The deleted note is kept 7 days; nothing is written for that chat again"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "outbox",
     "kind": "queue",
     "name": "Event outbox",
     "headline": "At least once, in order, never waits for the gateway",
     "card": {
      "does": "Holds the main agent's events until the gateway has them.",
      "rules": [
       "Every event is written to the outbox's own SQLite file first",
       "A background sender delivers in order and retries with backoff",
       "The gateway can ask for 'my events since N' again (replay)",
       "Nothing is stored for a chat that was deleted",
       "Delivered events are removed after the retention period"
      ],
      "decision": "Outbox with a sender",
      "why": "A service must never wait on the gateway to do its own work.",
      "rejected": [
       "Call the gateway directly: an agent would stall whenever the gateway was down"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "llm",
     "kind": "component",
     "name": "Model runtime",
     "headline": "One provider, one model, settings changeable while running",
     "card": {
      "does": "Holds the main agent's model settings and its provider, and is the only way the agent calls a model.",
      "status": "accepted"
     },
     "children": [
      {
       "id": "settings",
       "kind": "policy",
       "name": "Effective settings",
       "headline": ".env, then saved changes, then the key",
       "card": {
        "does": "Works out the settings in force.",
        "rules": [
         "Starting values come from .env; changes saved from Settings are kept in the agent's own database",
         "The model and the address are remembered per provider: switching provider never carries them over",
         "Load settings apply at the next load; answer settings apply to the next call"
        ],
        "decision": "Each agent owns its settings",
        "why": "An agent keeps working, with the right settings, while the gateway is down.",
        "status": "accepted"
       }
      },
      {
       "id": "busy",
       "kind": "policy",
       "name": "Change guard",
       "headline": "No change while the model is in use",
       "card": {
        "does": "Keeps a settings change and a model call from overlapping.",
        "rules": [
         "A save, a new key, Unload or Reload while a call is running is refused with 409 and the words 'The model is in use right now. Try again when it has finished.'",
         "A call that starts while a change is being applied waits for the change to finish",
         "Nothing is changed by a refused request"
        ],
        "decision": "Refuse, do not queue the change",
        "why": "Rebuilding closes the provider, and for the built-in llama.cpp that stops the server under the running call.",
        "rejected": [
         "Apply the change after the call: the person would not know when it took effect",
         "Let the change through: it killed the model server in the middle of an answer"
        ],
        "status": "accepted"
       }
      },
      {
       "id": "keys",
       "kind": "policy",
       "name": "Key rule",
       "headline": "One key per agent, provider and address",
       "card": {
        "does": "Decides which stored key, if any, goes with a call.",
        "rules": [
         "Keys live in the operating system's credential store, never in a file or a database",
         "A key is stored for one agent and one provider",
         "A key is sent only to the address it was typed for; after the address changes it is held back until typed again",
         "The .env key goes only to the .env provider at the .env address",
         "A key is never returned: clients learn only 'set' or 'held back'"
        ],
        "decision": "Tie the key to its address",
        "why": "Pointing an agent at another server must not hand that server the old one's key.",
        "rejected": [
         "Tie the key to the provider only: a changed address received the stored key"
        ],
        "status": "accepted"
       }
      },
      {
       "id": "idle",
       "kind": "policy",
       "name": "Idle unload",
       "headline": "Unloads after 5 minutes without use",
       "card": {
        "does": "Frees the hardware when nobody is using the model.",
        "rules": [
         "A model counts as in use for the whole of every call, loading included",
         "Default 5 minutes per agent; 0 keeps the model loaded",
         "Checked every 15 seconds",
         "Nothing is loaded when the service starts"
        ],
        "decision": "Unload by the agent, not by the model server",
        "why": "A stopped llama.cpp process really releases the GPU; llama.cpp's own idle sleep does not.",
        "failure": "A failed unload is tried again on the next pass.",
        "status": "accepted"
       }
      },
      {
       "id": "timing",
       "kind": "component",
       "name": "Call timing",
       "headline": "Time to first token and tokens per second",
       "card": {
        "does": "Measures each streamed call.",
        "rules": [
         "Time to first token: from the request to the first piece that carries text or a tool call",
         "Tokens per second: output tokens over the time the model was generating, thinking included",
         "A trace stores the response the stream carried, not the stream"
        ],
        "exposes": "ttft_seconds and tokens_per_second on every llm_call event",
        "status": "accepted"
       }
      }
     ]
    }
   ]
  },
  {
   "id": "tools",
   "kind": "service",
   "name": "Tool server",
   "headline": "Files and shell inside one project; asks before risky steps",
   "card": {
    "does": "Runs the tools. Enforces the folder boundary for files, the approval for risky tools, and the deny list.",
    "status": "accepted"
   },
   "children": [
    {
     "id": "policy",
     "kind": "policy",
     "name": "Permission policy",
     "headline": "Read and write allowed; delete and shell ask",
     "card": {
      "does": "Decides for each tool whether it runs, asks, or is refused.",
      "rules": [
       "fs.read, fs.list, fs.write, fs.edit, fs.patch: allowed",
       "fs.delete, shell, shell session commands: ask the person every time",
       "Fixed in code: no prompt can change it"
      ],
      "decision": "Policy in the tool server",
      "why": "The server that runs a tool is the one place that cannot be talked out of the rule.",
      "status": "accepted"
     }
    },
    {
     "id": "deny",
     "kind": "policy",
     "name": "Deny list",
     "headline": "Refused before anyone is asked",
     "card": {
      "does": "Stops shell commands that must never run.",
      "rules": [
       "Erasing or repartitioning a disk, wiping files, deleting from the registry",
       "Deleting outside the project folder",
       "Changing the firewall, user accounts or other security settings of the PC",
       "Sending, publishing or fetching files over the network; making files on the PC reachable from other machines",
       "Commands that hide their own text (an encoded command)",
       "Checked before the approval is asked and again before the command runs",
       "Installing packages and cloning a repository are not on the list"
      ],
      "decision": "A list that approval cannot lift",
      "why": "An 'always allow' rule removes the approval for a chat; these commands must not depend on it.",
      "rejected": [
       "Confine the shell to the folder: real work needs the real shell",
       "Rely on approval alone: a habit of pressing Allow is not a control"
      ],
      "failure": "The command is answered with a tool error that says the rule cannot be approved away.",
      "question": "The list reads the command as text and does not see inside a script file.",
      "status": "open"
     }
    },
    {
     "id": "box",
     "kind": "policy",
     "name": "Folder boundary",
     "headline": "File tools never leave the project folder",
     "card": {
      "does": "Checks every path given to a file tool.",
      "rules": [
       "Resolves the path and refuses anything outside the folder: '..', links, junctions, short names, network paths",
       "The shell starts in the folder but is not confined to it"
      ],
      "decision": "Confine files, not the shell",
      "why": "Approval and the deny list are the shell's controls.",
      "status": "accepted"
     }
    },
    {
     "id": "shell",
     "kind": "component",
     "name": "Shell",
     "headline": "PowerShell, with the whole process tree killed on timeout",
     "card": {
      "does": "Runs a command, once or in a session that keeps its folder and variables.",
      "rules": [
       "At most 4 open sessions",
       "A timeout kills the process tree and closes the session",
       "An error that stops the command is reported as exit code 1; a program's own code is kept",
       "Output is capped"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "audit",
     "kind": "database",
     "name": "Call log",
     "headline": "Every call and decision, one file per project",
     "card": {
      "does": "Records each tool call, the chat it was for, the decision, and how it ended.",
      "rules": [
       "SQLite, one file per project",
       "Cleared with the chat, and after the retention period"
      ],
      "status": "accepted"
     }
    }
   ]
  },
  {
   "id": "models",
   "kind": "hardware",
   "name": "Model providers",
   "headline": "LM Studio, built-in llama.cpp, or an OpenAI-compatible endpoint",
   "lane": "right",
   "card": {
    "does": "Where the models run. Each agent chooses its own.",
    "status": "accepted"
   },
   "children": [
    {
     "id": "lmstudio",
     "kind": "hardware",
     "name": "LM Studio",
     "headline": "Loaded and unloaded through its own API",
     "card": {
      "does": "Serves a model on the PC.",
      "rules": [
       "Chat over /v1/responses",
       "An already-loaded model is adopted as it is",
       "Does not accept audio"
      ],
      "status": "accepted"
     }
    },
    {
     "id": "llamacpp",
     "kind": "hardware",
     "name": "Built-in llama.cpp",
     "headline": "One server process per agent, started on load",
     "card": {
      "does": "A llama.cpp server Thursday starts for a .gguf file and stops on unload.",
      "rules": [
       "One process per agent on a free localhost port, with a random key for each run",
       "Only files inside the chosen models folder are loaded",
       "Across several graphics cards the model is split by layer"
      ],
      "decision": "A process per agent",
      "why": "A stopped process really frees the GPU.",
      "question": "Running a model across cards in parallel does not load on NVIDIA cards in the build setup installs.",
      "status": "open"
     }
    },
    {
     "id": "cloud",
     "kind": "hardware",
     "name": "OpenAI-compatible endpoint",
     "headline": "Sends data off the PC",
     "card": {
      "does": "A cloud provider, or a model server run by the person.",
      "rules": [
       "Chat and the model list only: nothing to load or unload",
       "Clearly marked in Settings as sending data off the PC"
      ],
      "status": "accepted"
     }
    }
   ]
  },
  {
   "id": "speech",
   "kind": "service",
   "name": "Speech service",
   "headline": "Whisper and Kokoro on the CPU",
   "lane": "right",
   "card": {
    "does": "Turns a recording into text and a reply into audio.",
    "rules": [
     "One request at a time per engine",
     "Engines load on first use and are dropped after 5 minutes without use",
     "No audio is stored",
     "A voice model that can hear writes the words down itself; Whisper is the fallback"
    ],
    "decision": "Speech on the CPU",
    "why": "It is fast enough for push-to-talk and leaves the GPU to the models.",
    "question": "Continuous listening is not designed; voice is push-to-talk only.",
    "status": "open"
   }
  },
  {
   "id": "metrics",
   "kind": "service",
   "name": "Metrics collector",
   "headline": "Samples every second, keeps nothing",
   "lane": "bottom",
   "card": {
    "does": "Reads the PC's CPU, RAM, VRAM and network, asks each service for its numbers, and pushes them to the gateway.",
    "rules": [
     "One sample a second",
     "History is kept by the gateway: every 5 seconds for 24 hours, one a minute for 7 days by default",
     "Measures how much each service keeps on disk, at most once a minute"
    ],
    "status": "accepted"
   }
  },
  {
   "id": "launcher",
   "kind": "component",
   "name": "Launcher",
   "headline": "thursday up, down, status, setup",
   "lane": "bottom",
   "card": {
    "does": "Starts the services, restarts one that crashed, and stops them.",
    "rules": [
     "Restarts after a delay doubling from 1 s to 30 s, reset after 60 s of steady running",
     "'down' asks the supervisor to stop and waits 20 seconds before stopping what is left",
     "A supervisor is stopped even when none of its services answers",
     "Only a process that is Thursday's own is ever stopped"
    ],
    "status": "accepted"
   }
  }
 ],
 "edges": [
  {
   "from": "person",
   "to": "ui.chat",
   "label": "types or talks",
   "kind": "ui"
  },
  {
   "from": "ui.chat",
   "to": "gateway.doors",
   "label": "send a message",
   "card": {
    "carries": "POST /v1/chats/{id}/messages {client_message_id, text}",
    "mode": "sync",
    "timeout": "20 s",
    "retry": "the client retries; sends carry a client message id"
   }
  },
  {
   "from": "gateway.doors",
   "to": "gateway.relay",
   "label": "accepted message"
  },
  {
   "from": "gateway.relay",
   "to": "voice.turn",
   "label": "the message, in order",
   "card": {
    "carries": "POST /v1/chats/{id}/turns; the reply streams back as lines",
    "mode": "sync stream",
    "timeout": "none while the reply streams",
    "retry": "queued and retried with a delay from 1 s to 30 s; the turn is idempotent on the message id"
   }
  },
  {
   "from": "voice.turn",
   "to": "voice.yes",
   "label": "is this an answer to an approval?",
   "kind": "control"
  },
  {
   "from": "voice.turn",
   "to": "voice.llm.busy",
   "label": "model call"
  },
  {
   "from": "voice.llm.busy",
   "to": "voice.llm.settings",
   "label": "settings in force",
   "kind": "control"
  },
  {
   "from": "voice.llm.settings",
   "to": "voice.llm.keys",
   "label": "which key",
   "kind": "control"
  },
  {
   "from": "voice.llm.keys",
   "to": "models.lmstudio",
   "label": "request",
   "card": {
    "carries": "/v1/responses, streamed",
    "mode": "sync stream",
    "timeout": "per provider",
    "retry": "none in the voice agent"
   }
  },
  {
   "from": "voice.llm.timing",
   "to": "voice.outbox",
   "label": "llm_call event",
   "kind": "monitor",
   "async": true
  },
  {
   "from": "voice.llm.busy",
   "to": "voice.llm.timing",
   "label": "the stream"
  },
  {
   "from": "voice.llm.idle",
   "to": "models.llamacpp",
   "label": "stop the server when idle",
   "kind": "control"
  },
  {
   "from": "voice.turn",
   "to": "voice.delegate",
   "label": "start a task"
  },
  {
   "from": "voice.delegate",
   "to": "main.door",
   "label": "task, with its request name",
   "card": {
    "carries": "A2A SendMessage with metadata thursday.request, project id and folder",
    "mode": "sync, returns immediately",
    "timeout": "short",
    "retry": "the same name is sent again; the main agent answers with the task it already started"
   }
  },
  {
   "from": "voice.turn",
   "to": "voice.store",
   "label": "transcript, stored reply",
   "kind": "store"
  },
  {
   "from": "voice.delegate",
   "to": "voice.store",
   "label": "delegated task",
   "kind": "store"
  },
  {
   "from": "voice.turn",
   "to": "voice.outbox",
   "label": "message events",
   "kind": "store",
   "async": true
  },
  {
   "from": "voice.outbox",
   "to": "gateway.ingest",
   "label": "events",
   "async": true,
   "card": {
    "carries": "event envelope {event_id, source, seq, type, payload}",
    "mode": "async, at least once",
    "timeout": "per request",
    "retry": "backoff until delivered; replay on request"
   }
  },
  {
   "from": "main.door",
   "to": "main.store",
   "label": "task and request name",
   "kind": "store"
  },
  {
   "from": "main.door",
   "to": "main.line",
   "label": "task"
  },
  {
   "from": "main.line",
   "to": "main.loop.call",
   "label": "the task whose turn it is"
  },
  {
   "from": "main.loop.call",
   "to": "main.loop.compact",
   "label": "is the view too big?",
   "kind": "control"
  },
  {
   "from": "main.loop.call",
   "to": "main.llm.busy",
   "label": "model call"
  },
  {
   "from": "main.llm.busy",
   "to": "main.llm.settings",
   "label": "settings in force",
   "kind": "control"
  },
  {
   "from": "main.llm.settings",
   "to": "main.llm.keys",
   "label": "which key",
   "kind": "control"
  },
  {
   "from": "main.llm.keys",
   "to": "models.llamacpp",
   "label": "request",
   "card": {
    "carries": "/v1/chat/completions, streamed",
    "mode": "sync stream",
    "timeout": "per provider",
    "retry": "3 tries in the loop"
   }
  },
  {
   "from": "main.llm.keys",
   "to": "models.cloud",
   "label": "request",
   "card": {
    "carries": "/v1/responses, streamed",
    "mode": "sync stream",
    "timeout": "per provider",
    "retry": "3 tries in the loop"
   }
  },
  {
   "from": "main.llm.busy",
   "to": "main.llm.timing",
   "label": "the stream"
  },
  {
   "from": "main.llm.timing",
   "to": "main.outbox",
   "label": "llm_call event",
   "kind": "monitor",
   "async": true
  },
  {
   "from": "main.llm.idle",
   "to": "models.lmstudio",
   "label": "unload when idle",
   "kind": "control"
  },
  {
   "from": "main.loop.call",
   "to": "main.loop.tools",
   "label": "tool calls the model asked for"
  },
  {
   "from": "main.loop.tools",
   "to": "main.mcp",
   "label": "tool call"
  },
  {
   "from": "main.mcp",
   "to": "tools.deny",
   "label": "shell command",
   "card": {
    "carries": "MCP tools/call over stdio, with the chat id beside the arguments",
    "mode": "sync",
    "timeout": "the tool's own, capped",
    "retry": "never blindly: a call without a result is reported as unknown"
   }
  },
  {
   "from": "main.mcp",
   "to": "tools.box",
   "label": "file tool call"
  },
  {
   "from": "tools.deny",
   "to": "tools.policy",
   "label": "not on the list"
  },
  {
   "from": "tools.deny",
   "to": "main.mcp",
   "label": "refused, nobody asked",
   "kind": "error"
  },
  {
   "from": "tools.box",
   "to": "tools.policy",
   "label": "path inside the folder"
  },
  {
   "from": "tools.policy",
   "to": "main.loop.ask",
   "label": "ask the person",
   "kind": "control",
   "card": {
    "carries": "MCP input-required result",
    "mode": "sync",
    "timeout": "300 s",
    "retry": "the call is retried with the answer"
   }
  },
  {
   "from": "main.loop.ask",
   "to": "main.outbox",
   "label": "approval_requested",
   "kind": "store",
   "async": true
  },
  {
   "from": "main.loop.ask",
   "to": "tools.shell",
   "label": "allowed"
  },
  {
   "from": "tools.shell",
   "to": "tools.audit",
   "label": "call, decision, outcome",
   "kind": "store"
  },
  {
   "from": "tools.shell",
   "to": "main.loop.tools",
   "label": "output and exit code",
   "kind": "result"
  },
  {
   "from": "main.loop.tools",
   "to": "main.loop.save",
   "label": "step saved",
   "kind": "store"
  },
  {
   "from": "main.loop.save",
   "to": "main.loop.call",
   "label": "next step",
   "kind": "control"
  },
  {
   "from": "main.loop.call",
   "to": "voice.report",
   "label": "task update",
   "kind": "result",
   "async": true,
   "card": {
    "carries": "A2A push notification with the task's token",
    "mode": "async",
    "timeout": "per request",
    "retry": "by the A2A server"
   }
  },
  {
   "from": "main.loop.tools",
   "to": "main.outbox",
   "label": "tool_call events",
   "kind": "store",
   "async": true
  },
  {
   "from": "main.outbox",
   "to": "gateway.ingest",
   "label": "events",
   "async": true,
   "card": {
    "carries": "event envelope {event_id, source, seq, type, payload}",
    "mode": "async, at least once",
    "timeout": "per request",
    "retry": "backoff until delivered; replay on request"
   }
  },
  {
   "from": "voice.report",
   "to": "voice.llm.busy",
   "label": "write the report"
  },
  {
   "from": "voice.report",
   "to": "voice.outbox",
   "label": "assistant message",
   "kind": "store",
   "async": true
  },
  {
   "from": "gateway.ingest",
   "to": "gateway.read",
   "label": "projected events",
   "kind": "store"
  },
  {
   "from": "gateway.ingest",
   "to": "gateway.hub",
   "label": "new event"
  },
  {
   "from": "gateway.hub",
   "to": "ui.chat",
   "label": "messages, task cards, reply text",
   "kind": "ui",
   "async": true
  },
  {
   "from": "gateway.ingest",
   "to": "ui.approvals",
   "label": "approval request and notification",
   "kind": "ui",
   "async": true
  },
  {
   "from": "ui.approvals",
   "to": "gateway.control",
   "label": "allow once, allow always, deny",
   "card": {
    "carries": "POST /v1/approvals/{id}",
    "mode": "sync",
    "timeout": "20 s",
    "retry": "the client retries; sends carry a client message id"
   }
  },
  {
   "from": "ui.chat",
   "to": "gateway.control",
   "label": "pause, resume, stop",
   "kind": "control"
  },
  {
   "from": "gateway.control",
   "to": "main.loop.ask",
   "label": "the answer",
   "card": {
    "carries": "A2A message to the waiting task",
    "mode": "sync",
    "timeout": "short",
    "retry": "none; the first answer wins"
   }
  },
  {
   "from": "voice.yes",
   "to": "main.loop.ask",
   "label": "a spoken yes or no"
  },
  {
   "from": "gateway.control",
   "to": "main.loop.save",
   "label": "pause at the next step, or stop now",
   "kind": "control"
  },
  {
   "from": "gateway.read",
   "to": "ui.trace",
   "label": "a task's steps",
   "kind": "ui"
  },
  {
   "from": "gateway.read",
   "to": "ui.monitor",
   "label": "history",
   "kind": "ui"
  },
  {
   "from": "main.loop.ask",
   "to": "ui.tools",
   "label": "allow-always rules",
   "kind": "ui"
  },
  {
   "from": "gateway.status",
   "to": "ui.chat",
   "label": "banner: what is down",
   "kind": "ui"
  },
  {
   "from": "gateway.status",
   "to": "voice.turn",
   "label": "readiness check",
   "kind": "control"
  },
  {
   "from": "gateway.status",
   "to": "main.door",
   "label": "readiness check",
   "kind": "control"
  },
  {
   "from": "gateway.lifecycle",
   "to": "gateway.relay",
   "label": "fail the chat's waiting messages",
   "kind": "control"
  },
  {
   "from": "gateway.lifecycle",
   "to": "voice.store",
   "label": "delete this chat",
   "kind": "control",
   "card": {
    "carries": "DELETE /v1/chats/{id}",
    "mode": "sync",
    "timeout": "short",
    "retry": "until it confirms"
   }
  },
  {
   "from": "gateway.lifecycle",
   "to": "main.store",
   "label": "delete this chat",
   "kind": "control",
   "card": {
    "carries": "DELETE /v1/chats/{id}",
    "mode": "sync",
    "timeout": "short",
    "retry": "until it confirms"
   }
  },
  {
   "from": "main.store",
   "to": "tools.audit",
   "label": "forget this chat's calls",
   "kind": "control"
  },
  {
   "from": "gateway.keep",
   "to": "voice.store",
   "label": "retention period, backup copy",
   "kind": "control"
  },
  {
   "from": "gateway.keep",
   "to": "main.store",
   "label": "retention period, backup copy",
   "kind": "control"
  },
  {
   "from": "ui.settings",
   "to": "gateway.doors",
   "label": "a settings change"
  },
  {
   "from": "voice.llm.settings",
   "to": "ui.settings",
   "label": "provider, model, load and answer settings, idle time",
   "kind": "config"
  },
  {
   "from": "main.llm.settings",
   "to": "ui.settings",
   "label": "provider, model, load and answer settings, context limit",
   "kind": "config"
  },
  {
   "from": "voice.llm.keys",
   "to": "ui.settings",
   "label": "API key: set, or held back",
   "kind": "config"
  },
  {
   "from": "main.llm.keys",
   "to": "ui.settings",
   "label": "API key: set, or held back",
   "kind": "config"
  },
  {
   "from": "main.llm.busy",
   "to": "ui.settings",
   "label": "refused: the model is in use",
   "kind": "error"
  },
  {
   "from": "gateway.keep",
   "to": "ui.settings",
   "label": "retention period, backup folder and schedule",
   "kind": "config"
  },
  {
   "from": "gateway.doors",
   "to": "ui.settings",
   "label": "paired devices, pairing code",
   "kind": "config"
  },
  {
   "from": "ui.chat",
   "to": "speech",
   "label": "a recording; a reply to read aloud",
   "card": {
    "carries": "through the gateway: /v1/speech/transcribe, /v1/speech/speak",
    "mode": "sync",
    "timeout": "20 s",
    "retry": "none"
   }
  },
  {
   "from": "speech",
   "to": "ui.chat",
   "label": "the words; the audio",
   "kind": "result"
  },
  {
   "from": "metrics",
   "to": "gateway.read",
   "label": "samples",
   "kind": "monitor",
   "async": true
  },
  {
   "from": "metrics",
   "to": "ui.monitor",
   "label": "live values",
   "kind": "ui",
   "async": true
  },
  {
   "from": "launcher",
   "to": "gateway.doors",
   "label": "start, health check, stop",
   "kind": "control"
  },
  {
   "from": "launcher",
   "to": "models.llamacpp",
   "label": "stop a server left behind",
   "kind": "control"
  }
 ],
 "flows": [
  {
   "id": "task",
   "name": "An instruction that needs an approval",
   "steps": [
    {
     "at": "person",
     "note": "You type or say what you want done."
    },
    {
     "at": "ui.chat",
     "note": "The client gives the message an id and sends it."
    },
    {
     "at": "gateway.doors",
     "note": "The request is accepted on the listener it came through."
    },
    {
     "at": "gateway.relay",
     "note": "The message is stored and queued; it is safe from here on."
    },
    {
     "at": "voice.turn",
     "note": "The voice model answers and decides this is work to hand over."
    },
    {
     "at": "voice.delegate",
     "note": "A task is started under a name worked out from the message."
    },
    {
     "at": "main.door",
     "note": "The main agent stores the task with its name and answers at once."
    },
    {
     "at": "main.line",
     "note": "The task waits for its turn on the model."
    },
    {
     "at": "main.loop.call",
     "note": "The model is called and asks for a shell command."
    },
    {
     "at": "main.loop.tools",
     "note": "The call gets its run-once mark."
    },
    {
     "at": "main.mcp",
     "note": "The call goes to the project's tool server."
    },
    {
     "at": "tools.deny",
     "note": "The command is not on the deny list."
    },
    {
     "at": "tools.policy",
     "note": "Shell commands ask the person."
    },
    {
     "at": "main.loop.ask",
     "note": "The task waits up to 300 seconds; you press Allow."
    },
    {
     "at": "tools.shell",
     "note": "The command runs in the project folder."
    },
    {
     "at": "main.loop.tools",
     "note": "The output comes back and the step is finished."
    },
    {
     "at": "main.loop.save",
     "note": "Everything is saved before the next step."
    },
    {
     "at": "main.loop.call",
     "note": "The model reads the output and gives its result."
    },
    {
     "at": "voice.report",
     "note": "The voice agent tells you the result in a sentence or two."
    }
   ]
  },
  {
   "id": "denied",
   "name": "A command that is never run",
   "steps": [
    {
     "at": "main.loop.tools",
     "note": "The model asks to upload a file with a web request."
    },
    {
     "at": "main.mcp",
     "note": "The call goes to the tool server."
    },
    {
     "at": "tools.deny",
     "note": "The command is on the deny list: refused, and nobody is asked."
    },
    {
     "at": "main.mcp",
     "note": "The model is told the rule cannot be approved away, and chooses another way."
    }
   ]
  },
  {
   "id": "lost",
   "name": "The main agent's answer is lost",
   "steps": [
    {
     "at": "voice.turn",
     "note": "The voice model decides to hand work over."
    },
    {
     "at": "voice.delegate",
     "note": "The request is sent; the task starts, but the answer never arrives."
    },
    {
     "at": "main.door",
     "note": "The same request, with the same name, is sent again: the main agent answers with the task it already has."
    },
    {
     "at": "main.line",
     "note": "One task runs, once."
    }
   ]
  },
  {
   "id": "busy",
   "name": "Saving a setting while the model answers",
   "steps": [
    {
     "at": "ui.settings",
     "note": "You save a new temperature for the main agent."
    },
    {
     "at": "gateway.doors",
     "note": "The change is passed to the main agent."
    }
   ]
  }
 ]
};
