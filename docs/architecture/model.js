// The architecture model: the only file edited for a project. index.html draws it; after every edit run
//   node check.mjs
// The full field reference is in README.md, next to this file.
//
//   parts      { id, kind, name, does, lane, children, ...the fields its kind needs }
//   kinds      external group step decision store queue event ui
//   needs      step: in, out   decision: test, branches   store: keeps   queue: capacity, when_full   event: trigger
//   optional   headline rules choice why rejected failure exposes code stops status question
//   links      'from -> to : label (kind, async)'  or  { from, to, label, kind, async, contract: { mode, timeout, retry } }
//   journeys   { id, name, type, paths: ['a -> b -> c'], notes: { id: 'note' } }   type: user call timer signal data
//   data       { id, name, fields: { field: 'type' } }   a type can name another data item: 'request' or 'request[]'
window.ARCH_MODEL = {
  name: 'Thursday',
  palette: 'violet',
  note: 'A personal agent harness on your own PC: a quick voice agent hands work to a main agent with tools, and a dashboard and a phone app show everything live.',

  data: [
    { id: 'chat_message', name: 'Chat message', fields: { client_message_id: 'string', chat_id: 'string', project_id: 'string', project_folder: 'path', text: 'string', direct: 'boolean' } },
    { id: 'reply', name: 'Reply stream', fields: { type: 'enum', text: 'string' } },
    { id: 'task_request', name: 'Task request', fields: { context_id: 'chat id', request: 'string', project_id: 'string', project_folder: 'path', text: 'string' } },
    { id: 'task_update', name: 'Task update', fields: { task_id: 'string', state: 'enum', summary: 'string' } },
    { id: 'task_control', name: 'Task control', fields: { task_id: 'string', action: 'enum' } },
    { id: 'approval_request', name: 'Approval request', fields: { approval_id: 'string', task_id: 'string', chat_id: 'string', tool: 'string', summary: 'string', arguments: 'json', expires_at: 'timestamp' } },
    { id: 'approval_answer', name: 'Approval answer', fields: { approval_id: 'string', decision: 'enum' } },
    { id: 'tool_call', name: 'Tool call', fields: { chat_id: 'string', tool: 'string', arguments: 'json' } },
    { id: 'tool_result', name: 'Tool result', fields: { status: 'enum', output: 'string' } },
    { id: 'event', name: 'Event', fields: { event_id: 'string', schema_version: 'integer', source: 'enum', seq: 'integer', ts: 'timestamp', project_id: 'string', chat_id: 'string', task_id: 'string', type: 'enum', payload: 'json' } },
    { id: 'notification', name: 'Notification', fields: { chat_id: 'string', text: 'string' } },
    { id: 'model_request', name: 'Model request', fields: { input: 'json', tools: 'json', settings: 'json' } },
    { id: 'model_response', name: 'Model response', fields: { text: 'string', tool_calls: 'json', usage: 'json' } },
    { id: 'recording', name: 'Recording', fields: { audio: 'bytes' } },
    { id: 'transcript', name: 'Transcript', fields: { text: 'string' } },
    { id: 'spoken_reply', name: 'Spoken reply', fields: { audio: 'bytes' } },
    { id: 'setting', name: 'Setting', fields: { agent: 'enum', key: 'string', value: 'json' } },
    { id: 'metrics_sample', name: 'Metrics sample', fields: { ts: 'timestamp', values: 'json' } },
    { id: 'request', name: 'Client request', fields: { method: 'string', path: 'string', body: 'json', door: 'enum' } },
    { id: 'refusal', name: 'Refusal', fields: { status: 'integer', reason: 'string' } },
    { id: 'pairing_code', name: 'Pairing code', fields: { code: 'string', expires_at: 'timestamp', used: 'boolean' } },
    { id: 'device', name: 'Paired device', fields: { device_id: 'string', token: 'string', last_seen: 'timestamp' } },
    { id: 'view', name: 'View', fields: { items: 'json' } }
  ],

  parts: [
    { id: 'owner', kind: 'external', lane: 'top', name: 'Owner',
      does: 'Types or says an instruction, approves risky steps, and watches the result.' },
    { id: 'apps', kind: 'ui', lane: 'top', name: 'Dashboard and Android app',
      does: 'Shows chats, task steps, approvals, traces, tools, monitoring and settings, on the PC in a browser and on the phone. Both talk to the gateway only.' },
    { id: 'system', kind: 'group', name: 'Thursday',
      does: 'Runs on one PC: turns an instruction into a task, carries it out with tools after the owner approves risky steps, and reports each step live.',
      children: [
      { id: 'gateway', kind: 'group', name: 'Gateway',
        code: 'services/gateway',
        does: 'The one door for every client: projects, chats, sending, task control, settings, pairing and the live stream. Keeps the read model that the screens read.',
        children: [
          { id: 'clients', kind: 'group', name: 'Clients',
            does: 'Where clients come in: the two listeners, the live stream, and talking.',
            children: [
              { id: 'doors', kind: 'group', name: 'Two listeners',
                code: 'services/gateway/src/thursday_gateway/transport',
                does: 'Accepts client requests on two listeners, so which door a call came through cannot be forged by a header.',
                choice: 'Two listeners in place of one listener with rules',
                why: 'The door a request came through cannot be forged by a header.',
                children: [
                  { id: 'local_in', kind: 'step', name: 'Accept on localhost',
                    in: 'request',
                    out: 'request',
                    does: 'The dashboard on the PC calls this listener. No pairing is needed. A proxied request can never reach it.'
                  },
                  { id: 'local_ok', kind: 'decision', name: 'Own page and client header?',
                    test: 'the Host and Origin are the listener\'s own, and a write carries the X-Thursday-Client header',
                    branches: { 'yes': 'system.gateway.clients.doors.route', 'otherwise': 'system.gateway.clients.doors.refuse' }
                  },
                  { id: 'proxy_in', kind: 'step', name: 'Accept behind Tailscale',
                    in: 'request',
                    out: 'request',
                    does: 'The phone calls the tailnet listener, which Tailscale Serve forwards to. It always needs a paired device.'
                  },
                  { id: 'proxy_ok', kind: 'decision', name: 'Valid device token?',
                    test: 'the call carries a valid device token',
                    branches: { 'yes': 'system.gateway.clients.doors.route', 'it claims a pairing code': 'system.gateway.clients.doors.pairing.pair_claim', 'otherwise': 'system.gateway.clients.doors.refuse' }
                  },
                  { id: 'refuse', kind: 'step', name: 'Refuse the call',
                    in: 'request',
                    out: 'refusal',
                    does: '401 without a valid token; 403 for a browser request from another origin or without the client header.',
                    stops: 'The client gets the refusal and nothing else happens.'
                  },
                  { id: 'pairing', kind: 'group', name: 'Pairing',
                    does: 'Makes pairing codes and issues device tokens to phones.',
                    children: [
                      { id: 'pair_make', kind: 'step', name: 'Make a pairing code',
                        in: 'request',
                        out: 'pairing_code',
                        does: 'Only on the localhost listener. A code is 8 characters, valid once, for 5 minutes.'
                      },
                      { id: 'pair_claim', kind: 'decision', name: 'Code still good?',
                        test: 'the code is unused and under 5 minutes old',
                        branches: { 'yes': 'system.gateway.clients.doors.pairing.pair_issue', 'otherwise': 'system.gateway.clients.doors.refuse' }
                      },
                      { id: 'pair_issue', kind: 'step', name: 'Issue a device token',
                        in: 'pairing_code',
                        out: 'device',
                        does: 'Makes a token for the phone, stores it, and uses the code up. The phone\'s fingerprint or PIN check happens on the phone.'
                      },
                      { id: 'devices', kind: 'store', name: 'Paired devices',
                        keeps: [ 'pairing_code', 'device' ],
                        does: 'Keeps pairing codes and the paired devices\' tokens and last-seen times.'
                      }
                    ]
                  },
                  { id: 'route', kind: 'step', name: 'Route the call',
                    in: 'request',
                    out: 'request',
                    does: 'Hands a checked call to the part that owns it: sending, task control, settings, chats and projects, retention and backup, or a read.'
                  }
                ]
              },
              { id: 'hub', kind: 'group', name: 'Live stream',
                code: 'services/gateway/src/thursday_gateway/application/hub.py',
                does: 'Pushes stored events and passing messages (reply text, sending state) to every connected client.',
                children: [
                  { id: 'join', kind: 'step', name: 'Join the stream',
                    in: 'request',
                    out: 'event',
                    does: 'A client joins at the position that the status call gave it and replays what it missed. It reconnects with a delay that doubles from 1 s to 30 s.'
                  },
                  { id: 'push', kind: 'step', name: 'Push to clients',
                    in: 'event',
                    out: 'view',
                    does: 'Sends each new stored event, and each passing message, to every joined client. Reply text is passed on but not stored.'
                  }
                ]
              },
              { id: 'talk', kind: 'group', name: 'Talk and read aloud',
                code: 'services/gateway/src/thursday_gateway/transport/speech_api.py',
                does: 'Turns a recording into a message, and a reply into audio. The owner can type instead when speech is down.',
                children: [
                  { id: 'recording_in', kind: 'step', name: 'Receive a recording',
                    in: 'recording',
                    out: 'recording',
                    does: 'Takes a push-to-talk recording from a client.'
                  },
                  { id: 'heard', kind: 'decision', name: 'Did the voice model hear?',
                    test: 'the voice agent\'s own model wrote down what is said (it did not answer 409)',
                    branches: { 'yes': 'system.gateway.clients.talk.text_in', 'otherwise': 'system.gateway.clients.talk.to_speech' }
                  },
                  { id: 'to_speech', kind: 'step', name: 'Use speech-to-text',
                    in: 'recording',
                    out: 'recording',
                    does: 'The model cannot hear, the clip is over 30 seconds, nothing was heard, or the words do not fit the clip, so Whisper writes them down.'
                  },
                  { id: 'text_in', kind: 'step', name: 'Take the words',
                    in: 'transcript',
                    out: 'chat_message',
                    does: 'Shows the owner what was heard and sends the words on as an ordinary message. If speech is down, the owner gets 503 and typing still works.'
                  },
                  { id: 'read_aloud', kind: 'step', name: 'Ask for a reply to be read aloud',
                    in: 'reply',
                    out: 'reply',
                    does: 'Sends the reply text, piece by piece, to the speech service.'
                  },
                  { id: 'play', kind: 'step', name: 'Pass the audio on',
                    in: 'spoken_reply',
                    out: 'spoken_reply',
                    does: 'Sends the audio to the client, which plays it.'
                  }
                ]
              }
            ]
          },
          { id: 'chats', kind: 'group', name: 'Chats and tasks',
            does: 'Sending messages, controlling tasks, and creating and deleting chats.',
            children: [
              { id: 'relay', kind: 'group', name: 'Message relay',
                code: 'services/gateway/src/thursday_gateway/application/relay.py',
                does: 'Takes a sent message and delivers it to the voice agent in order. The message is safe the moment it is accepted, whatever is down.',
                choice: 'The queue lives in the gateway\'s own database',
                why: 'The owner\'s message survives a restart of any service.',
                children: [
                  { id: 'take', kind: 'group', name: 'Accepting a message',
                    does: 'Stores a message and takes the oldest one for sending.',
                    children: [
                      { id: 'accept', kind: 'step', name: 'Accept the message',
                        in: 'chat_message',
                        out: 'chat_message',
                        does: 'Stores the message and tells the client it is queued. Sending the same client message id again returns the stored one; sending a failed message again queues it again.'
                      },
                      { id: 'room', kind: 'decision', name: 'Room for it?',
                        test: 'the chat has fewer than 100 waiting messages, or this message is already waiting',
                        branches: { 'yes': 'system.gateway.chats.relay.take.queue', 'otherwise': 'system.gateway.chats.relay.take.refuse_full' },
                        choice: 'At most 100 waiting messages in a chat',
                        why: 'A long outage of the voice agent must not let the queue grow without end; the owner is told why.',
                        rejected: [ 'No limit: a message is small, but a long outage grows the queue and the owner is never told' ]
                      },
                      { id: 'refuse_full', kind: 'step', name: 'Refuse the message',
                        in: 'chat_message',
                        out: 'refusal',
                        does: 'Answers 429 "Too many waiting messages" with Retry-After 30 seconds. The client keeps the message and may send it again.',
                        stops: 'The client is told to wait and send again.'
                      },
                      { id: 'queue', kind: 'queue', name: 'Waiting messages',
                        capacity: '100 for each chat',
                        when_full: 'refuse the new message with 429 and Retry-After 30 s',
                        does: 'Holds messages in order until the voice agent has them. A message that is already waiting is never refused again.'
                      },
                      { id: 'next', kind: 'step', name: 'Take the oldest message',
                        in: 'chat_message',
                        out: 'chat_message',
                        does: 'Takes the oldest queued message. One message is sent at a time.'
                      },
                      { id: 'active', kind: 'decision', name: 'Chat still active?',
                        test: 'the chat exists and is not being deleted',
                        branches: { 'yes': 'system.gateway.chats.relay.send.mode', 'otherwise': 'system.gateway.chats.relay.take.fail_deleted' }
                      },
                      { id: 'fail_deleted', kind: 'step', name: 'Fail the message',
                        in: 'chat_message',
                        out: 'none',
                        does: 'Marks it failed with "The chat was deleted." Nothing is sent into a chat that is being deleted.',
                        stops: 'The message is failed and shown as failed.'
                      }
                    ]
                  },
                  { id: 'send', kind: 'group', name: 'Sending a message',
                    does: 'Sends one message to the voice agent and handles the answer.',
                    children: [
                      { id: 'mode', kind: 'decision', name: 'Direct mode?',
                        test: 'the chat is in direct mode',
                        branches: { 'yes': 'system.gateway.chats.relay.send.send_direct', 'otherwise': 'system.gateway.chats.relay.send.send_turn' }
                      },
                      { id: 'send_turn', kind: 'step', name: 'Send as a turn',
                        in: 'chat_message',
                        out: 'reply',
                        does: 'Sends the message to the voice agent and passes its reply text on, piece by piece, to the live stream. Reply text is not stored here.'
                      },
                      { id: 'send_direct', kind: 'step', name: 'Send straight on',
                        in: 'chat_message',
                        out: 'chat_message',
                        does: 'Sends the owner\'s words, unchanged, to the main agent through the voice agent\'s direct route.'
                      },
                      { id: 'outcome', kind: 'decision', name: 'How did the voice agent answer?',
                        test: 'the voice agent took the message',
                        branches: { 'yes': 'system.gateway.chats.relay.send.delivered', 'it refused it': 'system.gateway.chats.relay.send.failed', 'otherwise': 'system.gateway.chats.relay.send.backoff' }
                      },
                      { id: 'delivered', kind: 'step', name: 'Mark delivered',
                        in: 'chat_message',
                        out: 'none',
                        does: 'Marks the message delivered and tells the live stream.',
                        stops: 'The message is delivered; the next one is taken.'
                      },
                      { id: 'failed', kind: 'step', name: 'Mark failed',
                        in: 'chat_message',
                        out: 'none',
                        does: 'Marks the message failed with the reason. The client can send it again.',
                        stops: 'The message waits for the owner to send it again.'
                      },
                      { id: 'backoff', kind: 'step', name: 'Wait and try again',
                        in: 'chat_message',
                        out: 'chat_message',
                        does: 'Keeps the message queued, raises the "voice agent unreachable" state, and waits before the next try.',
                        rules: [ 'The delay doubles from 1 s up to 30 s, and resets after one success' ]
                      }
                    ]
                  }
                ]
              },
              { id: 'control', kind: 'group', name: 'Task control',
                code: 'services/gateway/src/thursday_gateway/application/control.py',
                does: 'Sends the owner\'s control of a task, and the owner\'s approval answers, to the main agent. The gateway is its own A2A client, so it works when the voice model is busy or down.',
                choice: 'The gateway talks to the main agent directly for control',
                why: 'Controls must work even when the voice agent cannot.',
                children: [
                  { id: 'send_control', kind: 'step', name: 'Send the control',
                    in: 'task_control',
                    out: 'task_control',
                    does: 'Pause takes effect after the current step; stop cancels at once, including a running tool.'
                  },
                  { id: 'send_answer', kind: 'step', name: 'Send the approval answer',
                    in: 'approval_answer',
                    out: 'approval_answer',
                    does: 'Forwards allow once, allow always or deny for a waiting approval.'
                  },
                  { id: 'answer_taken', kind: 'decision', name: 'Answer accepted?',
                    test: 'the approval is still waiting when the main agent receives the answer',
                    branches: { 'yes': 'system.gateway.chats.control.accepted', 'otherwise': 'system.gateway.chats.control.conflict' }
                  },
                  { id: 'accepted', kind: 'step', name: 'Report the answer taken',
                    in: 'approval_answer',
                    out: 'none',
                    does: 'Tells the client its answer counted.',
                    stops: 'The client sees the approval resolved.'
                  },
                  { id: 'conflict', kind: 'step', name: 'Answer 409',
                    in: 'approval_answer',
                    out: 'refusal',
                    does: 'An approval answer that arrives second gets 409, because the first answer already decided it.',
                    stops: 'The client sees that the approval was already answered.'
                  }
                ]
              },
              { id: 'lifecycle', kind: 'group', name: 'Projects, chats and deletion',
                code: 'services/gateway/src/thursday_gateway/application/deletion.py',
                does: 'Creates projects and chats, and deletes them everywhere as a repeatable saga.',
                choice: 'A repeatable saga',
                why: 'Any service may be down in the middle; asking again must finish the job, never start it twice.',
                children: [
                  { id: 'create', kind: 'step', name: 'Create a project or chat',
                    in: 'request',
                    out: 'view',
                    does: 'A project is a workspace folder. A chat belongs to a project, and has its own voice context and main-agent context.'
                  },
                  { id: 'begin_delete', kind: 'step', name: 'Mark deleting',
                    in: 'request',
                    out: 'request',
                    does: 'In one step: stops the chat\'s tasks, marks the chat deleting, and fails its waiting messages.'
                  },
                  { id: 'ask_agents', kind: 'step', name: 'Ask each agent to delete',
                    in: 'request',
                    out: 'request',
                    does: 'Asks the voice agent and the main agent to remove what they hold for the chat. Repeating the request is safe.'
                  },
                  { id: 'all_done', kind: 'decision', name: 'Everyone confirmed?',
                    test: 'every agent has confirmed the deletion',
                    branches: { 'yes': 'system.gateway.chats.lifecycle.remove_own', 'otherwise': 'system.gateway.chats.lifecycle.wait_retry' }
                  },
                  { id: 'wait_retry', kind: 'step', name: 'Wait and ask again',
                    in: 'request',
                    out: 'request',
                    does: 'Waits, then asks the agents that have not confirmed yet. It retries until every one confirms.'
                  },
                  { id: 'remove_own', kind: 'step', name: 'Remove its own records',
                    in: 'request',
                    out: 'view',
                    does: 'Removes the chat from the read model. The project folder on disk is never touched.',
                    stops: 'The chat is gone from every service.'
                  }
                ]
              }
            ]
          },
          { id: 'settings', kind: 'group', name: 'Settings and keys',
            does: 'Passes a setting the owner changes to the agent that owns it, and keeps a typed API key out of every file.',
            children: [
              { id: 'pass', kind: 'step', name: 'Pass the setting on',
                in: 'setting',
                out: 'setting',
                does: 'Sends the change to the voice agent or the main agent. The agent that owns the setting applies it.'
              },
              { id: 'key', kind: 'step', name: 'Pass the typed API key on',
                in: 'setting',
                out: 'setting',
                does: 'Hands a typed key to the agent that owns it. The gateway keeps no key and never reads one back to a client.'
              }
            ]
          },
          { id: 'data', kind: 'group', name: 'Data',
            does: 'What the screens read, how events reach it, and how old data is cleaned or copied.',
            children: [
              { id: 'ingest', kind: 'group', name: 'Event ingest',
                code: 'services/gateway/src/thursday_gateway/application/ingest.py',
                does: 'Receives the agents\' events in batches and turns them into what the screens read.',
                children: [
                  { id: 'receive', kind: 'step', name: 'Receive a batch',
                    in: 'event',
                    out: 'event',
                    does: 'Takes a batch of events from an agent. Each event carries a source, a sequence number and a unique event_id.'
                  },
                  { id: 'filter', kind: 'group', name: 'Filtering',
                    does: 'Drops what must not be stored and ignores repeats.',
                    children: [
                      { id: 'chat_known', kind: 'decision', name: 'Chat still there?',
                        test: 'the event\'s chat exists and is not being deleted (or the event is global)',
                        branches: { 'yes': 'system.gateway.data.ingest.filter.is_new', 'otherwise': 'system.gateway.data.ingest.filter.drop' }
                      },
                      { id: 'drop', kind: 'step', name: 'Drop the event',
                        in: 'event',
                        out: 'none',
                        does: 'An event for a chat that is deleted, or being deleted, is discarded.',
                        stops: 'The event is discarded.'
                      },
                      { id: 'is_new', kind: 'decision', name: 'Seen before?',
                        test: 'the event_id has not been stored yet',
                        branches: { 'yes': 'system.gateway.data.ingest.store_event', 'otherwise': 'system.gateway.data.ingest.filter.ignore' }
                      },
                      { id: 'ignore', kind: 'step', name: 'Ignore the repeat',
                        in: 'event',
                        out: 'none',
                        does: 'Delivery from the agents is at least once, so a repeat is expected and changes nothing.',
                        stops: 'The repeat changes nothing.'
                      }
                    ]
                  },
                  { id: 'store_event', kind: 'step', name: 'Store in order',
                    in: 'event',
                    out: 'event',
                    does: 'Stores the event and keeps order by sequence number for each source.'
                  },
                  { id: 'is_approval', kind: 'decision', name: 'Approval request?',
                    test: 'the event is an approval request',
                    branches: { 'yes': 'system.gateway.data.ingest.notify', 'otherwise': 'system.gateway.data.ingest.project' }
                  },
                  { id: 'notify', kind: 'step', name: 'Raise the notification',
                    in: 'event',
                    out: 'notification',
                    does: 'Raises a plain notification itself, without waiting for the voice agent to say it.'
                  },
                  { id: 'project', kind: 'step', name: 'Update what screens read',
                    in: 'event',
                    out: 'event',
                    does: 'Adds the event to the timeline, messages, tasks and approvals that the clients read.'
                  }
                ]
              },
              { id: 'read', kind: 'group', name: 'Read model',
                code: 'services/gateway/src/thursday_gateway/infrastructure/read_model.py',
                does: 'Holds everything the clients read, in one place, so no client reads an agent.',
                choice: 'One read model in the gateway',
                why: 'Dashboards read one place, and no service waits on another.',
                rejected: [ 'Clients query each agent: every screen would depend on every service being up' ],
                children: [
                  { id: 'db', kind: 'store', name: 'Read database',
                    keeps: [ 'event', 'notification', 'metrics_sample' ],
                    does: 'Keeps the timeline, messages, tasks, approvals, notifications and the metrics history. Can be rebuilt from each agent\'s replay.',
                    rules: [ 'Working data is kept 30 days by default (7 days to 1 year, or until deleted); chat history until deleted' ]
                  },
                  { id: 'take_sample', kind: 'step', name: 'Take a metrics sample',
                    in: 'metrics_sample',
                    out: 'metrics_sample',
                    does: 'Stores each sample from the collector. History: every 5 seconds for 24 hours, then one a minute for 7 days by default.'
                  },
                  { id: 'answer_read', kind: 'step', name: 'Answer a read',
                    in: 'request',
                    out: 'view',
                    does: 'Serves a screen from the database: lists, search, a task\'s trace. Search matches the text as typed.'
                  },
                  { id: 'trace_long', kind: 'decision', name: 'Trace too long?',
                    test: 'a task\'s trace has more than 2,000 events',
                    branches: { 'yes': 'system.gateway.data.read.trim', 'otherwise': 'system.gateway.data.read.whole' }
                  },
                  { id: 'trim', kind: 'step', name: 'Trim the trace',
                    in: 'event',
                    out: 'view',
                    does: 'Returns the first and last half, with the number left out.'
                  },
                  { id: 'whole', kind: 'step', name: 'Return the whole trace',
                    in: 'event',
                    out: 'view',
                    does: 'Returns every event of the task.'
                  }
                ]
              },
              { id: 'keep', kind: 'group', name: 'Retention and backup',
                code: 'services/gateway/src/thursday_gateway/application/retention.py',
                does: 'Cleans old working data on every service and copies the chats and projects on request.',
                children: [
                  { id: 'minute', kind: 'event', name: 'Every minute',
                    trigger: 'The retention timer fires'
                  },
                  { id: 'send_period', kind: 'step', name: 'Send the retention period',
                    in: 'setting',
                    out: 'setting',
                    does: 'Sends the period the owner chose to each agent. Repeated once a minute until the agent confirms the period now in force.'
                  },
                  { id: 'period_set', kind: 'decision', name: 'Period confirmed?',
                    test: 'the agent answered with the period now in force',
                    branches: { 'yes': 'system.gateway.data.keep.purge', 'otherwise': 'system.gateway.data.keep.later' }
                  },
                  { id: 'later', kind: 'step', name: 'Try again next minute',
                    in: 'setting',
                    out: 'none',
                    does: 'The agent is down or has not caught up; the same request is sent at the next tick.',
                    stops: 'The next tick tries again.'
                  },
                  { id: 'purge', kind: 'step', name: 'Remove old working data',
                    in: 'none',
                    out: 'none',
                    does: 'Removes traces, saved task state and tool call logs older than the period. Chat history is kept until the owner deletes it.',
                    stops: 'Old working data is gone.'
                  },
                  { id: 'backup', kind: 'group', name: 'Backup',
                    does: 'Copies the chats and projects of every service into a folder.',
                    children: [
                      { id: 'backup_now', kind: 'step', name: 'Start a backup',
                        in: 'request',
                        out: 'request',
                        does: 'Makes a timestamped folder and asks each service to copy its chats and projects into it. Monitor history and tool call logs are not copied; .env and API keys never are.'
                      },
                      { id: 'all_copied', kind: 'decision', name: 'Everything copied?',
                        test: 'every service copied its chats and projects',
                        branches: { 'yes': 'system.gateway.data.keep.backup.prune', 'otherwise': 'system.gateway.data.keep.backup.incomplete' }
                      },
                      { id: 'incomplete', kind: 'step', name: 'Leave it incomplete',
                        in: 'request',
                        out: 'view',
                        does: 'The folder is marked incomplete and is never counted as a good copy.',
                        stops: 'The owner sees the backup is incomplete.'
                      },
                      { id: 'prune', kind: 'step', name: 'Keep the newest copies',
                        in: 'request',
                        out: 'view',
                        does: 'Writes the manifest, then removes older copies beyond the newest 7. The newest complete copy is never removed. Restoring is manual: stop everything, copy each service\'s .sqlite files into its data folder, delete any -wal and -shm files beside them, start again.',
                        rules: [ 'Tried on Linux: a project, a chat and the backup setting came back with the same ids in a fresh data folder' ],
                        stops: 'The owner sees the backup is complete.'
                      }
                    ]
                  }
                ]
              }
            ]
          },
          { id: 'status', kind: 'group', name: 'Dependency status',
            code: 'services/gateway/src/thursday_gateway/application/status.py',
            does: 'Tells clients which parts are up, without a false alarm.',
            choice: 'Two missed checks in a row, and a longer keep-alive',
            why: 'A check that landed on a connection the agent had just closed raised a false "not running" banner.',
            children: [
              { id: 'tick', kind: 'event', name: 'Every 5 seconds',
                trigger: 'The 5-second readiness timer fires'
              },
              { id: 'probe', kind: 'step', name: 'Ask each agent if it is ready',
                in: 'none',
                out: 'none',
                does: 'Asks the voice agent and the main agent. Services keep an unused connection for 30 seconds, longer than any caller does.'
              },
              { id: 'two_misses', kind: 'decision', name: 'Two misses in a row?',
                test: 'the same part missed two checks in a row',
                branches: { 'yes': 'system.gateway.status.banner', 'otherwise': 'system.gateway.status.quiet' }
              },
              { id: 'banner', kind: 'step', name: 'Raise the banner',
                in: 'none',
                out: 'view',
                does: 'Tells every client which part is not running; messages stay queued.'
              },
              { id: 'quiet', kind: 'step', name: 'Show nothing',
                in: 'none',
                out: 'none',
                does: 'One missed check shows nothing.',
                stops: 'No change on screen.'
              }
            ]
          },
          { id: 'boot', kind: 'step', name: 'Start up and answer health checks',
            in: 'none',
            out: 'none',
            does: 'Starts as a native process on localhost, answers /health and /ready, and exposes its numbers on /metrics.',
            stops: 'The service is running.'
          }
        ]
      },
      { id: 'voice', kind: 'group', name: 'Voice agent',
        code: 'services/voice_agent',
        does: 'Answers quickly, turns an instruction into a task for the main agent, and tells the owner how it went. Keeps its own conversation data.',
        children: [
          { id: 'conversation', kind: 'group', name: 'Conversation',
            does: 'Turns, spoken approvals, and listening.',
            children: [
              { id: 'turn', kind: 'group', name: 'Conversation turn',
                code: 'services/voice_agent/src/thursday_voice_agent/application/conversation.py',
                does: 'Runs one message through the voice model and streams the reply.',
                choice: 'A plain loop without saved steps',
                why: 'A turn is short; a repeated turn is answered from the stored reply.',
                rejected: [ 'The same checkpointed graph as the main agent: latency for no benefit' ],
                children: [
                  { id: 'gate', kind: 'group', name: 'Gate',
                    does: 'Checks the message before the model sees it.',
                    children: [
                      { id: 'receive', kind: 'step', name: 'Receive the message',
                        in: 'chat_message',
                        out: 'chat_message',
                        does: 'Takes a turn, or a direct message, from the gateway.'
                      },
                      { id: 'chat_gone', kind: 'decision', name: 'Chat deleted?',
                        test: 'the chat was deleted',
                        branches: { 'yes': 'system.voice.conversation.turn.gate.refuse_gone', 'otherwise': 'system.voice.conversation.spoken.is_answer' }
                      },
                      { id: 'refuse_gone', kind: 'step', name: 'Refuse with 410',
                        in: 'chat_message',
                        out: 'refusal',
                        does: 'A turn or direct message for a deleted chat is refused.',
                        stops: 'The gateway marks the message failed.'
                      },
                      { id: 'direct', kind: 'decision', name: 'Direct message?',
                        test: 'the message came on the direct route',
                        branches: { 'yes': 'system.voice.tasks.delegate.name_request', 'otherwise': 'system.voice.conversation.turn.seen' }
                      }
                    ]
                  },
                  { id: 'seen', kind: 'decision', name: 'Already answered?',
                    test: 'the client message id already has a stored reply',
                    branches: { 'yes': 'system.voice.conversation.turn.replay', 'otherwise': 'system.voice.conversation.turn.build_view' }
                  },
                  { id: 'replay', kind: 'step', name: 'Answer from the stored reply',
                    in: 'chat_message',
                    out: 'reply',
                    does: 'A repeated turn returns the stored reply without calling the model.'
                  },
                  { id: 'build_view', kind: 'step', name: 'Build what the model sees',
                    in: 'chat_message',
                    out: 'model_request',
                    does: 'The system prompt, the task tool, and the most recent messages.',
                    rules: [ 'At most the last 60 messages, fewer when a context limit is set', 'The window moves forward 20 messages at a time so the model server can reuse its work' ]
                  },
                  { id: 'hands_over', kind: 'decision', name: 'Hand work over?',
                    test: 'the model asks to start, pause, resume or stop a task',
                    branches: { 'start a task': 'system.voice.tasks.delegate.name_request', 'pause, resume or stop a task': 'system.voice.tasks.delegate.control', 'otherwise': 'system.voice.conversation.turn.store_reply' }
                  },
                  { id: 'store_reply', kind: 'step', name: 'Store the reply',
                    in: 'reply',
                    out: 'event',
                    does: 'Keeps the reply and the user message, and writes the events that tell the gateway.'
                  }
                ]
              },
              { id: 'spoken', kind: 'group', name: 'Spoken approval',
                code: 'services/voice_agent/src/thursday_voice_agent/domain/spoken.py',
                does: 'Answers a waiting approval from a typed or spoken yes or no.',
                choice: 'Code decides, not the model',
                why: 'An approval must never come out of model output.',
                children: [
                  { id: 'is_answer', kind: 'decision', name: 'A yes or no to a waiting approval?',
                    test: 'an approval is waiting in this chat and the whole message is a yes or no phrase ("yes", "allow always", "no")',
                    branches: { 'yes': 'system.voice.conversation.spoken.answer', 'otherwise': 'system.voice.conversation.turn.gate.direct' },
                    rules: [ 'The voice model has no approval tool' ]
                  },
                  { id: 'answer', kind: 'step', name: 'Answer the approval',
                    in: 'chat_message',
                    out: 'approval_answer',
                    does: 'Sends the owner\'s decision to the main agent and tells the gateway the words were an answer.'
                  }
                ]
              },
              { id: 'hear', kind: 'group', name: 'Listening',
                code: 'services/voice_agent/src/thursday_voice_agent/domain/audio.py',
                does: 'Lets the voice model write down a short recording itself, when it can hear.',
                children: [
                  { id: 'hear_in', kind: 'step', name: 'Receive a recording',
                    in: 'recording',
                    out: 'recording',
                    does: 'Takes a WAV clip from the gateway.'
                  },
                  { id: 'can_hear', kind: 'decision', name: 'Can the model hear this?',
                    test: 'the voice model can hear, the clip is 30 seconds or shorter, and words were heard',
                    branches: { 'yes': 'system.voice.conversation.hear.write_down', 'otherwise': 'system.voice.conversation.hear.say_409' }
                  },
                  { id: 'write_down', kind: 'step', name: 'Write down what is said',
                    in: 'recording',
                    out: 'transcript',
                    does: 'The voice model writes the words down. The chat still shows what was said, and spoken yes or no approvals work unchanged.'
                  },
                  { id: 'say_409', kind: 'step', name: 'Answer 409',
                    in: 'recording',
                    out: 'refusal',
                    does: '409 means "use speech-to-text instead".'
                  }
                ]
              }
            ]
          },
          { id: 'tasks', kind: 'group', name: 'Tasks',
            does: 'Handing work to the main agent and reporting back.',
            children: [
              { id: 'delegate', kind: 'group', name: 'Delegation',
                code: 'services/voice_agent/src/thursday_voice_agent/application/tasks.py',
                does: 'Starts, pauses, resumes and stops tasks on the main agent.',
                choice: 'Named requests',
                why: 'When the main agent\'s answer is lost, sending again must not start the work twice.',
                rejected: [ 'A fresh id per attempt: a lost answer created a duplicate task' ],
                children: [
                  { id: 'name_request', kind: 'step', name: 'Name the request',
                    in: 'chat_message',
                    out: 'task_request',
                    does: 'Works out a name from the chat, the message and its position. The push token is worked out from the name, so a repeat carries the same one. The project id and folder come from the gateway request, never from the model.'
                  },
                  { id: 'send_task', kind: 'step', name: 'Send the task',
                    in: 'task_request',
                    out: 'task_request',
                    does: 'Sends the task to the main agent and returns at once; the main agent pushes updates later.'
                  },
                  { id: 'known', kind: 'decision', name: 'Task new to us?',
                    test: 'the task is not yet recorded here',
                    branches: { 'yes': 'system.voice.tasks.delegate.record', 'otherwise': 'system.voice.tasks.delegate.already' }
                  },
                  { id: 'record', kind: 'step', name: 'Record and announce',
                    in: 'task_request',
                    out: 'event',
                    does: 'Records the task and announces it once.'
                  },
                  { id: 'already', kind: 'step', name: 'Add nothing',
                    in: 'task_request',
                    out: 'none',
                    does: 'A task that is already known is added once and announced once; a repeat changes nothing.',
                    stops: 'The repeat changes nothing.'
                  },
                  { id: 'control', kind: 'step', name: 'Pause, resume or stop',
                    in: 'task_control',
                    out: 'task_control',
                    does: 'Any task that has not ended can be chosen, however old it is.'
                  }
                ]
              },
              { id: 'report', kind: 'group', name: 'Task reports',
                code: 'services/voice_agent/src/thursday_voice_agent/domain/reports.py',
                does: 'Receives task updates from the main agent and puts them into the chat.',
                children: [
                  { id: 'check', kind: 'group', name: 'Checks',
                    does: 'Checks a pushed update before it is reported.',
                    children: [
                      { id: 'push_in', kind: 'step', name: 'Receive an update',
                        in: 'task_update',
                        out: 'task_update',
                        does: 'Updates arrive on a push webhook, with a short summary; the full output is fetched from the main agent.'
                      },
                      { id: 'token_ok', kind: 'decision', name: 'Right token?',
                        test: 'the update carries the task\'s push token',
                        branches: { 'yes': 'system.voice.tasks.report.check.chat_alive', 'otherwise': 'system.voice.tasks.report.check.reject' }
                      },
                      { id: 'reject', kind: 'step', name: 'Refuse the update',
                        in: 'task_update',
                        out: 'refusal',
                        does: 'Only the task\'s own token is accepted.',
                        stops: 'The update is ignored.'
                      },
                      { id: 'chat_alive', kind: 'decision', name: 'Chat still there?',
                        test: 'the chat still exists',
                        branches: { 'yes': 'system.voice.tasks.report.narrate', 'otherwise': 'system.voice.tasks.report.check.drop' }
                      },
                      { id: 'drop', kind: 'step', name: 'Drop the report',
                        in: 'task_update',
                        out: 'none',
                        does: 'A report that finishes after its chat was deleted is dropped.',
                        stops: 'The report is dropped.'
                      }
                    ]
                  },
                  { id: 'narrate', kind: 'step', name: 'Tell the owner how it went',
                    in: 'task_update',
                    out: 'reply',
                    does: 'The voice model writes a short report of the task\'s state or result. For a direct task it only reports.'
                  },
                  { id: 'report_ok', kind: 'decision', name: 'Report trustworthy?',
                    test: 'the model\'s report can be trusted',
                    branches: { 'yes': 'system.voice.tasks.report.say', 'otherwise': 'system.voice.tasks.report.fallback' }
                  },
                  { id: 'fallback', kind: 'step', name: 'Use the main agent\'s words',
                    in: 'task_update',
                    out: 'reply',
                    does: 'Code falls back to the main agent\'s own words.'
                  },
                  { id: 'say', kind: 'step', name: 'Put it into the chat',
                    in: 'reply',
                    out: 'event',
                    does: 'Stores the report as the assistant\'s message and tells the gateway.'
                  }
                ]
              }
            ]
          },
          { id: 'store', kind: 'store', name: 'Voice store',
            keeps: [ 'chat_message', 'reply', 'setting' ],
            does: 'Keeps what the voice agent owns, in its own SQLite file: the conversation, tasks, settings, and a "this chat was deleted" note kept for 7 days.',
            rules: [ 'Owned by this service alone', 'Nothing is written for a deleted chat', 'Forward-only migrations, with a backup before each' ]
          },
          { id: 'events', kind: 'group', name: 'Events',
            does: 'The outbox and the sender that empties it.',
            children: [
              { id: 'outbox', kind: 'queue', name: 'Event outbox',
                capacity: 'no limit',
                when_full: 'not applicable: the file only grows with the unsent events',
                code: 'packages/runtime/src/thursday_runtime/outbox.py',
                does: 'Holds the voice agent\'s events, in order, until the gateway has them. Every event is written here first; a background sender delivers them, with backoff. The gateway can ask for "my events since N" again.',
                choice: 'Outbox with a sender',
                why: 'A service must never wait on the gateway to do its own work.',
                rejected: [ 'Call the gateway directly: an agent would stall whenever the gateway was down', 'Cap the unsent events and drop the oldest: the screens would have a gap in their history' ],
                rules: [ 'No limit on unsent events: each event is size-capped (20,000 characters a part), the gateway runs on the same PC, and the backlog is reported in the agent\'s status as outbox_backlog' ]
              },
              { id: 'sender', kind: 'step', name: 'Send events in order',
                in: 'event',
                out: 'event',
                does: 'Delivers batches to the gateway, retrying with backoff. Delivered events are removed after the retention period.'
              }
            ]
          },
          { id: 'plumbing', kind: 'group', name: 'Housekeeping',
            does: 'Start-up, numbers, deleting a chat, retention and backup.',
            children: [
              { id: 'forget', kind: 'step', name: 'Delete a chat',
                in: 'request',
                out: 'view',
                does: 'Notes the chat as deleted (kept 7 days), removes what the agent holds, and refuses any new work for it. Asking again is safe.'
              },
              { id: 'retention', kind: 'step', name: 'Apply the retention period',
                in: 'setting',
                out: 'setting',
                does: 'Keeps the period the gateway sent, answers with the period now in force, and removes working data older than it.'
              },
              { id: 'backup', kind: 'step', name: 'Copy its chats',
                in: 'request',
                out: 'view',
                does: 'Copies the chats and projects it holds into the backup folder.'
              },
              { id: 'numbers', kind: 'step', name: 'Answer a request for numbers',
                in: 'none',
                out: 'metrics_sample',
                does: 'Gives the collector this service\'s numbers on /metrics.'
              },
              { id: 'boot', kind: 'step', name: 'Start up and answer health checks',
                in: 'none',
                out: 'none',
                does: 'Starts as a native process on localhost, answers /health and /ready, and exposes its numbers on /metrics.',
                stops: 'The service is running.'
              }
            ]
          },
          { id: 'llm', kind: 'group', name: 'Model runtime',
            code: 'packages/llm',
            does: 'Holds the voice agent\'s model settings and provider. It is the only way the agent calls a model.',
            choice: 'Each agent owns its settings',
            why: 'An agent keeps working, with the right settings, while the gateway is down.',
            children: [
              { id: 'change', kind: 'group', name: 'Changing settings',
                does: 'Applies a saved setting, a typed key, Unload or Reload, unless a call is running.',
                children: [
                  { id: 'settings_in', kind: 'step', name: 'Receive a change',
                    in: 'setting',
                    out: 'setting',
                    does: 'A saved setting, a typed API key, Unload, or Reload arrives from the gateway.'
                  },
                  { id: 'call_running', kind: 'decision', name: 'A call running?',
                    test: 'a model call is running',
                    branches: { 'yes': 'system.voice.llm.change.refuse_busy', 'otherwise': 'system.voice.llm.change.apply' }
                  },
                  { id: 'refuse_busy', kind: 'step', name: 'Refuse the change',
                    in: 'setting',
                    out: 'refusal',
                    does: 'Answers 409 "The model is in use right now. Try again when it has finished." Nothing is changed.',
                    choice: 'Refuse, do not queue the change',
                    why: 'Rebuilding closes the provider, and for the built-in llama.cpp that stops the server under the running call.',
                    rejected: [ 'Apply the change after the call: the owner would not know when it took effect', 'Let the change through: it killed the model server in the middle of an answer' ],
                    stops: 'The owner sees the refusal.'
                  },
                  { id: 'apply', kind: 'step', name: 'Apply the change',
                    in: 'setting',
                    out: 'setting',
                    does: 'Keeps the setting in the agent\'s own database and a typed key in the system credential store. The model and the address are remembered per provider; switching provider never carries them over. Load settings apply at the next load; answer settings at the next call.',
                    rules: [ 'A key is stored for one agent and one provider', 'A key is never returned: clients learn only "set" or "held back"', 'Starting values come from .env' ]
                  }
                ]
              },
              { id: 'prepare', kind: 'step', name: 'Work out the call',
                in: 'model_request',
                out: 'model_request',
                does: 'Chooses the provider, the model and the answer settings in force for this call, and waits if a change is being applied.'
              },
              { id: 'key_fits', kind: 'decision', name: 'Key fits the address?',
                test: 'the stored key was typed for the address the call goes to',
                branches: { 'yes': 'system.voice.llm.call', 'otherwise': 'system.voice.llm.call_no_key' },
                choice: 'Tie the key to its address',
                why: 'Pointing an agent at another server must not hand that server the old one\'s key.',
                rejected: [ 'Tie the key to the provider only: a changed address received the stored key' ]
              },
              { id: 'call_no_key', kind: 'step', name: 'Call without a key',
                in: 'model_request',
                out: 'model_response',
                does: 'Calls the endpoint with no key; the key is held back until it is typed again for this address.'
              },
              { id: 'call', kind: 'step', name: 'Call the model',
                in: 'model_request',
                out: 'model_response',
                does: 'Streams one call to the provider and keeps the response, not the stream. Measures time to first token (request to the first piece with text or a tool call) and tokens per second (output tokens over the time the model was generating, thinking included).',
                rules: [ 'Three tries with increasing delays when the endpoint fails', 'Nothing is loaded when the service starts; the model loads on the first call' ]
              },
              { id: 'unloading', kind: 'group', name: 'Idle unload',
                does: 'Frees the hardware when nobody has used the model for a while.',
                children: [
                  { id: 'tick', kind: 'event', name: 'Every 15 seconds',
                    trigger: 'The idle check timer fires'
                  },
                  { id: 'idle', kind: 'decision', name: 'Idle too long?',
                    test: 'a model is loaded, no call is running, and it has been idle longer than the limit (0 keeps it loaded)',
                    branches: { 'yes': 'system.voice.llm.unloading.unload', 'otherwise': 'system.voice.llm.unloading.stay' },
                    choice: 'Unload by the agent, not by the model server',
                    why: 'A stopped llama.cpp process really releases the GPU; llama.cpp\'s own idle sleep does not.',
                    rules: [ 'Default 5 minutes for each agent', 'A model counts as in use for the whole of every call, loading included' ]
                  },
                  { id: 'unload', kind: 'step', name: 'Unload the model',
                    in: 'setting',
                    out: 'setting',
                    does: 'Unloads the model so the hardware is free while the services keep running. A failed unload is tried again on the next pass.',
                    stops: 'The hardware is free until the next call loads the model again.'
                  },
                  { id: 'stay', kind: 'step', name: 'Leave it loaded',
                    in: 'none',
                    out: 'none',
                    does: 'The model stays loaded.',
                    stops: 'No change.'
                  }
                ]
              }
            ]
          }
        ]
      },
      { id: 'main', kind: 'group', name: 'Main agent',
        code: 'services/main_agent',
        does: 'Runs each delegated task, with its model calls, tool calls and approvals, until there is a result. Keeps its own task data.',
        children: [
          { id: 'door', kind: 'group', name: 'A2A server',
            code: 'services/main_agent/src/thursday_main_agent/transport',
            does: 'Accepts tasks, task control and approval answers over the A2A protocol.',
            choice: 'A2A between the agents',
            why: 'A clean protocol boundary: the main agent can be replaced or used by another front.',
            children: [
              { id: 'tasks', kind: 'group', name: 'Tasks in',
                does: 'Accepts a new task and recognises a repeat.',
                children: [
                  { id: 'accept', kind: 'step', name: 'Accept a task',
                    in: 'task_request',
                    out: 'task_request',
                    does: 'Takes a task from the voice agent or, in direct mode, from the gateway. The project id and folder arrive as metadata.'
                  },
                  { id: 'chat_exists', kind: 'decision', name: 'Chat deleted?',
                    test: 'the chat was deleted',
                    branches: { 'yes': 'system.main.door.tasks.refuse_deleted', 'otherwise': 'system.main.door.tasks.known' }
                  },
                  { id: 'refuse_deleted', kind: 'step', name: 'Refuse the task',
                    in: 'task_request',
                    out: 'refusal',
                    does: 'A new task for a deleted chat is refused.',
                    stops: 'The sender is told the chat was deleted.'
                  },
                  { id: 'known', kind: 'decision', name: 'Name already accepted?',
                    test: 'the request name was already accepted',
                    branches: { 'yes': 'system.main.door.tasks.existing', 'otherwise': 'system.main.door.tasks.create' }
                  },
                  { id: 'existing', kind: 'step', name: 'Answer with the existing task',
                    in: 'task_request',
                    out: 'task_update',
                    does: 'A request that was already accepted gets the task that exists, so a repeat never starts the work twice.'
                  },
                  { id: 'create', kind: 'step', name: 'Create the task',
                    in: 'task_request',
                    out: 'task_request',
                    does: 'Stores the name with the task in one transaction. If two requests with the same name arrive at once, the second ends failed without running.'
                  }
                ]
              },
              { id: 'controls', kind: 'group', name: 'Controls in',
                does: 'Accepts a pause, resume, stop or approval answer.',
                children: [
                  { id: 'control_in', kind: 'step', name: 'Accept a control',
                    in: 'task_control',
                    out: 'task_control',
                    does: 'Pause, resume and stop. Pause and resume are an extension to the protocol; stop is the standard cancel.'
                  },
                  { id: 'answer_in', kind: 'step', name: 'Accept an approval answer',
                    in: 'approval_answer',
                    out: 'approval_answer',
                    does: 'Takes allow once, allow always or deny for a waiting approval.'
                  },
                  { id: 'answer_waiting', kind: 'decision', name: 'Still waiting?',
                    test: 'the approval is still waiting',
                    branches: { 'yes': 'system.main.work.ask.owner_answers.record_answer', 'otherwise': 'system.main.door.controls.resolved' }
                  },
                  { id: 'resolved', kind: 'step', name: 'Say it was already answered',
                    in: 'approval_answer',
                    out: 'refusal',
                    does: 'The first answer wins; a second one gets an "already resolved" error.',
                    stops: 'The sender is told the approval was already answered.'
                  }
                ]
              }
            ]
          },
          { id: 'work', kind: 'group', name: 'Running a task',
            does: 'Task turns, the loop, approvals and tool servers.',
            children: [
              { id: 'line', kind: 'queue', name: 'Task turns',
                capacity: 1,
                when_full: 'wait in order; a task waiting for an approval lets go of its turn',
                choice: 'One at a time',
                why: 'Tasks would otherwise share one context window.',
                does: 'Lets tasks take turns on the model. One task runs; the others wait in order.'
              },
              { id: 'loop', kind: 'group', name: 'Agent loop',
                code: 'services/main_agent/src/thursday_main_agent/application/runner.py',
                does: 'Runs a task step by step until the model gives a result.',
                children: [
                  { id: 'prepare', kind: 'group', name: 'Before the call',
                    does: 'Builds the view, checks for a pause, and keeps it inside the window.',
                    children: [
                      { id: 'start', kind: 'step', name: 'Build the task\'s view',
                        in: 'task_request',
                        out: 'model_request',
                        does: 'The system prompt, the chat summary, the earlier tasks as instruction, tool log and final message, and this instruction.'
                      },
                      { id: 'awake', kind: 'step', name: 'Keep the PC awake',
                        in: 'none',
                        out: 'none',
                        does: 'Asks the PC not to sleep while a task runs, so the phone can still reach it. Stops asking when no task runs.',
                        rules: [ 'Windows: a power request', 'Linux with systemd: an inhibitor lock held by a systemd-inhibit process, for sleep and idle, or for idle alone where the session may not block sleep', 'Elsewhere (macOS): nothing is requested' ],
                        stops: 'The PC is asked not to sleep.'
                      },
                      { id: 'pause_asked', kind: 'decision', name: 'Pause asked?',
                        test: 'a pause was asked',
                        branches: { 'yes': 'system.main.work.loop.prepare.hold', 'otherwise': 'system.main.work.loop.prepare.fits' }
                      },
                      { id: 'hold', kind: 'step', name: 'Hold at the top of the step',
                        in: 'task_control',
                        out: 'event',
                        does: 'A pause takes effect at the top of a step, never in the middle. The task stays working, flagged paused.',
                        stops: 'The task waits until the owner resumes or stops it.'
                      },
                      { id: 'fits', kind: 'decision', name: 'View fits?',
                        test: 'the view is under the agent\'s token limit and under 90 percent of the loaded window',
                        branches: { 'yes': 'system.main.work.loop.ask_model.call', 'otherwise': 'system.main.work.loop.prepare.compact' },
                        choice: 'A token limit per agent',
                        why: 'A percentage could never trigger on an endpoint that reports no window.',
                        rejected: [ 'OpenAI\'s server-side compaction: not available on local endpoints' ]
                      },
                      { id: 'compact', kind: 'step', name: 'Summarise older turns',
                        in: 'model_request',
                        out: 'model_request',
                        does: 'Summarises the older turns for the model and adds a marker to the timeline. A cloud endpoint reports no window, so the token limit is the only trigger there.'
                      }
                    ]
                  },
                  { id: 'ask_model', kind: 'group', name: 'The model call',
                    does: 'Calls the model and handles a failed or full-window call.',
                    children: [
                      { id: 'call', kind: 'step', name: 'Ask the model',
                        in: 'model_request',
                        out: 'model_response',
                        does: 'Sends the task\'s view to the model through the model runtime.'
                      },
                      { id: 'call_ok', kind: 'decision', name: 'Did the call work?',
                        test: 'the model answered',
                        branches: { 'yes': 'system.main.work.loop.tools.wants_tools', 'the window is full': 'system.main.work.loop.ask_model.compact_harder', 'otherwise': 'system.main.work.loop.ask_model.fail_task' }
                      },
                      { id: 'compact_harder', kind: 'step', name: 'Compact harder and try once more',
                        in: 'model_request',
                        out: 'model_request',
                        does: 'A full window is handled by compacting harder and trying the call once more.'
                      },
                      { id: 'fail_task', kind: 'step', name: 'Fail the task',
                        in: 'model_response',
                        out: 'task_update',
                        does: 'After the last try the task fails and the owner is notified.'
                      }
                    ]
                  },
                  { id: 'tools', kind: 'group', name: 'Tool calls',
                    does: 'Runs, reuses or reports each tool call the model asked for.',
                    children: [
                      { id: 'wants_tools', kind: 'decision', name: 'Tools asked for?',
                        test: 'the model asked for tool calls',
                        branches: { 'yes': 'system.main.work.loop.tools.mark', 'otherwise': 'system.main.work.loop.finish' }
                      },
                      { id: 'mark', kind: 'decision', name: 'Run before?',
                        test: 'what is stored for this call (marked by task, step and position)',
                        branches: { 'nothing yet': 'system.main.work.loop.tools.send_call', 'it finished': 'system.main.work.loop.tools.from_mark', 'otherwise': 'system.main.work.loop.tools.unknown' },
                        choice: 'Run-once marks',
                        why: 'After a restart the loop must not repeat a command that may already have run.'
                      },
                      { id: 'from_mark', kind: 'step', name: 'Answer from the stored result',
                        in: 'tool_call',
                        out: 'tool_result',
                        does: 'A call that finished is answered from its stored result and not run again.'
                      },
                      { id: 'unknown', kind: 'step', name: 'Report "outcome unknown"',
                        in: 'tool_call',
                        out: 'tool_result',
                        does: 'A call that started without a result is reported as "outcome unknown, verify first" and never re-run blindly.'
                      },
                      { id: 'send_call', kind: 'step', name: 'Send the call',
                        in: 'tool_call',
                        out: 'tool_call',
                        does: 'Writes the mark first, then sends the call to the tool server through the manager.'
                      },
                      { id: 'got_result', kind: 'step', name: 'Keep the result',
                        in: 'tool_result',
                        out: 'tool_result',
                        does: 'Marks the call finished and stores its result.'
                      }
                    ]
                  },
                  { id: 'cancelled', kind: 'step', name: 'Cancel the task',
                    in: 'task_control',
                    out: 'task_update',
                    does: 'Stop cancels at once, including a running tool, and the task ends cancelled.'
                  },
                  { id: 'save', kind: 'step', name: 'Save the step',
                    in: 'model_response',
                    out: 'none',
                    does: 'Saves everything the loop knows after every step. After a restart the task continues from its last step.'
                  },
                  { id: 'finish', kind: 'step', name: 'Finish the task',
                    in: 'model_response',
                    out: 'task_update',
                    does: 'Stores the final message, pushes the result to the voice agent, and lets go of the model\'s turn.'
                  }
                ]
              },
              { id: 'ask', kind: 'group', name: 'Approval wait',
                code: 'services/main_agent/src/thursday_main_agent/domain/approvals.py',
                does: 'Waits for the owner\'s answer when a tool needs one.',
                choice: 'Allow-always rules live in the main agent',
                why: 'Approvals must not depend on the gateway being up.',
                children: [
                  { id: 'rule_exists', kind: 'decision', name: 'Allowed always?',
                    test: 'an allow-always rule exists for this chat and this tool',
                    branches: { 'yes': 'system.main.work.ask.owner_answers.resume_call', 'otherwise': 'system.main.work.ask.ask_owner' }
                  },
                  { id: 'ask_owner', kind: 'step', name: 'Ask the owner',
                    in: 'approval_request',
                    out: 'approval_request',
                    does: 'Marks the task as needing input, tells the clients, and lets go of the model\'s turn while it waits.'
                  },
                  { id: 'timeout', kind: 'group', name: 'No answer',
                    does: 'Handles an approval that nobody answers.',
                    children: [
                      { id: 'wait_ends', kind: 'event', name: 'The wait runs out',
                        trigger: 'The 300-second wait for an answer runs out'
                      },
                      { id: 'time_out', kind: 'step', name: 'Cancel the request',
                        in: 'approval_request',
                        out: 'tool_result',
                        does: 'Cancels the request and tells the model the owner did not respond; it may try a different approach.'
                      },
                      { id: 'two_in_row', kind: 'decision', name: 'Two timeouts in a row?',
                        test: 'this is the second timeout in a row',
                        branches: { 'yes': 'system.main.work.ask.timeout.pause_notify', 'otherwise': 'system.main.work.loop.tools.got_result' }
                      },
                      { id: 'pause_notify', kind: 'step', name: 'Pause and notify',
                        in: 'approval_request',
                        out: 'event',
                        does: 'Pauses the task and notifies the owner.',
                        stops: 'The task waits until the owner resumes or stops it.'
                      }
                    ]
                  },
                  { id: 'owner_answers', kind: 'group', name: 'The owner answers',
                    does: 'Takes the owner\'s answer and acts on it.',
                    children: [
                      { id: 'answered', kind: 'decision', name: 'What did the owner say?',
                        test: 'the owner answered within 300 seconds',
                        branches: { 'allow once': 'system.main.work.ask.owner_answers.resume_call', 'allow always': 'system.main.work.ask.owner_answers.remember', 'deny': 'system.main.work.ask.owner_answers.tell_denied', 'otherwise': 'system.main.work.ask.timeout.time_out' }
                      },
                      { id: 'record_answer', kind: 'step', name: 'Take the answer',
                        in: 'approval_answer',
                        out: 'approval_answer',
                        does: 'Records the first answer; later ones are refused.'
                      },
                      { id: 'remember', kind: 'step', name: 'Keep the rule',
                        in: 'approval_answer',
                        out: 'approval_answer',
                        does: 'Keeps an allow-always rule for this chat and this tool. The rule applies only in that chat.'
                      },
                      { id: 'resume_call', kind: 'step', name: 'Run the call',
                        in: 'approval_answer',
                        out: 'tool_call',
                        does: 'Runs the tool call again with the approval attached.'
                      },
                      { id: 'tell_denied', kind: 'step', name: 'Tell the model it was refused',
                        in: 'approval_answer',
                        out: 'tool_result',
                        does: 'The model is told the owner refused, so it can try something else.'
                      }
                    ]
                  }
                ]
              },
              { id: 'mcp', kind: 'group', name: 'Tool server manager',
                code: 'services/main_agent/src/thursday_main_agent/infrastructure/mcp_manager.py',
                does: 'Starts and talks to tool servers over MCP.',
                children: [
                  { id: 'running', kind: 'decision', name: 'Server running?',
                    test: 'a tool server is running for this project',
                    branches: { 'yes': 'system.main.work.mcp.call_tool', 'otherwise': 'system.main.work.mcp.start_server' }
                  },
                  { id: 'start_server', kind: 'step', name: 'Start a tool server',
                    in: 'none',
                    out: 'none',
                    does: 'Starts a tool server for the project on demand, over standard input and output, with the project folder as its root.',
                    choice: 'One built-in tool server in version 1',
                    why: 'A second tool server needs its own permission rules, and they are not designed.',
                    rejected: [ 'A second MCP server of the owner\'s own in version 1: left out until its permission rules are designed' ]
                  },
                  { id: 'call_tool', kind: 'step', name: 'Call the tool',
                    in: 'tool_call',
                    out: 'tool_call',
                    does: 'Sends the call. The chat id travels beside the arguments and is only recorded.'
                  },
                  { id: 'tick', kind: 'event', name: 'Every minute',
                    trigger: 'The idle check for tool servers fires'
                  },
                  { id: 'idle', kind: 'decision', name: 'Server idle?',
                    test: 'a server has been idle longer than the limit (10 minutes) and has no open shell session',
                    branches: { 'yes': 'system.main.work.mcp.stop_server', 'otherwise': 'system.main.work.mcp.keep' }
                  },
                  { id: 'stop_server', kind: 'step', name: 'Stop the server',
                    in: 'none',
                    out: 'none',
                    does: 'Stops the tool server to free the memory.',
                    stops: 'The server is stopped; the next call starts it again.'
                  },
                  { id: 'keep', kind: 'step', name: 'Keep the server',
                    in: 'none',
                    out: 'none',
                    does: 'A server with an open shell session is not stopped.',
                    stops: 'No change.'
                  }
                ]
              }
            ]
          },
          { id: 'state', kind: 'group', name: 'State',
            does: 'Tasks, approvals, allow-always rules and saved steps.',
            children: [
              { id: 'store', kind: 'store', name: 'Main store',
                keeps: [ 'task_request', 'approval_request', 'approval_answer', 'setting' ],
                does: 'Keeps what the main agent owns, in its own SQLite file: tasks, approvals, allow-always rules and settings.',
                rules: [ 'Owned by this service alone', 'The "this chat was deleted" note is kept 7 days; nothing is written for that chat again' ]
              },
              { id: 'checkpoints', kind: 'store', name: 'Saved steps',
                keeps: [ 'model_response', 'tool_result' ],
                does: 'Keeps one saved thread for each task, so a restart continues from the last step. Removed with the chat, and for finished tasks after the retention period.'
              }
            ]
          },
          { id: 'plumbing', kind: 'group', name: 'Housekeeping',
            does: 'Start-up, numbers, deleting a chat, retention and backup.',
            children: [
              { id: 'forget', kind: 'group', name: 'Deleting a chat',
                code: 'services/main_agent/src/thursday_main_agent/application/deletion.py',
                does: 'Removes what the agent holds for a deleted chat, in an order that a repeat can finish.',
                children: [
                  { id: 'note_deleted', kind: 'step', name: 'Note the chat as deleted',
                    in: 'request',
                    out: 'request',
                    does: 'From now on nothing is written for this chat.'
                  },
                  { id: 'remove_saved', kind: 'step', name: 'Remove the saved steps',
                    in: 'request',
                    out: 'request',
                    does: 'Removes the saved thread of each task of the chat.'
                  },
                  { id: 'remove_records', kind: 'step', name: 'Remove the task records last',
                    in: 'request',
                    out: 'view',
                    does: 'Last, so asking again can finish a delete that failed half-way.',
                    stops: 'The gateway is told the chat is gone.'
                  }
                ]
              },
              { id: 'retention', kind: 'step', name: 'Apply the retention period',
                in: 'setting',
                out: 'setting',
                does: 'Keeps the period the gateway sent, answers with the period now in force, and removes finished tasks\' saved state older than it.'
              },
              { id: 'backup', kind: 'step', name: 'Copy its tasks',
                in: 'request',
                out: 'view',
                does: 'Copies the chats and projects it holds into the backup folder.'
              },
              { id: 'numbers', kind: 'step', name: 'Answer a request for numbers',
                in: 'none',
                out: 'metrics_sample',
                does: 'Gives the collector this service\'s numbers on /metrics.'
              },
              { id: 'boot', kind: 'step', name: 'Start up and answer health checks',
                in: 'none',
                out: 'none',
                does: 'Starts as a native process on localhost, answers /health and /ready, and exposes its numbers on /metrics.',
                stops: 'The service is running.'
              }
            ]
          },
          { id: 'events', kind: 'group', name: 'Events',
            does: 'The outbox and the sender that empties it.',
            children: [
              { id: 'outbox', kind: 'queue', name: 'Event outbox',
                capacity: 'no limit',
                when_full: 'not applicable: the file only grows with the unsent events',
                code: 'packages/runtime/src/thursday_runtime/outbox.py',
                does: 'Holds the main agent\'s events, in order, until the gateway has them. Every event is written here first; a background sender delivers them with backoff.',
                choice: 'Outbox with a sender',
                why: 'A service must never wait on the gateway to do its own work.',
                rejected: [ 'Call the gateway directly: an agent would stall whenever the gateway was down', 'Cap the unsent events and drop the oldest: the screens would have a gap in their history' ],
                rules: [ 'No limit on unsent events: each event is size-capped (20,000 characters a part), the gateway runs on the same PC, and the backlog is reported in the agent\'s status as outbox_backlog' ]
              },
              { id: 'sender', kind: 'step', name: 'Send events in order',
                in: 'event',
                out: 'event',
                does: 'Delivers batches to the gateway, retrying with backoff. The gateway can ask again for "my events since N".'
              }
            ]
          },
          { id: 'llm', kind: 'group', name: 'Model runtime',
            code: 'packages/llm',
            does: 'Holds the main agent\'s model settings and provider. It is the only way the agent calls a model.',
            choice: 'Each agent owns its settings',
            why: 'An agent keeps working, with the right settings, while the gateway is down.',
            children: [
              { id: 'change', kind: 'group', name: 'Changing settings',
                does: 'Applies a saved setting, a typed key, Unload or Reload, unless a call is running.',
                children: [
                  { id: 'settings_in', kind: 'step', name: 'Receive a change',
                    in: 'setting',
                    out: 'setting',
                    does: 'A saved setting, a typed API key, Unload, or Reload arrives from the gateway.'
                  },
                  { id: 'call_running', kind: 'decision', name: 'A call running?',
                    test: 'a model call is running',
                    branches: { 'yes': 'system.main.llm.change.refuse_busy', 'otherwise': 'system.main.llm.change.apply' }
                  },
                  { id: 'refuse_busy', kind: 'step', name: 'Refuse the change',
                    in: 'setting',
                    out: 'refusal',
                    does: 'Answers 409 "The model is in use right now. Try again when it has finished." Nothing is changed.',
                    choice: 'Refuse, do not queue the change',
                    why: 'Rebuilding closes the provider, and for the built-in llama.cpp that stops the server under the running call.',
                    rejected: [ 'Apply the change after the call: the owner would not know when it took effect', 'Let the change through: it killed the model server in the middle of an answer' ],
                    stops: 'The owner sees the refusal.'
                  },
                  { id: 'apply', kind: 'step', name: 'Apply the change',
                    in: 'setting',
                    out: 'setting',
                    does: 'Keeps the setting in the agent\'s own database and a typed key in the system credential store. The model and the address are remembered per provider; switching provider never carries them over. Load settings apply at the next load; answer settings at the next call.',
                    rules: [ 'A key is stored for one agent and one provider', 'A key is never returned: clients learn only "set" or "held back"', 'Starting values come from .env' ]
                  }
                ]
              },
              { id: 'prepare', kind: 'step', name: 'Work out the call',
                in: 'model_request',
                out: 'model_request',
                does: 'Chooses the provider, the model and the answer settings in force for this call, and waits if a change is being applied.'
              },
              { id: 'key_fits', kind: 'decision', name: 'Key fits the address?',
                test: 'the stored key was typed for the address the call goes to',
                branches: { 'yes': 'system.main.llm.call', 'otherwise': 'system.main.llm.call_no_key' },
                choice: 'Tie the key to its address',
                why: 'Pointing an agent at another server must not hand that server the old one\'s key.',
                rejected: [ 'Tie the key to the provider only: a changed address received the stored key' ]
              },
              { id: 'call_no_key', kind: 'step', name: 'Call without a key',
                in: 'model_request',
                out: 'model_response',
                does: 'Calls the endpoint with no key; the key is held back until it is typed again for this address.'
              },
              { id: 'call', kind: 'step', name: 'Call the model',
                in: 'model_request',
                out: 'model_response',
                does: 'Streams one call to the provider and keeps the response, not the stream. Measures time to first token (request to the first piece with text or a tool call) and tokens per second (output tokens over the time the model was generating, thinking included).',
                rules: [ 'Three tries with increasing delays when the endpoint fails', 'Nothing is loaded when the service starts; the model loads on the first call' ]
              },
              { id: 'unloading', kind: 'group', name: 'Idle unload',
                does: 'Frees the hardware when nobody has used the model for a while.',
                children: [
                  { id: 'tick', kind: 'event', name: 'Every 15 seconds',
                    trigger: 'The idle check timer fires'
                  },
                  { id: 'idle', kind: 'decision', name: 'Idle too long?',
                    test: 'a model is loaded, no call is running, and it has been idle longer than the limit (0 keeps it loaded)',
                    branches: { 'yes': 'system.main.llm.unloading.unload', 'otherwise': 'system.main.llm.unloading.stay' },
                    choice: 'Unload by the agent, not by the model server',
                    why: 'A stopped llama.cpp process really releases the GPU; llama.cpp\'s own idle sleep does not.',
                    rules: [ 'Default 5 minutes for each agent', 'A model counts as in use for the whole of every call, loading included' ]
                  },
                  { id: 'unload', kind: 'step', name: 'Unload the model',
                    in: 'setting',
                    out: 'setting',
                    does: 'Unloads the model so the hardware is free while the services keep running. A failed unload is tried again on the next pass.',
                    stops: 'The hardware is free until the next call loads the model again.'
                  },
                  { id: 'stay', kind: 'step', name: 'Leave it loaded',
                    in: 'none',
                    out: 'none',
                    does: 'The model stays loaded.',
                    stops: 'No change.'
                  }
                ]
              }
            ]
          }
        ]
      },
      { id: 'tools', kind: 'group', name: 'Tool server',
        code: 'services/tool_server',
        does: 'Runs the tools. Enforces the folder boundary for files, the approval for risky tools, and the deny list. The main agent starts one per project, on demand.',
        children: [
          { id: 'policy', kind: 'group', name: 'Permission policy',
            code: 'services/tool_server/src/thursday_tool_server/domain/policy.py',
            does: 'Decides for each tool whether it runs, asks, or is refused. Fixed in code: no prompt can change it.',
            choice: 'Policy in the tool server',
            why: 'The server that runs a tool is the one place that cannot be talked out of the rule.',
            children: [
              { id: 'sort', kind: 'group', name: 'Sorting the call',
                does: 'Tells apart a retry, a shell command, a file tool and an unknown tool.',
                children: [
                  { id: 'receive', kind: 'step', name: 'Receive the call',
                    in: 'tool_call',
                    out: 'tool_call',
                    does: 'Takes a call from the main agent over MCP, with the chat id as metadata.'
                  },
                  { id: 'is_retry', kind: 'decision', name: 'Carries an answer?',
                    test: 'the call carries an approval answer',
                    branches: { 'yes': 'system.tools.policy.answer_back', 'otherwise': 'system.tools.policy.sort.is_shell' }
                  },
                  { id: 'is_shell', kind: 'decision', name: 'A shell command?',
                    test: 'the tool is the shell or a shell session command',
                    branches: { 'yes': 'system.tools.deny.check_before', 'otherwise': 'system.tools.policy.sort.is_file' }
                  },
                  { id: 'is_file', kind: 'decision', name: 'A file tool?',
                    test: 'the tool is a file tool',
                    branches: { 'yes': 'system.tools.box.inside', 'otherwise': 'system.tools.policy.sort.unknown_tool' }
                  },
                  { id: 'unknown_tool', kind: 'step', name: 'Refuse an unknown tool',
                    in: 'tool_call',
                    out: 'tool_result',
                    does: 'A tool that is not listed is refused.',
                    stops: 'The model is told the tool does not exist.'
                  }
                ]
              },
              { id: 'needs_ask', kind: 'decision', name: 'Ask first?',
                test: 'the tool asks every time: fs.delete, shell, or a shell session command',
                branches: { 'yes': 'system.tools.policy.ask', 'otherwise': 'system.tools.policy.run' },
                rules: [ 'fs.read, fs.list, fs.write, fs.edit and fs.patch run without asking' ]
              },
              { id: 'ask', kind: 'step', name: 'Ask the main agent for approval',
                in: 'tool_call',
                out: 'approval_request',
                does: 'Returns an "input required" result with the approval request. The main agent asks the owner and calls again with the answer.'
              },
              { id: 'answer_back', kind: 'decision', name: 'Answer attached?',
                test: 'the answer is allow',
                branches: { 'yes': 'system.tools.deny.check_again', 'otherwise': 'system.tools.policy.refused' }
              },
              { id: 'refused', kind: 'step', name: 'Report the refusal',
                in: 'tool_call',
                out: 'tool_result',
                does: 'The model is told the owner refused the call.',
                stops: 'The model is told the call was refused.'
              },
              { id: 'run', kind: 'step', name: 'Run the tool',
                in: 'tool_call',
                out: 'tool_result',
                does: 'Runs the file tool, or hands the command to the shell, and returns the result.'
              }
            ]
          },
          { id: 'deny', kind: 'group', name: 'Deny list',
            code: 'services/tool_server/src/thursday_tool_server/domain/deny.py',
            does: 'Stops shell commands that must never run, whatever the owner has allowed before.',
            choice: 'A list that approval cannot lift',
            why: 'An "always allow" rule removes the approval for a chat; these commands must not depend on it.',
            rejected: [ 'Confine the shell to the folder: real work needs the real shell', 'Rely on approval alone: a habit of pressing Allow is not a control' ],
            children: [
              { id: 'check_before', kind: 'decision', name: 'On the list?',
                test: 'the command matches the deny list (erasing or partitioning a disk, wiping files, deleting outside the project, changing the firewall or security settings, sending or fetching files over the network, a command that hides its own text)',
                branches: { 'yes': 'system.tools.deny.refuse', 'otherwise': 'system.tools.policy.needs_ask' },
                rules: [ 'Accepted limit: the list reads the command as text and does not see inside a script file. Approval is the control; the list is a backstop to it', 'Installing packages and cloning a repository are not on the list' ]
              },
              { id: 'refuse', kind: 'step', name: 'Refuse the command',
                in: 'tool_call',
                out: 'tool_result',
                does: 'Answers with a tool error that says the rule cannot be approved away. Nobody is asked.',
                stops: 'The model is told the command is refused and cannot be approved.'
              },
              { id: 'check_again', kind: 'decision', name: 'Still not on the list?',
                test: 'the command does not match the deny list when checked again before it runs',
                branches: { 'yes': 'system.tools.policy.run', 'otherwise': 'system.tools.deny.refuse' }
              }
            ]
          },
          { id: 'box', kind: 'group', name: 'Folder boundary',
            code: 'services/tool_server/src/thursday_tool_server/domain/workspace.py',
            does: 'Checks every path given to a file tool. The shell starts in the folder but is not confined to it.',
            choice: 'Confine files, not the shell',
            why: 'Approval and the deny list are the shell\'s controls.',
            children: [
              { id: 'inside', kind: 'decision', name: 'Inside the folder?',
                test: 'the resolved path is inside the project folder (no "..", link, junction, short name or network path leads out)',
                branches: { 'yes': 'system.tools.policy.needs_ask', 'otherwise': 'system.tools.box.outside' }
              },
              { id: 'outside', kind: 'step', name: 'Refuse the path',
                in: 'tool_call',
                out: 'tool_result',
                does: 'A path outside the folder is refused.',
                stops: 'The model is told the path is outside the folder.'
              }
            ]
          },
          { id: 'shell', kind: 'group', name: 'Shell',
            code: 'services/tool_server/src/thursday_tool_server/infrastructure/shell.py',
            does: 'Runs a command in PowerShell, once or in a session that keeps its folder and variables.',
            rules: [ 'Windows PowerShell or PowerShell 7 (pwsh); Linux needs pwsh', 'Output is capped', 'Output is plain text: no colour or terminal codes (PowerShell 7 adds them to errors, even into a pipe)' ],
            children: [
              { id: 'run_once', kind: 'step', name: 'Run the command',
                in: 'tool_call',
                out: 'tool_result',
                does: 'Starts the shell in the project folder and collects the output.'
              },
              { id: 'sessions_full', kind: 'decision', name: 'Too many sessions?',
                test: 'four sessions are already open',
                branches: { 'yes': 'system.tools.shell.too_many', 'otherwise': 'system.tools.shell.run_once' }
              },
              { id: 'too_many', kind: 'step', name: 'Refuse a fifth session',
                in: 'tool_call',
                out: 'tool_result',
                does: 'At most 4 sessions are open.',
                stops: 'The model is told too many sessions are open.'
              },
              { id: 'in_time', kind: 'decision', name: 'In time?',
                test: 'the command finished before its timeout',
                branches: { 'yes': 'system.tools.shell.report', 'otherwise': 'system.tools.shell.kill' }
              },
              { id: 'kill', kind: 'step', name: 'Kill the process tree',
                in: 'tool_call',
                out: 'tool_result',
                does: 'A timeout kills the whole process tree and closes the session.'
              },
              { id: 'report', kind: 'step', name: 'Report the result',
                in: 'tool_result',
                out: 'tool_result',
                does: 'An error that stops the command is reported as exit code 1; a program\'s own code is kept.'
              }
            ]
          },
          { id: 'audit', kind: 'store', name: 'Call log',
            keeps: [ 'tool_call', 'tool_result' ],
            does: 'Records each tool call, the chat it was for, the decision, and how it ended. One SQLite file for each project; cleared with the chat and after the retention period.'
          }
        ]
      },
      { id: 'speech', kind: 'group', name: 'Speech service',
        code: 'services/speech',
        does: 'Turns a recording into text and a reply into audio, on the CPU.',
        children: [
          { id: 'listen', kind: 'group', name: 'Listening',
            does: 'Receives a recording and turns it into words.',
            children: [
              { id: 'recording_in', kind: 'step', name: 'Receive a recording',
                in: 'recording',
                out: 'recording',
                does: 'Takes a recording from the gateway. No audio is stored.',
                choice: 'Push-to-talk only in version 1',
                why: 'Continuous listening needs a design of its own: when to start, when to stop, and what to do about background noise.',
                rejected: [ 'Continuous listening in version 1: not designed, left out' ]
              },
              { id: 'loaded', kind: 'decision', name: 'Engine loaded?',
                test: 'the speech engine for this request is loaded',
                branches: { 'yes': 'system.speech.listen.transcribe', 'otherwise': 'system.speech.listen.load_engine' }
              },
              { id: 'load_engine', kind: 'step', name: 'Load the engine',
                in: 'none',
                out: 'none',
                does: 'Loads the engine, downloading its model files first on first use (about 0.5 GB for Whisper small and 0.35 GB for Kokoro). The first request is slow.'
              },
              { id: 'transcribe', kind: 'step', name: 'Write the words down',
                in: 'recording',
                out: 'transcript',
                does: 'Whisper small (int8) turns the recording into text on the CPU, one request at a time.',
                choice: 'Speech on the CPU',
                why: 'It is fast enough for push-to-talk and leaves the GPU to the models.'
              }
            ]
          },
          { id: 'speak', kind: 'step', name: 'Read the reply aloud',
            in: 'reply',
            out: 'spoken_reply',
            does: 'Kokoro turns the reply text into audio on the CPU, piece by piece, so the voice starts within about half a second.'
          },
          { id: 'idle_unload', kind: 'group', name: 'Idle unload',
            does: 'Drops an engine that nobody has used for a while.',
            children: [
              { id: 'tick', kind: 'event', name: 'Every minute',
                trigger: 'The idle check for the engines fires'
              },
              { id: 'idle', kind: 'decision', name: 'Engine idle?',
                test: 'an engine has not been used for 5 minutes (0 keeps it loaded)',
                branches: { 'yes': 'system.speech.idle_unload.drop_engine', 'otherwise': 'system.speech.idle_unload.keep_engine' }
              },
              { id: 'drop_engine', kind: 'step', name: 'Drop the engine',
                in: 'none',
                out: 'none',
                does: 'Frees the engine\'s memory; it loads again on the next use.',
                stops: 'The memory is free until the next use.'
              },
              { id: 'keep_engine', kind: 'step', name: 'Keep the engine',
                in: 'none',
                out: 'none',
                does: 'The engine stays loaded.',
                stops: 'No change.'
              }
            ]
          },
          { id: 'numbers', kind: 'step', name: 'Answer a request for numbers',
            in: 'none',
            out: 'metrics_sample',
            does: 'Gives the collector this service\'s numbers on /metrics.'
          },
          { id: 'boot', kind: 'step', name: 'Start up and answer health checks',
            in: 'none',
            out: 'none',
            does: 'Starts as a native process on localhost, answers /health and /ready, and exposes its numbers on /metrics.',
            stops: 'The service is running.'
          }
        ]
      },
      { id: 'metrics', kind: 'group', name: 'Metrics collector',
        code: 'services/metrics_collector',
        does: 'Reads the PC\'s CPU, RAM, VRAM and network, asks each service for its numbers, and pushes them to the gateway.',
        children: [
          { id: 'tick', kind: 'event', name: 'Every second',
            trigger: 'The one-second sample timer fires'
          },
          { id: 'read_pc', kind: 'step', name: 'Read the PC',
            in: 'none',
            out: 'metrics_sample',
            does: 'Reads CPU, RAM, VRAM for each card, and network speed.'
          },
          { id: 'scrape', kind: 'step', name: 'Ask each service',
            in: 'none',
            out: 'metrics_sample',
            does: 'Asks the gateway\'s peers (voice agent, main agent, speech) for their numbers.'
          },
          { id: 'answered', kind: 'decision', name: 'Did it answer?',
            test: 'the service answered the request for its numbers',
            branches: { 'yes': 'system.metrics.disk', 'otherwise': 'system.metrics.gap' }
          },
          { id: 'gap', kind: 'step', name: 'Leave a gap',
            in: 'none',
            out: 'metrics_sample',
            does: 'A missed request is a gap in that service\'s numbers; the sample goes on without it.'
          },
          { id: 'disk', kind: 'step', name: 'Measure disk use',
            in: 'metrics_sample',
            out: 'metrics_sample',
            does: 'Measures how much each service keeps on disk, at most once a minute.'
          },
          { id: 'push', kind: 'step', name: 'Push the sample',
            in: 'metrics_sample',
            out: 'metrics_sample',
            does: 'Sends one sample a second to the gateway. The gateway keeps the history.',
            stops: 'The sample is with the gateway.'
          },
          { id: 'boot', kind: 'step', name: 'Start up and answer health checks',
            in: 'none',
            out: 'none',
            does: 'Starts as a native process on localhost, answers /health and /ready, and exposes its numbers on /metrics.',
            stops: 'The service is running.'
          }
        ]
      },
      { id: 'launcher', kind: 'group', name: 'Launcher',
        code: 'launcher',
        does: 'Starts the services, checks their health, restarts one that crashed, stops them all, and downloads the built-in llama.cpp.',
        children: [
          { id: 'command', kind: 'step', name: 'Take a command',
            in: 'request',
            out: 'request',
            does: 'Takes setup, up, down, status or check from the command line.'
          },
          { id: 'setup', kind: 'group', name: 'Setup download',
            does: 'Downloads and checks the built-in llama.cpp.',
            children: [
              { id: 'asks_download', kind: 'decision', name: 'Download llama.cpp?',
                test: 'the owner said yes to the built-in llama.cpp download (about 650 MB)',
                branches: { 'yes': 'system.launcher.setup.fetch', 'otherwise': 'system.launcher.setup.skip' }
              },
              { id: 'skip', kind: 'step', name: 'Skip the download',
                in: 'request',
                out: 'none',
                does: 'A yes is only needed for the built-in llama.cpp; LM Studio and cloud endpoints need nothing.',
                stops: 'Nothing is downloaded.'
              },
              { id: 'fetch', kind: 'step', name: 'Fetch the newest build',
                in: 'request',
                out: 'request',
                does: 'Reads the newest stable release of the official llama.cpp project, picks the build for this PC (CUDA for an NVIDIA card, otherwise Vulkan, otherwise CPU), and downloads it.'
              },
              { id: 'checksum', kind: 'decision', name: 'Checksum matches?',
                test: 'the download matches the SHA-256 that the release publishes',
                branches: { 'yes': 'system.launcher.setup.install', 'otherwise': 'system.launcher.setup.reject' }
              },
              { id: 'reject', kind: 'step', name: 'Reject the download',
                in: 'request',
                out: 'none',
                does: 'A download that does not match is not used.',
                stops: 'Nothing is installed.'
              },
              { id: 'install', kind: 'step', name: 'Install the build',
                in: 'request',
                out: 'none',
                does: 'Puts the build in the data folder.',
                stops: 'The built-in llama.cpp is ready.'
              }
            ]
          },
          { id: 'start_all', kind: 'step', name: 'Start the services',
            in: 'request',
            out: 'none',
            does: 'Starts the gateway, voice agent, main agent, metrics collector and speech service as native processes on localhost, and waits until each is ready.'
          },
          { id: 'watch', kind: 'group', name: 'Watching',
            does: 'Checks each service and restarts one that is not healthy.',
            children: [
              { id: 'tick', kind: 'event', name: 'Health check timer',
                trigger: 'The health check timer fires'
              },
              { id: 'healthy', kind: 'decision', name: 'Healthy?',
                test: 'the service answers its health check',
                branches: { 'yes': 'system.launcher.watch.fine', 'otherwise': 'system.launcher.watch.restart' }
              },
              { id: 'fine', kind: 'step', name: 'Leave it',
                in: 'none',
                out: 'none',
                does: 'The service is healthy.',
                stops: 'No change.'
              },
              { id: 'restart', kind: 'step', name: 'Restart after a delay',
                in: 'none',
                out: 'none',
                does: 'Restarts the service after a delay that doubles from 1 s to 30 s, and resets after 60 s of steady running.'
              }
            ]
          },
          { id: 'stop', kind: 'group', name: 'Stopping',
            does: 'Stops the services and any model server left behind.',
            children: [
              { id: 'stop_all', kind: 'step', name: 'Ask the supervisor to stop',
                in: 'request',
                out: 'none',
                does: '"down" asks the running supervisor to stop its services and waits 20 seconds before stopping what is left. A supervisor is stopped even when none of its services answers.'
              },
              { id: 'is_ours', kind: 'decision', name: 'Thursday\'s own process?',
                test: 'the process is Thursday\'s own',
                branches: { 'yes': 'system.launcher.stop.stop_it', 'otherwise': 'system.launcher.stop.leave_alone' }
              },
              { id: 'stop_it', kind: 'step', name: 'Stop the process',
                in: 'none',
                out: 'none',
                does: 'Stops the service and its child processes, and any model server an agent left running.',
                stops: 'The process is stopped.'
              },
              { id: 'leave_alone', kind: 'step', name: 'Leave the process alone',
                in: 'none',
                out: 'none',
                does: 'Only a process that is Thursday\'s own is ever stopped.',
                stops: 'The process is untouched.'
              }
            ]
          }
        ]
      },
      { id: 'llamacpp', kind: 'group', name: 'Built-in model server',
        code: 'packages/llm/src/thursday_llm/providers/llamacpp',
        does: 'One model server process for each agent that chose it, started for a chosen .gguf file and stopped on unload.',
        children: [
          { id: 'in_folder', kind: 'decision', name: 'Model in the folder?',
            test: 'the model file is inside the chosen models folder',
            branches: { 'yes': 'system.llamacpp.start', 'otherwise': 'system.llamacpp.refuse' }
          },
          { id: 'refuse', kind: 'step', name: 'Refuse the model',
            in: 'model_request',
            out: 'refusal',
            does: 'Only files inside the chosen models folder are loaded.',
            stops: 'The agent is told the model is not in the folder.'
          },
          { id: 'start', kind: 'step', name: 'Start the server',
            in: 'model_request',
            out: 'none',
            does: 'Starts one llama.cpp process for the agent on a free localhost port, with a random key for each run. Across several graphics cards the model is split by layer.',
            choice: 'A process for each agent',
            why: 'A stopped process really frees the GPU.',
            rules: [ 'Accepted limit: running a model across cards in parallel does not load on NVIDIA cards in the build that setup installs. It is a problem in that build and is not worked around here' ]
          },
          { id: 'serve', kind: 'step', name: 'Answer a request',
            in: 'model_request',
            out: 'model_response',
            does: 'Answers over /v1/chat/completions on localhost.'
          },
          { id: 'stop', kind: 'step', name: 'Stop the server',
            in: 'setting',
            out: 'none',
            does: 'Stops the process when the agent unloads, and frees the GPU.',
            stops: 'The GPU is free.'
          }
        ]
      }
      ] },
    { id: 'models', kind: 'external', lane: 'right', name: 'Model servers',
      does: 'LM Studio on the PC, or an OpenAI-compatible endpoint (a cloud service sends data off the PC). Each agent chooses its own.' },
    { id: 'tailscale', kind: 'external', lane: 'right', name: 'Tailscale',
      does: 'Carries the phone\'s HTTPS traffic to the PC. Only needed for the Android app.' },
    { id: 'credstore', kind: 'external', lane: 'right', name: 'System credential store',
      does: 'Keeps each agent\'s API key. Windows Credential Manager, macOS Keychain, or Linux Secret Service.' },
    { id: 'downloads', kind: 'external', lane: 'right', name: 'Download sources',
      does: 'Official llama.cpp releases on GitHub, and the speech model files, fetched on first use.' }
  ],

  links: [
    'owner -> apps : instructions and approvals (ui)',
    'apps -> owner : steps, replies and approvals to answer (ui)',
    { from: 'apps', to: 'system.gateway.clients.doors.local_in', label: 'request', contract: { mode: 'REST /v1 and one WebSocket', timeout: 'see docs/API.md', retry: 'clients reconnect with backoff; sends carry client_message_id' } },
    { from: 'apps', to: 'tailscale', label: 'request from the phone', contract: { mode: 'HTTPS from the phone app', timeout: 'see docs/API.md', retry: 'clients reconnect with backoff' } },
    { from: 'tailscale', to: 'system.gateway.clients.doors.proxy_in', label: 'request', contract: { mode: 'HTTPS to the gateway proxy port', timeout: 'see docs/API.md', retry: 'clients reconnect with backoff' } },
    { from: 'system.gateway.clients.doors.refuse', to: 'apps', label: 'refusal', kind: 'error', contract: { mode: 'HTTP 401, 403 or 409', timeout: 'none', retry: 'the client may send again' } },
    'system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok : request',
    'system.gateway.clients.doors.proxy_in -> system.gateway.clients.doors.proxy_ok : request',
    'system.gateway.clients.doors.route -> system.gateway.clients.doors.pairing.pair_make : request (localhost only) (control)',
    'system.gateway.clients.doors.pairing.pair_make -> system.gateway.clients.doors.pairing.devices : pairing_code (store)',
    'system.gateway.clients.doors.pairing.pair_make -> apps : pairing_code (ui)',
    'system.gateway.clients.doors.pairing.pair_issue -> system.gateway.clients.doors.pairing.devices : device (store)',
    'system.gateway.clients.doors.pairing.pair_issue -> apps : device (ui)',
    'system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept : chat_message',
    'system.gateway.clients.doors.route -> system.gateway.chats.control.send_control : task_control (control)',
    'system.gateway.clients.doors.route -> system.gateway.chats.control.send_answer : approval_answer (control)',
    'system.gateway.clients.doors.route -> system.gateway.settings.pass : setting (config)',
    'system.gateway.clients.doors.route -> system.gateway.settings.key : setting (config)',
    'system.gateway.clients.doors.route -> system.gateway.chats.lifecycle.create : request',
    'system.gateway.clients.doors.route -> system.gateway.chats.lifecycle.begin_delete : request',
    'system.gateway.clients.doors.route -> system.gateway.data.keep.backup.backup_now : request',
    'system.gateway.clients.doors.route -> system.gateway.data.read.answer_read : request',
    'system.gateway.clients.doors.route -> system.gateway.clients.hub.join : request',
    'system.gateway.clients.doors.route -> system.gateway.clients.talk.recording_in : recording',
    'system.gateway.clients.doors.route -> system.gateway.clients.talk.read_aloud : reply',
    'system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room : chat_message',
    'system.gateway.chats.relay.take.accept -> system.gateway.clients.hub.push : message queued (ui)',
    'system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next : chat_message',
    'system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active : chat_message',
    'system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive : chat_message',
    'system.gateway.chats.relay.send.send_direct -> system.voice.conversation.turn.gate.receive : chat_message',
    'system.gateway.chats.relay.send.send_turn -> system.gateway.clients.hub.push : reply text piece by piece (ui)',
    'system.voice.conversation.turn.replay -> system.gateway.chats.relay.send.outcome : reply (result)',
    'system.voice.conversation.turn.store_reply -> system.gateway.chats.relay.send.outcome : reply (result)',
    'system.voice.conversation.spoken.answer -> system.gateway.chats.relay.send.outcome : answered (result)',
    'system.voice.conversation.turn.gate.refuse_gone -> system.gateway.chats.relay.send.outcome : refusal (error)',
    'system.gateway.chats.relay.send.delivered -> system.gateway.clients.hub.push : message delivered (ui)',
    'system.gateway.chats.relay.send.failed -> system.gateway.clients.hub.push : message failed (ui)',
    'system.gateway.chats.relay.take.fail_deleted -> system.gateway.clients.hub.push : message failed: chat deleted (ui)',
    'system.gateway.chats.relay.send.backoff -> system.gateway.chats.relay.take.queue : chat_message (store)',
    'system.gateway.clients.hub.join -> system.gateway.clients.hub.push : event',
    'system.gateway.clients.hub.push -> apps : live events and replies (ui)',
    'system.gateway.settings.pass -> system.voice.llm.change.settings_in : setting (config)',
    'system.gateway.settings.key -> system.voice.llm.change.settings_in : setting (config)',
    'system.gateway.settings.pass -> system.main.llm.change.settings_in : setting (config)',
    'system.gateway.settings.key -> system.main.llm.change.settings_in : setting (config)',
    'system.gateway.chats.control.send_control -> system.main.door.controls.control_in : task_control (control)',
    'system.gateway.chats.control.send_answer -> system.main.door.controls.answer_in : approval_answer (control)',
    'system.main.work.ask.owner_answers.record_answer -> system.gateway.chats.control.answer_taken : approval_answer (result)',
    'system.main.door.controls.resolved -> system.gateway.chats.control.answer_taken : refusal (error)',
    'system.gateway.chats.control.accepted -> apps : answer counted (ui)',
    { from: 'system.gateway.chats.control.conflict', to: 'apps', label: 'refusal', kind: 'error', contract: { mode: 'HTTP 409', timeout: 'none', retry: 'the client reloads the approval' } },
    'system.voice.events.outbox -> system.voice.events.sender : event',
    'system.voice.events.sender -> system.gateway.data.ingest.receive : event (async)',
    'system.main.events.outbox -> system.main.events.sender : event',
    'system.main.events.sender -> system.gateway.data.ingest.receive : event (async)',
    'system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known : event',
    'system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval : event',
    'system.gateway.data.ingest.notify -> system.gateway.data.ingest.project : notification',
    'system.gateway.data.ingest.notify -> system.gateway.clients.hub.push : notification (ui)',
    'system.gateway.data.ingest.project -> system.gateway.data.read.db : event (store)',
    'system.gateway.data.ingest.project -> system.gateway.clients.hub.push : event',
    'system.gateway.data.read.db -> system.gateway.data.read.answer_read : event (store)',
    'system.gateway.data.read.answer_read -> system.gateway.data.read.trace_long : view',
    'system.gateway.data.read.trim -> apps : view (ui)',
    'system.gateway.data.read.whole -> apps : view (ui)',
    'system.gateway.data.read.take_sample -> system.gateway.data.read.db : metrics_sample (store)',
    'system.gateway.data.read.take_sample -> system.gateway.clients.hub.push : live values (ui)',
    'system.metrics.push -> system.gateway.data.read.take_sample : metrics_sample (monitor, async)',
    'system.gateway.chats.lifecycle.create -> system.gateway.data.read.db : project or chat (store)',
    'system.gateway.chats.lifecycle.create -> apps : view (ui)',
    'system.gateway.chats.lifecycle.begin_delete -> system.gateway.chats.control.send_control : stop the tasks of the chat (control)',
    'system.gateway.chats.lifecycle.begin_delete -> system.gateway.chats.relay.take.queue : fail the waiting messages (control)',
    'system.gateway.chats.lifecycle.begin_delete -> system.gateway.chats.lifecycle.ask_agents : request',
    'system.gateway.chats.lifecycle.ask_agents -> system.voice.plumbing.forget : delete the chat (control)',
    'system.gateway.chats.lifecycle.ask_agents -> system.main.plumbing.forget.note_deleted : delete the chat (control)',
    'system.voice.plumbing.forget -> system.gateway.chats.lifecycle.all_done : view (result)',
    'system.main.plumbing.forget.note_deleted -> system.main.plumbing.forget.remove_saved : request',
    'system.main.plumbing.forget.remove_saved -> system.main.plumbing.forget.remove_records : request',
    'system.main.plumbing.forget.remove_records -> system.gateway.chats.lifecycle.all_done : view (result)',
    'system.gateway.chats.lifecycle.wait_retry -> system.gateway.chats.lifecycle.ask_agents : request (control)',
    'system.gateway.chats.lifecycle.remove_own -> system.gateway.data.read.db : remove the chat (store)',
    'system.gateway.chats.lifecycle.remove_own -> apps : view (ui)',
    'system.gateway.status.tick -> system.gateway.status.probe : start the readiness check (control)',
    'system.gateway.status.probe -> system.voice.plumbing.boot : are you ready (monitor)',
    'system.voice.plumbing.boot -> system.gateway.status.two_misses : ready (result)',
    'system.gateway.status.probe -> system.main.plumbing.boot : are you ready (monitor)',
    'system.main.plumbing.boot -> system.gateway.status.two_misses : ready (result)',
    'system.gateway.status.banner -> system.gateway.clients.hub.push : view (ui)',
    'system.gateway.data.keep.minute -> system.gateway.data.keep.send_period : start a round (control)',
    'system.gateway.data.keep.send_period -> system.voice.plumbing.retention : setting (config)',
    'system.voice.plumbing.retention -> system.gateway.data.keep.period_set : setting (result)',
    'system.gateway.data.keep.backup.backup_now -> system.voice.plumbing.backup : copy the chats (control)',
    'system.voice.plumbing.backup -> system.gateway.data.keep.backup.all_copied : view (result)',
    'system.gateway.data.keep.send_period -> system.main.plumbing.retention : setting (config)',
    'system.main.plumbing.retention -> system.gateway.data.keep.period_set : setting (result)',
    'system.gateway.data.keep.backup.backup_now -> system.main.plumbing.backup : copy the chats (control)',
    'system.main.plumbing.backup -> system.gateway.data.keep.backup.all_copied : view (result)',
    'system.gateway.data.keep.purge -> system.gateway.data.read.db : remove old working data (store)',
    'system.gateway.data.keep.backup.backup_now -> system.gateway.data.read.db : copy the chats (store)',
    'system.gateway.data.keep.backup.prune -> apps : view (ui)',
    'system.gateway.data.keep.backup.incomplete -> apps : view (ui)',
    'system.gateway.clients.talk.recording_in -> system.voice.conversation.hear.hear_in : recording',
    'system.voice.conversation.hear.write_down -> system.gateway.clients.talk.heard : transcript (result)',
    'system.voice.conversation.hear.say_409 -> system.gateway.clients.talk.heard : refusal (error)',
    'system.gateway.clients.talk.to_speech -> system.speech.listen.recording_in : recording',
    'system.speech.listen.transcribe -> system.gateway.clients.talk.text_in : transcript (result)',
    'system.gateway.clients.talk.text_in -> system.gateway.chats.relay.take.accept : chat_message',
    'system.gateway.clients.talk.text_in -> apps : what was heard (ui)',
    'system.gateway.clients.talk.read_aloud -> system.speech.speak : reply',
    'system.speech.speak -> system.gateway.clients.talk.play : spoken_reply (result)',
    'system.gateway.clients.talk.play -> apps : spoken_reply (ui)',
    'system.voice.conversation.hear.hear_in -> system.voice.conversation.hear.can_hear : recording',
    'system.voice.conversation.hear.write_down -> system.voice.llm.prepare : model_request',
    'system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone : chat_message',
    'system.voice.conversation.turn.build_view -> system.voice.llm.prepare : model_request',
    'system.voice.conversation.turn.store_reply -> system.voice.store : reply (store)',
    'system.voice.conversation.turn.store_reply -> system.voice.events.outbox : event (store)',
    'system.voice.tasks.delegate.name_request -> system.voice.tasks.delegate.send_task : task_request',
    'system.voice.tasks.delegate.send_task -> system.main.door.tasks.accept : task_request (async)',
    'system.main.door.tasks.create -> system.voice.tasks.delegate.known : task_update (result)',
    'system.main.door.tasks.existing -> system.voice.tasks.delegate.known : task_update (result)',
    'system.voice.tasks.delegate.record -> system.voice.events.outbox : event (store)',
    'system.voice.tasks.delegate.record -> system.voice.llm.prepare : model_request',
    'system.voice.tasks.delegate.control -> system.main.door.controls.control_in : task_control (control)',
    'system.voice.conversation.spoken.answer -> system.main.door.controls.answer_in : approval_answer (control)',
    'system.voice.conversation.spoken.answer -> system.voice.events.outbox : event (store)',
    'system.main.work.loop.finish -> system.voice.tasks.report.check.push_in : task_update (async)',
    'system.main.work.loop.ask_model.fail_task -> system.voice.tasks.report.check.push_in : task_update (async)',
    'system.main.work.loop.cancelled -> system.voice.tasks.report.check.push_in : task_update (async)',
    'system.main.work.ask.ask_owner -> system.voice.tasks.report.check.push_in : task_update (async)',
    'system.main.work.ask.timeout.pause_notify -> system.voice.tasks.report.check.push_in : task_update (async)',
    'system.voice.tasks.report.check.push_in -> system.voice.tasks.report.check.token_ok : task_update',
    'system.voice.tasks.report.narrate -> system.voice.llm.prepare : model_request',
    'system.voice.tasks.report.fallback -> system.voice.tasks.report.say : reply',
    'system.voice.tasks.report.say -> system.voice.events.outbox : event (store)',
    'system.voice.llm.change.settings_in -> system.voice.llm.change.call_running : setting',
    'system.voice.llm.prepare -> system.voice.llm.key_fits : model_request',
    'system.voice.llm.unloading.tick -> system.voice.llm.unloading.idle : start the idle check of the voice agent (control)',
    'system.main.door.tasks.accept -> system.main.door.tasks.chat_exists : task_request',
    'system.main.door.tasks.create -> system.main.state.store : task_request (store)',
    'system.main.door.tasks.create -> system.main.work.line : task_request',
    'system.main.work.line -> system.main.work.loop.prepare.start : task_request',
    'system.main.door.controls.control_in -> system.main.work.loop.prepare.pause_asked : pause or resume (control)',
    'system.main.door.controls.control_in -> system.main.work.loop.cancelled : stop (control)',
    'system.main.door.controls.answer_in -> system.main.door.controls.answer_waiting : approval_answer',
    'system.main.work.loop.cancelled -> system.tools.shell.kill : cancel the running tool (control)',
    'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked : model_request',
    'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.awake : keep the PC awake (control)',
    'system.main.work.loop.prepare.hold -> system.main.events.outbox : event (store)',
    'system.main.work.loop.prepare.compact -> system.main.work.loop.ask_model.call : model_request',
    'system.main.work.loop.prepare.compact -> system.main.events.outbox : event (store)',
    'system.main.work.loop.ask_model.call -> system.main.llm.prepare : model_request',
    'system.main.work.loop.ask_model.compact_harder -> system.main.work.loop.ask_model.call : model_request',
    'system.main.work.loop.ask_model.fail_task -> system.main.events.outbox : event (store)',
    'system.main.work.loop.tools.from_mark -> system.main.work.loop.tools.got_result : tool_result',
    'system.main.work.loop.tools.unknown -> system.main.work.loop.tools.got_result : tool_result',
    'system.main.work.loop.tools.send_call -> system.main.work.mcp.running : tool_call',
    'system.main.work.mcp.start_server -> system.main.work.mcp.call_tool : tool_call',
    'system.main.work.mcp.call_tool -> system.tools.policy.sort.receive : tool_call',
    'system.main.work.mcp.tick -> system.main.work.mcp.idle : start the tool server idle check (control)',
    'system.main.work.loop.tools.got_result -> system.main.work.loop.save : tool_result',
    'system.main.work.loop.save -> system.main.state.checkpoints : model_response (store)',
    'system.main.work.loop.save -> system.main.work.loop.prepare.pause_asked : model_request',
    'system.main.work.loop.finish -> system.main.events.outbox : event (store)',
    'system.main.work.loop.cancelled -> system.main.events.outbox : event (store)',
    'system.main.work.ask.ask_owner -> system.main.events.outbox : event (store)',
    'system.main.work.ask.ask_owner -> system.main.work.ask.owner_answers.answered : approval_request',
    'system.main.work.ask.owner_answers.record_answer -> system.main.work.ask.owner_answers.answered : approval_answer',
    'system.main.work.ask.owner_answers.record_answer -> system.main.state.store : approval_answer (store)',
    'system.main.work.ask.owner_answers.remember -> system.main.state.store : allow-always rule (store)',
    'system.main.work.ask.owner_answers.remember -> system.main.work.ask.owner_answers.resume_call : approval_answer',
    'system.main.work.ask.owner_answers.resume_call -> system.main.work.mcp.call_tool : tool_call',
    'system.main.work.ask.owner_answers.tell_denied -> system.main.work.loop.tools.got_result : tool_result',
    'system.main.work.ask.timeout.time_out -> system.main.work.ask.timeout.two_in_row : tool_result',
    'system.main.work.ask.timeout.pause_notify -> system.main.events.outbox : event (store)',
    'system.main.llm.change.settings_in -> system.main.llm.change.call_running : setting',
    'system.main.llm.prepare -> system.main.llm.key_fits : model_request',
    'system.main.llm.unloading.tick -> system.main.llm.unloading.idle : start the idle check of the main agent (control)',
    'system.main.plumbing.retention -> system.main.state.checkpoints : remove old saved steps (store)',
    'system.voice.plumbing.retention -> system.voice.store : remove old working data (store)',
    'system.voice.llm.change.apply -> system.voice.store : setting (store)',
    'system.voice.llm.change.apply -> system.voice.events.outbox : event (store)',
    { from: 'system.voice.llm.change.apply', to: 'credstore', label: 'typed API key', kind: 'store', contract: { mode: 'keyring library call', timeout: 'none', retry: 'none' } },
    { from: 'system.voice.llm.prepare', to: 'credstore', label: 'read the API key', kind: 'store', contract: { mode: 'keyring library call', timeout: 'none', retry: 'none' } },
    { from: 'system.voice.llm.change.refuse_busy', to: 'apps', label: 'refusal', kind: 'error', contract: { mode: 'HTTP 409', timeout: 'none', retry: 'try again when the call has finished' } },
    { from: 'system.voice.llm.call', to: 'models', label: 'model_request', contract: { mode: 'HTTP, OpenAI-compatible', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    { from: 'system.voice.llm.call_no_key', to: 'models', label: 'model_request', contract: { mode: 'HTTP, OpenAI-compatible', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    'system.voice.llm.call -> system.llamacpp.in_folder : model_request',
    'system.voice.llm.call_no_key -> system.llamacpp.in_folder : model_request',
    { from: 'system.voice.llm.unloading.unload', to: 'models', label: 'unload request', contract: { mode: 'LM Studio native API', timeout: 'see docs/API.md', retry: 'tried again on the next pass' } },
    'system.voice.llm.unloading.unload -> system.llamacpp.stop : setting (control)',
    'system.voice.llm.unloading.unload -> system.voice.events.outbox : event (store)',
    'system.main.llm.change.apply -> system.main.state.store : setting (store)',
    'system.main.llm.change.apply -> system.main.events.outbox : event (store)',
    { from: 'system.main.llm.change.apply', to: 'credstore', label: 'typed API key', kind: 'store', contract: { mode: 'keyring library call', timeout: 'none', retry: 'none' } },
    { from: 'system.main.llm.prepare', to: 'credstore', label: 'read the API key', kind: 'store', contract: { mode: 'keyring library call', timeout: 'none', retry: 'none' } },
    { from: 'system.main.llm.change.refuse_busy', to: 'apps', label: 'refusal', kind: 'error', contract: { mode: 'HTTP 409', timeout: 'none', retry: 'try again when the call has finished' } },
    { from: 'system.main.llm.call', to: 'models', label: 'model_request', contract: { mode: 'HTTP, OpenAI-compatible', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    { from: 'system.main.llm.call_no_key', to: 'models', label: 'model_request', contract: { mode: 'HTTP, OpenAI-compatible', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    'system.main.llm.call -> system.llamacpp.in_folder : model_request',
    'system.main.llm.call_no_key -> system.llamacpp.in_folder : model_request',
    { from: 'system.main.llm.unloading.unload', to: 'models', label: 'unload request', contract: { mode: 'LM Studio native API', timeout: 'see docs/API.md', retry: 'tried again on the next pass' } },
    'system.main.llm.unloading.unload -> system.llamacpp.stop : setting (control)',
    'system.main.llm.unloading.unload -> system.main.events.outbox : event (store)',
    { from: 'models', to: 'system.voice.conversation.turn.hands_over', label: 'model_response', kind: 'result', contract: { mode: 'HTTP stream', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    { from: 'models', to: 'system.voice.tasks.report.report_ok', label: 'model_response', kind: 'result', contract: { mode: 'HTTP stream', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    { from: 'models', to: 'system.voice.conversation.hear.write_down', label: 'model_response', kind: 'result', contract: { mode: 'HTTP stream', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    { from: 'models', to: 'system.main.work.loop.ask_model.call_ok', label: 'model_response', kind: 'result', contract: { mode: 'HTTP stream', timeout: 'see docs/API.md', retry: 'three tries with increasing delays' } },
    'system.llamacpp.start -> system.llamacpp.serve : model_request',
    'system.llamacpp.serve -> system.voice.conversation.turn.hands_over : model_response (result)',
    'system.llamacpp.serve -> system.voice.tasks.report.report_ok : model_response (result)',
    'system.llamacpp.serve -> system.voice.conversation.hear.write_down : model_response (result)',
    'system.llamacpp.serve -> system.main.work.loop.ask_model.call_ok : model_response (result)',
    'system.tools.policy.sort.receive -> system.tools.policy.sort.is_retry : tool_call',
    'system.tools.policy.sort.receive -> system.tools.audit : tool_call (store)',
    'system.tools.policy.ask -> system.main.work.ask.rule_exists : approval_request (control)',
    'system.tools.policy.run -> system.tools.shell.sessions_full : tool_call',
    'system.tools.policy.run -> system.main.work.loop.tools.got_result : tool_result (result)',
    'system.tools.policy.run -> system.tools.audit : tool_result (store)',
    'system.tools.policy.sort.unknown_tool -> system.main.work.loop.tools.got_result : tool_result (error)',
    'system.tools.policy.refused -> system.main.work.loop.tools.got_result : tool_result (error)',
    'system.tools.deny.refuse -> system.main.work.loop.tools.got_result : tool_result (error)',
    'system.tools.box.outside -> system.main.work.loop.tools.got_result : tool_result (error)',
    'system.tools.shell.too_many -> system.main.work.loop.tools.got_result : tool_result (error)',
    'system.tools.shell.kill -> system.main.work.loop.tools.got_result : tool_result (result)',
    'system.tools.shell.report -> system.main.work.loop.tools.got_result : tool_result (result)',
    'system.tools.deny.refuse -> system.tools.audit : tool_result (store)',
    'system.tools.policy.refused -> system.tools.audit : tool_result (store)',
    'system.tools.shell.run_once -> system.tools.shell.in_time : tool_result',
    'system.speech.listen.recording_in -> system.speech.listen.loaded : recording',
    'system.speech.listen.load_engine -> system.speech.listen.transcribe : recording',
    { from: 'system.speech.listen.load_engine', to: 'downloads', label: 'model files, on first use', contract: { mode: 'HTTPS download', timeout: 'see docs/API.md', retry: 'tried again on the next use' } },
    'system.speech.idle_unload.tick -> system.speech.idle_unload.idle : start the engine idle check (control)',
    'system.metrics.tick -> system.metrics.read_pc : start a reading (control)',
    'system.metrics.read_pc -> system.metrics.scrape : metrics_sample',
    'system.metrics.scrape -> system.voice.plumbing.numbers : ask for the numbers (monitor)',
    'system.voice.plumbing.numbers -> system.metrics.answered : metrics_sample (monitor)',
    'system.metrics.scrape -> system.main.plumbing.numbers : ask for the numbers (monitor)',
    'system.main.plumbing.numbers -> system.metrics.answered : metrics_sample (monitor)',
    'system.metrics.scrape -> system.speech.numbers : ask for the numbers (monitor)',
    'system.speech.numbers -> system.metrics.answered : metrics_sample (monitor)',
    'system.metrics.disk -> system.metrics.push : metrics_sample',
    'system.metrics.gap -> system.metrics.push : metrics_sample',
    { from: 'owner', to: 'system.launcher.command', label: 'uv run thursday setup, up, down, status or check', kind: 'control', contract: { mode: 'command line', timeout: 'none', retry: 'run the command again' } },
    'system.launcher.command -> system.launcher.setup.asks_download : setup',
    'system.launcher.command -> system.launcher.start_all : up',
    'system.launcher.command -> system.launcher.stop.stop_all : down',
    { from: 'system.launcher.setup.fetch', to: 'downloads', label: 'the newest llama.cpp build', contract: { mode: 'HTTPS download, checked against the published SHA-256', timeout: 'see docs/API.md', retry: 'run setup again' } },
    'system.launcher.setup.fetch -> system.launcher.setup.checksum : request',
    'system.launcher.stop.stop_all -> system.launcher.stop.is_ours : request',
    'system.launcher.watch.tick -> system.launcher.watch.healthy : start the health checks (control)',
    'system.launcher.start_all -> system.gateway.boot : start the gateway (control)',
    'system.gateway.boot -> system.launcher.watch.healthy : gateway health (result)',
    'system.launcher.watch.restart -> system.gateway.boot : restart the gateway (control)',
    'system.launcher.stop.stop_it -> system.gateway.boot : stop the gateway (control)',
    'system.launcher.start_all -> system.voice.plumbing.boot : start the voice agent (control)',
    'system.voice.plumbing.boot -> system.launcher.watch.healthy : voice agent health (result)',
    'system.launcher.watch.restart -> system.voice.plumbing.boot : restart the voice agent (control)',
    'system.launcher.stop.stop_it -> system.voice.plumbing.boot : stop the voice agent (control)',
    'system.launcher.start_all -> system.main.plumbing.boot : start the main agent (control)',
    'system.main.plumbing.boot -> system.launcher.watch.healthy : main agent health (result)',
    'system.launcher.watch.restart -> system.main.plumbing.boot : restart the main agent (control)',
    'system.launcher.stop.stop_it -> system.main.plumbing.boot : stop the main agent (control)',
    'system.launcher.start_all -> system.speech.boot : start the speech service (control)',
    'system.speech.boot -> system.launcher.watch.healthy : speech service health (result)',
    'system.launcher.watch.restart -> system.speech.boot : restart the speech service (control)',
    'system.launcher.stop.stop_it -> system.speech.boot : stop the speech service (control)',
    'system.launcher.start_all -> system.metrics.boot : start the metrics collector (control)',
    'system.metrics.boot -> system.launcher.watch.healthy : metrics collector health (result)',
    'system.launcher.watch.restart -> system.metrics.boot : restart the metrics collector (control)',
    'system.launcher.stop.stop_it -> system.metrics.boot : stop the metrics collector (control)',
    'system.launcher.stop.stop_it -> system.llamacpp.stop : stop a server left behind (control)',
    'system.launcher.start_all -> system.launcher.watch.tick : begin the health checks (control)',
    'system.voice.tasks.delegate.record -> system.gateway.chats.relay.send.outcome : task id (result)',
    'system.voice.tasks.delegate.already -> system.gateway.chats.relay.send.outcome : task id (result)',
    'system.voice.llm.call -> system.gateway.chats.relay.send.outcome : model unreachable (503) (error)',
    'system.tools.box.outside -> system.tools.audit : tool_result (store)',
    'system.tools.policy.sort.unknown_tool -> system.tools.audit : tool_result (store)',
    'system.main.work.ask.timeout.wait_ends -> system.main.work.ask.owner_answers.answered : the wait is over (control)',
    { from: 'system.gateway.chats.relay.take.refuse_full', to: 'apps', label: 'refusal', kind: 'error', contract: { mode: 'HTTP 429 with Retry-After 30', timeout: 'none', retry: 'the client sends the message again later' } }
  ],

  journeys: [
    { id: 'send_task', name: 'The owner sends an instruction that needs an approval', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.spoken.is_answer -> system.voice.conversation.turn.gate.direct -> system.voice.conversation.turn.seen -> system.voice.conversation.turn.build_view -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.conversation.turn.hands_over -> system.voice.tasks.delegate.name_request -> system.voice.tasks.delegate.send_task -> system.main.door.tasks.accept -> system.main.door.tasks.chat_exists -> system.main.door.tasks.known -> system.main.door.tasks.create -> system.main.work.line -> system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.tools.mark -> system.main.work.loop.tools.send_call -> system.main.work.mcp.running -> system.main.work.mcp.call_tool -> system.tools.policy.sort.receive -> system.tools.policy.sort.is_retry -> system.tools.policy.sort.is_shell -> system.tools.deny.check_before -> system.tools.policy.needs_ask -> system.tools.policy.ask -> system.main.work.ask.rule_exists -> system.main.work.ask.ask_owner -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.notify -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.door.tasks.create -> system.main.state.store',
        'system.main.door.tasks.create -> system.voice.tasks.delegate.known -> system.voice.tasks.delegate.record -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.voice.tasks.delegate.record -> system.voice.llm.prepare',
        'system.tools.policy.sort.receive -> system.tools.audit',
        'system.main.work.ask.ask_owner -> system.voice.tasks.report.check.push_in -> system.voice.tasks.report.check.token_ok -> system.voice.tasks.report.check.chat_alive -> system.voice.tasks.report.narrate -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.tasks.report.report_ok -> system.voice.tasks.report.say -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.voice.tasks.delegate.record -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.delivered -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.chats.relay.take.accept -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.data.ingest.notify -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.data.ingest.project -> system.gateway.data.read.db'
      ],
      notes: { 'system.voice.tasks.delegate.send_task': 'The voice agent hands the work over and returns at once. The main agent pushes updates later.', 'system.main.work.ask.ask_owner': 'The owner is asked; the task lets go of the model while it waits.' } },
    { id: 'answer_approval', name: 'The owner allows a risky step once', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.control.send_answer -> system.main.door.controls.answer_in -> system.main.door.controls.answer_waiting -> system.main.work.ask.owner_answers.record_answer -> system.main.work.ask.owner_answers.answered -> system.main.work.ask.owner_answers.resume_call -> system.main.work.mcp.call_tool -> system.tools.policy.sort.receive -> system.tools.policy.sort.is_retry -> system.tools.policy.answer_back -> system.tools.deny.check_again -> system.tools.policy.run -> system.tools.shell.sessions_full -> system.tools.shell.run_once -> system.tools.shell.in_time -> system.tools.shell.report -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.finish -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.work.ask.owner_answers.record_answer -> system.gateway.chats.control.answer_taken -> system.gateway.chats.control.accepted -> apps -> owner',
        'system.main.work.ask.owner_answers.record_answer -> system.main.state.store',
        'system.main.work.loop.save -> system.main.state.checkpoints',
        'system.tools.policy.run -> system.tools.audit',
        'system.main.work.loop.finish -> system.voice.tasks.report.check.push_in -> system.voice.tasks.report.check.token_ok -> system.voice.tasks.report.check.chat_alive -> system.voice.tasks.report.narrate -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call_no_key -> models -> system.voice.tasks.report.report_ok -> system.voice.tasks.report.fallback -> system.voice.tasks.report.say -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'approve_always', name: 'The owner allows a tool always in this chat', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.control.send_answer -> system.main.door.controls.answer_in -> system.main.door.controls.answer_waiting -> system.main.work.ask.owner_answers.record_answer -> system.main.work.ask.owner_answers.answered -> system.main.work.ask.owner_answers.remember -> system.main.state.store',
        'system.main.work.ask.owner_answers.remember -> system.main.work.ask.owner_answers.resume_call -> system.main.work.mcp.call_tool -> system.tools.policy.sort.receive -> system.tools.audit',
        'system.main.work.ask.rule_exists -> system.main.work.ask.owner_answers.resume_call'
      ] },
    { id: 'deny_approval', name: 'The owner refuses a risky step', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.control.send_answer -> system.main.door.controls.answer_in -> system.main.door.controls.answer_waiting -> system.main.work.ask.owner_answers.record_answer -> system.main.work.ask.owner_answers.answered -> system.main.work.ask.owner_answers.tell_denied -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.state.checkpoints',
        'system.main.work.mcp.call_tool -> system.tools.policy.sort.receive -> system.tools.policy.sort.is_retry -> system.tools.policy.answer_back -> system.tools.policy.refused -> system.main.work.loop.tools.got_result',
        'system.tools.policy.refused -> system.tools.audit'
      ] },
    { id: 'answer_twice', name: 'A second answer to the same approval', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.control.send_answer -> system.main.door.controls.answer_in -> system.main.door.controls.answer_waiting -> system.main.door.controls.resolved -> system.gateway.chats.control.answer_taken -> system.gateway.chats.control.conflict -> apps -> owner'
      ] },
    { id: 'approval_timeout', name: 'Nobody answers an approval in 300 seconds', type: 'timer', paths: [
        'system.main.work.ask.timeout.wait_ends -> system.main.work.ask.owner_answers.answered -> system.main.work.ask.timeout.time_out -> system.main.work.ask.timeout.two_in_row -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.state.checkpoints',
        'system.main.work.ask.timeout.two_in_row -> system.main.work.ask.timeout.pause_notify -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.notify -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.work.ask.timeout.pause_notify -> system.voice.tasks.report.check.push_in -> system.voice.tasks.report.check.token_ok -> system.voice.tasks.report.check.chat_alive -> system.voice.tasks.report.narrate -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.tasks.report.report_ok -> system.voice.tasks.report.say -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.work.ask.ask_owner -> system.main.work.ask.owner_answers.answered'
      ] },
    { id: 'send_direct', name: 'The owner sends words straight to the main agent', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_direct -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.spoken.is_answer -> system.voice.conversation.turn.gate.direct -> system.voice.tasks.delegate.name_request -> system.voice.tasks.delegate.send_task -> system.main.door.tasks.accept -> system.main.door.tasks.chat_exists -> system.main.door.tasks.known -> system.main.door.tasks.create -> system.main.work.line -> system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.finish -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.door.tasks.create -> system.voice.tasks.delegate.known -> system.voice.tasks.delegate.record -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.delivered -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'chat_reply', name: 'The owner chats and the voice agent answers', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.spoken.is_answer -> system.voice.conversation.turn.gate.direct -> system.voice.conversation.turn.seen -> system.voice.conversation.turn.build_view -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.conversation.turn.hands_over -> system.voice.conversation.turn.store_reply -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.delivered -> system.gateway.clients.hub.push -> apps -> owner',
        'system.voice.conversation.turn.store_reply -> system.voice.store',
        'system.voice.conversation.turn.store_reply -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.chats.relay.send.send_turn -> system.gateway.clients.hub.push'
      ] },
    { id: 'spoken_approval', name: 'The owner says yes to a waiting approval', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.spoken.is_answer -> system.voice.conversation.spoken.answer -> system.main.door.controls.answer_in -> system.main.door.controls.answer_waiting -> system.main.work.ask.owner_answers.record_answer -> system.main.state.store',
        'system.voice.conversation.spoken.answer -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.delivered -> system.gateway.clients.hub.push -> apps -> owner',
        'system.voice.conversation.spoken.answer -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'message_repeated', name: 'The same message is sent again', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.spoken.is_answer -> system.voice.conversation.turn.gate.direct -> system.voice.conversation.turn.seen -> system.voice.conversation.turn.replay -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.delivered -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'message_refused', name: 'The voice agent refuses a message for a deleted chat', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.turn.gate.refuse_gone -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.failed -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'chat_deleted_while_waiting', name: 'A waiting message meets a deleted chat', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.take.fail_deleted -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'model_down', name: 'The model server cannot be reached', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.spoken.is_answer -> system.voice.conversation.turn.gate.direct -> system.voice.conversation.turn.seen -> system.voice.conversation.turn.build_view -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.backoff -> system.gateway.chats.relay.take.queue',
        'system.voice.llm.call -> models',
        'system.voice.llm.key_fits -> system.voice.llm.call_no_key -> models',
        'system.main.llm.key_fits -> system.main.llm.call_no_key -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.finish -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'builtin_model', name: 'An agent uses the built-in model server', type: 'user', paths: [
        'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> system.llamacpp.in_folder -> system.llamacpp.start -> system.llamacpp.serve -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.finish -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.llm.call -> system.llamacpp.in_folder -> system.llamacpp.refuse',
        'system.voice.llm.call -> system.llamacpp.in_folder -> system.llamacpp.start -> system.llamacpp.serve -> system.voice.conversation.turn.hands_over -> system.voice.conversation.turn.store_reply -> system.voice.store',
        'system.llamacpp.serve -> system.voice.tasks.report.report_ok -> system.voice.tasks.report.say -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.llamacpp.serve -> system.voice.conversation.hear.write_down -> system.gateway.clients.talk.heard -> system.gateway.clients.talk.text_in -> apps -> owner',
        'system.main.llm.call_no_key -> system.llamacpp.in_folder',
        'system.voice.llm.call_no_key -> system.llamacpp.in_folder'
      ] },
    { id: 'model_failed', name: 'The model call fails or the window is full', type: 'signal', paths: [
        'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.prepare.compact -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.ask_model.compact_harder -> system.main.work.loop.ask_model.call',
        'system.main.work.loop.prepare.compact -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.work.loop.ask_model.call_ok -> system.main.work.loop.ask_model.fail_task -> system.main.events.outbox',
        'system.main.work.loop.ask_model.fail_task -> system.voice.tasks.report.check.push_in -> system.voice.tasks.report.check.token_ok -> system.voice.tasks.report.check.chat_alive -> system.voice.tasks.report.narrate -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.tasks.report.report_ok -> system.voice.tasks.report.say -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.llm.call_no_key -> models -> system.main.work.loop.ask_model.call_ok'
      ] },
    { id: 'pause_task', name: 'The owner pauses a task', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.control.send_control -> system.main.door.controls.control_in -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.hold -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'stop_task', name: 'The owner stops a task', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.control.send_control -> system.main.door.controls.control_in -> system.main.work.loop.cancelled -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.work.loop.cancelled -> system.tools.shell.kill -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.state.checkpoints',
        'system.main.work.loop.cancelled -> system.voice.tasks.report.check.push_in -> system.voice.tasks.report.check.token_ok -> system.voice.tasks.report.check.chat_alive -> system.voice.tasks.report.narrate -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.tasks.report.report_ok -> system.voice.tasks.report.say -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'denied_command', name: 'A command on the deny list is refused', type: 'call', paths: [
        'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.tools.mark -> system.main.work.loop.tools.send_call -> system.main.work.mcp.running -> system.main.work.mcp.call_tool -> system.tools.policy.sort.receive -> system.tools.policy.sort.is_retry -> system.tools.policy.sort.is_shell -> system.tools.deny.check_before -> system.tools.deny.refuse -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.state.checkpoints',
        'system.tools.deny.refuse -> system.tools.audit',
        'system.tools.policy.answer_back -> system.tools.deny.check_again -> system.tools.deny.refuse'
      ] },
    { id: 'file_tool', name: 'A file tool is called', type: 'call', paths: [
        'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.tools.mark -> system.main.work.loop.tools.send_call -> system.main.work.mcp.running -> system.main.work.mcp.call_tool -> system.tools.policy.sort.receive -> system.tools.policy.sort.is_retry -> system.tools.policy.sort.is_shell -> system.tools.policy.sort.is_file -> system.tools.box.inside -> system.tools.policy.needs_ask -> system.tools.policy.run -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.state.checkpoints',
        'system.tools.box.inside -> system.tools.box.outside -> system.main.work.loop.tools.got_result',
        'system.tools.policy.sort.is_file -> system.tools.policy.sort.unknown_tool -> system.main.work.loop.tools.got_result',
        'system.tools.box.outside -> system.tools.audit'
      ] },
    { id: 'shell_limits', name: 'The shell hits a limit', type: 'call', paths: [
        'system.tools.policy.run -> system.tools.shell.sessions_full -> system.tools.shell.too_many -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.state.checkpoints',
        'system.tools.shell.sessions_full -> system.tools.shell.run_once -> system.tools.shell.in_time -> system.tools.shell.kill -> system.main.work.loop.tools.got_result',
        'system.tools.policy.sort.unknown_tool -> system.tools.audit'
      ] },
    { id: 'run_again_after_restart', name: 'A tool call was run before a restart', type: 'signal', paths: [
        'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.fits -> system.main.work.loop.ask_model.call -> system.main.llm.prepare -> system.main.llm.key_fits -> system.main.llm.call -> models -> system.main.work.loop.ask_model.call_ok -> system.main.work.loop.tools.wants_tools -> system.main.work.loop.tools.mark -> system.main.work.loop.tools.from_mark -> system.main.work.loop.tools.got_result -> system.main.work.loop.save -> system.main.state.checkpoints',
        'system.main.work.loop.tools.mark -> system.main.work.loop.tools.unknown -> system.main.work.loop.tools.got_result',
        'system.main.work.loop.prepare.start -> system.main.work.loop.prepare.awake'
      ] },
    { id: 'answer_lost', name: 'The main agent\'s answer is lost, so the request is sent again', type: 'signal', paths: [
        'system.voice.tasks.delegate.send_task -> system.main.door.tasks.accept -> system.main.door.tasks.chat_exists -> system.main.door.tasks.known -> system.main.door.tasks.existing -> system.voice.tasks.delegate.known -> system.voice.tasks.delegate.already -> system.gateway.chats.relay.send.outcome -> system.gateway.chats.relay.send.delivered -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.door.tasks.chat_exists -> system.main.door.tasks.refuse_deleted'
      ] },
    { id: 'task_report', name: 'The main agent reports a task to the voice agent', type: 'call', paths: [
        'system.main.work.loop.finish -> system.voice.tasks.report.check.push_in -> system.voice.tasks.report.check.token_ok -> system.voice.tasks.report.check.reject',
        'system.voice.tasks.report.check.chat_alive -> system.voice.tasks.report.check.drop',
        'system.main.work.loop.finish -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'talk', name: 'The owner talks and the voice model hears', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.clients.talk.recording_in -> system.voice.conversation.hear.hear_in -> system.voice.conversation.hear.can_hear -> system.voice.conversation.hear.write_down -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.conversation.hear.write_down -> system.gateway.clients.talk.heard -> system.gateway.clients.talk.text_in -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.clients.talk.text_in -> apps -> owner'
      ] },
    { id: 'talk_fallback', name: 'The owner talks and Whisper writes the words down', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.clients.talk.recording_in -> system.voice.conversation.hear.hear_in -> system.voice.conversation.hear.can_hear -> system.voice.conversation.hear.say_409 -> system.gateway.clients.talk.heard -> system.gateway.clients.talk.to_speech -> system.speech.listen.recording_in -> system.speech.listen.loaded -> system.speech.listen.transcribe -> system.gateway.clients.talk.text_in -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.gateway.clients.hub.push -> apps -> owner',
        'system.speech.listen.loaded -> system.speech.listen.load_engine -> system.speech.listen.transcribe',
        'system.speech.listen.load_engine -> downloads',
        'system.gateway.clients.talk.text_in -> apps -> owner'
      ] },
    { id: 'read_aloud', name: 'A reply is read aloud', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.clients.talk.read_aloud -> system.speech.speak -> system.gateway.clients.talk.play -> apps -> owner'
      ] },
    { id: 'change_setting', name: 'The owner changes a setting', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.settings.pass -> system.voice.llm.change.settings_in -> system.voice.llm.change.call_running -> system.voice.llm.change.apply -> system.voice.store',
        'system.voice.llm.change.apply -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.settings.pass -> system.main.llm.change.settings_in -> system.main.llm.change.call_running -> system.main.llm.change.apply -> system.main.state.store',
        'system.main.llm.change.apply -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'setting_while_busy', name: 'A setting is saved while the model answers', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.settings.pass -> system.main.llm.change.settings_in -> system.main.llm.change.call_running -> system.main.llm.change.refuse_busy -> apps -> owner',
        'system.gateway.settings.pass -> system.voice.llm.change.settings_in -> system.voice.llm.change.call_running -> system.voice.llm.change.refuse_busy -> apps'
      ] },
    { id: 'save_key', name: 'The owner types an API key', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.settings.key -> system.voice.llm.change.settings_in -> system.voice.llm.change.call_running -> system.voice.llm.change.apply -> credstore',
        'system.gateway.settings.key -> system.main.llm.change.settings_in -> system.main.llm.change.call_running -> system.main.llm.change.apply -> credstore',
        'system.voice.llm.prepare -> credstore',
        'system.main.llm.prepare -> credstore'
      ] },
    { id: 'load_or_unload_model', name: 'The owner unloads a model', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.settings.pass -> system.main.llm.change.settings_in -> system.main.llm.change.call_running -> system.main.llm.change.apply -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'unload_idle_model', name: 'An idle model is unloaded', type: 'timer', paths: [
        'system.voice.llm.unloading.tick -> system.voice.llm.unloading.idle -> system.voice.llm.unloading.unload -> models',
        'system.voice.llm.unloading.unload -> system.llamacpp.stop',
        'system.voice.llm.unloading.unload -> system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.voice.llm.unloading.idle -> system.voice.llm.unloading.stay'
      ] },
    { id: 'unload_idle_main_model', name: 'An idle model of the main agent is unloaded', type: 'timer', paths: [
        'system.main.llm.unloading.tick -> system.main.llm.unloading.idle -> system.main.llm.unloading.unload -> models',
        'system.main.llm.unloading.unload -> system.llamacpp.stop',
        'system.main.llm.unloading.unload -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.main.llm.unloading.idle -> system.main.llm.unloading.stay'
      ] },
    { id: 'idle_engine', name: 'An idle speech engine is dropped', type: 'timer', paths: [
        'system.speech.idle_unload.tick -> system.speech.idle_unload.idle -> system.speech.idle_unload.drop_engine',
        'system.speech.idle_unload.idle -> system.speech.idle_unload.keep_engine'
      ] },
    { id: 'idle_tool_server', name: 'An idle tool server is stopped', type: 'timer', paths: [
        'system.main.work.mcp.tick -> system.main.work.mcp.idle -> system.main.work.mcp.stop_server',
        'system.main.work.mcp.idle -> system.main.work.mcp.keep',
        'system.main.work.mcp.running -> system.main.work.mcp.start_server -> system.main.work.mcp.call_tool -> system.tools.policy.sort.receive -> system.tools.audit'
      ] },
    { id: 'create_chat', name: 'The owner creates a project or chat', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.lifecycle.create -> system.gateway.data.read.db',
        'system.gateway.chats.lifecycle.create -> apps -> owner'
      ] },
    { id: 'delete_chat', name: 'The owner deletes a chat or a project', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.lifecycle.begin_delete -> system.gateway.chats.lifecycle.ask_agents -> system.voice.plumbing.forget -> system.gateway.chats.lifecycle.all_done -> system.gateway.chats.lifecycle.remove_own -> system.gateway.data.read.db',
        'system.gateway.chats.lifecycle.remove_own -> apps -> owner',
        'system.gateway.chats.lifecycle.ask_agents -> system.main.plumbing.forget.note_deleted -> system.main.plumbing.forget.remove_saved -> system.main.plumbing.forget.remove_records -> system.gateway.chats.lifecycle.all_done -> system.gateway.chats.lifecycle.wait_retry -> system.gateway.chats.lifecycle.ask_agents',
        'system.gateway.chats.lifecycle.begin_delete -> system.gateway.chats.control.send_control -> system.main.door.controls.control_in -> system.main.work.loop.cancelled -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.chats.lifecycle.begin_delete -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.take.fail_deleted -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'browse', name: 'The owner reads a trace, searches history or lists chats', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.data.read.answer_read -> system.gateway.data.read.trace_long -> system.gateway.data.read.trim -> apps -> owner',
        'system.gateway.data.read.trace_long -> system.gateway.data.read.whole -> apps',
        'system.gateway.data.read.db -> system.gateway.data.read.answer_read'
      ] },
    { id: 'watch_live', name: 'The owner opens the live stream', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.clients.hub.join -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'pair_phone', name: 'The owner pairs the phone', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.clients.doors.pairing.pair_make -> system.gateway.clients.doors.pairing.devices',
        'system.gateway.clients.doors.pairing.pair_make -> apps -> owner'
      ] },
    { id: 'phone_claims_code', name: 'The phone claims a pairing code', type: 'call', paths: [
        'owner -> apps -> tailscale -> system.gateway.clients.doors.proxy_in -> system.gateway.clients.doors.proxy_ok -> system.gateway.clients.doors.pairing.pair_claim -> system.gateway.clients.doors.pairing.pair_issue -> system.gateway.clients.doors.pairing.devices',
        'system.gateway.clients.doors.pairing.pair_issue -> apps -> owner',
        'system.gateway.clients.doors.pairing.pair_claim -> system.gateway.clients.doors.refuse -> apps'
      ] },
    { id: 'phone_request', name: 'The phone asks the gateway for something', type: 'call', paths: [
        'owner -> apps -> tailscale -> system.gateway.clients.doors.proxy_in -> system.gateway.clients.doors.proxy_ok -> system.gateway.clients.doors.route -> system.gateway.clients.hub.join -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'request_refused', name: 'A call without the right header or token is refused', type: 'call', paths: [
        'apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.refuse -> apps -> owner',
        'owner -> apps -> tailscale -> system.gateway.clients.doors.proxy_in -> system.gateway.clients.doors.proxy_ok -> system.gateway.clients.doors.refuse -> apps'
      ] },
    { id: 'backup_now', name: 'The owner backs up', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.data.keep.backup.backup_now -> system.voice.plumbing.backup -> system.gateway.data.keep.backup.all_copied -> system.gateway.data.keep.backup.prune -> apps -> owner',
        'system.gateway.data.keep.backup.backup_now -> system.main.plumbing.backup -> system.gateway.data.keep.backup.all_copied -> system.gateway.data.keep.backup.incomplete -> apps',
        'system.gateway.data.keep.backup.backup_now -> system.gateway.data.read.db'
      ] },
    { id: 'retention_round', name: 'The gateway repeats the retention period', type: 'timer', paths: [
        'system.gateway.data.keep.minute -> system.gateway.data.keep.send_period -> system.voice.plumbing.retention -> system.gateway.data.keep.period_set -> system.gateway.data.keep.purge -> system.gateway.data.read.db',
        'system.gateway.data.keep.send_period -> system.main.plumbing.retention -> system.gateway.data.keep.period_set -> system.gateway.data.keep.later',
        'system.voice.plumbing.retention -> system.voice.store',
        'system.main.plumbing.retention -> system.main.state.checkpoints'
      ] },
    { id: 'status_check', name: 'The gateway checks that the agents are ready', type: 'timer', paths: [
        'system.gateway.status.tick -> system.gateway.status.probe -> system.voice.plumbing.boot -> system.gateway.status.two_misses -> system.gateway.status.banner -> system.gateway.clients.hub.push -> apps -> owner',
        'system.gateway.status.probe -> system.main.plumbing.boot -> system.gateway.status.two_misses -> system.gateway.status.quiet'
      ] },
    { id: 'metrics_round', name: 'The monitor takes a reading', type: 'timer', paths: [
        'system.metrics.tick -> system.metrics.read_pc -> system.metrics.scrape -> system.voice.plumbing.numbers -> system.metrics.answered -> system.metrics.disk -> system.metrics.push -> system.gateway.data.read.take_sample -> system.gateway.data.read.db',
        'system.gateway.data.read.take_sample -> system.gateway.clients.hub.push -> apps -> owner',
        'system.metrics.scrape -> system.main.plumbing.numbers -> system.metrics.answered -> system.metrics.gap -> system.metrics.push',
        'system.metrics.scrape -> system.speech.numbers -> system.metrics.answered'
      ] },
    { id: 'event_dropped_or_repeated', name: 'An event is dropped or repeated', type: 'data', paths: [
        'system.voice.events.outbox -> system.voice.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.drop',
        'system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.filter.ignore'
      ] },
    { id: 'start_up', name: 'The owner starts everything', type: 'user', paths: [
        'owner -> system.launcher.command -> system.launcher.start_all -> system.gateway.boot',
        'system.launcher.start_all -> system.voice.plumbing.boot',
        'system.launcher.start_all -> system.main.plumbing.boot',
        'system.launcher.start_all -> system.speech.boot',
        'system.launcher.start_all -> system.metrics.boot',
        'system.launcher.start_all -> system.launcher.watch.tick -> system.launcher.watch.healthy -> system.launcher.watch.fine'
      ] },
    { id: 'crash_restart', name: 'A service crashes and the launcher restarts it', type: 'signal', paths: [
        'system.launcher.watch.tick -> system.launcher.watch.healthy -> system.launcher.watch.restart -> system.gateway.boot',
        'system.launcher.watch.restart -> system.voice.plumbing.boot',
        'system.launcher.watch.restart -> system.main.plumbing.boot',
        'system.launcher.watch.restart -> system.speech.boot',
        'system.launcher.watch.restart -> system.metrics.boot',
        'system.launcher.watch.healthy -> system.launcher.watch.fine',
        'system.gateway.boot -> system.launcher.watch.healthy',
        'system.voice.plumbing.boot -> system.launcher.watch.healthy',
        'system.main.plumbing.boot -> system.launcher.watch.healthy',
        'system.speech.boot -> system.launcher.watch.healthy',
        'system.metrics.boot -> system.launcher.watch.healthy'
      ] },
    { id: 'stop_all', name: 'The owner stops everything', type: 'user', paths: [
        'owner -> system.launcher.command -> system.launcher.stop.stop_all -> system.launcher.stop.is_ours -> system.launcher.stop.stop_it -> system.gateway.boot',
        'system.launcher.stop.stop_it -> system.voice.plumbing.boot',
        'system.launcher.stop.stop_it -> system.main.plumbing.boot',
        'system.launcher.stop.stop_it -> system.speech.boot',
        'system.launcher.stop.stop_it -> system.metrics.boot',
        'system.launcher.stop.stop_it -> system.llamacpp.stop',
        'system.launcher.stop.is_ours -> system.launcher.stop.leave_alone'
      ] },
    { id: 'install_llamacpp', name: 'Setup downloads the built-in llama.cpp', type: 'user', paths: [
        'owner -> system.launcher.command -> system.launcher.setup.asks_download -> system.launcher.setup.fetch -> downloads',
        'system.launcher.setup.fetch -> system.launcher.setup.checksum -> system.launcher.setup.install',
        'system.launcher.setup.checksum -> system.launcher.setup.reject',
        'system.launcher.setup.asks_download -> system.launcher.setup.skip'
      ] },
    { id: 'tell_voice_to_pause', name: 'The owner asks the voice agent to pause a task', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.queue -> system.gateway.chats.relay.take.next -> system.gateway.chats.relay.take.active -> system.gateway.chats.relay.send.mode -> system.gateway.chats.relay.send.send_turn -> system.voice.conversation.turn.gate.receive -> system.voice.conversation.turn.gate.chat_gone -> system.voice.conversation.spoken.is_answer -> system.voice.conversation.turn.gate.direct -> system.voice.conversation.turn.seen -> system.voice.conversation.turn.build_view -> system.voice.llm.prepare -> system.voice.llm.key_fits -> system.voice.llm.call -> models -> system.voice.conversation.turn.hands_over -> system.voice.tasks.delegate.control -> system.main.door.controls.control_in -> system.main.work.loop.prepare.pause_asked -> system.main.work.loop.prepare.hold -> system.main.events.outbox -> system.main.events.sender -> system.gateway.data.ingest.receive -> system.gateway.data.ingest.filter.chat_known -> system.gateway.data.ingest.filter.is_new -> system.gateway.data.ingest.store_event -> system.gateway.data.ingest.is_approval -> system.gateway.data.ingest.project -> system.gateway.clients.hub.push -> apps -> owner'
      ] },
    { id: 'queue_full', name: 'A chat already has 100 waiting messages', type: 'user', paths: [
        'owner -> apps -> system.gateway.clients.doors.local_in -> system.gateway.clients.doors.local_ok -> system.gateway.clients.doors.route -> system.gateway.chats.relay.take.accept -> system.gateway.chats.relay.take.room -> system.gateway.chats.relay.take.refuse_full -> apps -> owner'
      ] }
  ]
};
