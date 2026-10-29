# Benchmark

This benchmark measures how fast Thursday itself responds on one PC, with the model taken out of the picture. It does not measure model speed, speech, the tool server shell, or the phone.

## Question

How long do a message, a reply and an event take to cross Thursday, and how much load does it hold before it slows or refuses work?

## Run it

```bash
uv run bench run --quick     # small sizes, one run each: checks that the harness works
uv run bench run             # the full plan below (long: the soak alone is an hour)
uv run bench run --only serial,burst
uv run bench report var/bench/<date>/results.json
uv run bench charts var/bench/<date>/results.json --kill-before <runs>... --kill-after <runs>...   # README charts into docs/images/
```

Stop Thursday first (`uv run thursday down`). The benchmark refuses to start while a stack runs, while a port it needs is in use, or while the PC is busy (CPU over 40%).

## Method

- Each run starts its own copy of the stack: a scratch data folder in `var/bench/<date>/raw/`, ports 187xx, its own service token and its own env file. It never touches the data of a stack you run yourself.
- Both agents call a small fake model server (`thursday_bench/fake_model.py`). It streams one fixed reply of 249 characters in 24 pieces with no delay.
- The harness uses only public interfaces: the client REST API on the gateway's localhost port, the WebSocket stream, `GET /v1/monitor`, and `POST /v1/events` (to fill the history). It never imports service code.
- The services already report resource use, outbox backlog, database size and model timing. The harness reads those values. It measures only what no service reports: what a client sees, and counts.
- Event lag is the time from an event's own `ts` (written by the agent) to the moment the stream message reaches the harness. Both clocks are on the same PC.
- Every run starts a fresh stack. The first messages of a run (5 in workloads 1 to 3, 2 for each chat in workloads 5 and 7) are not counted: they warm the stack up.

## Workloads

| # | Name | Workload | Metrics | Where the number comes from | Target (provisional) |
|---|---|---|---|---|---|
| 1 | `serial` | One chat, one message at a time, 200 messages | `POST` to `202`; p50, p95, p99 | Harness | p95 under 100 ms |
| 2 | `serial` | The same messages | Message to first `chat_delta`; message to final reply | Harness (WebSocket) | p95 under 250 ms to first delta |
| 3 | `serial` | The same messages | Event `ts` to the stream message that carries it | Harness, with the event `ts` | p95 under 250 ms |
| 4 | `burst` | 120 messages into one chat one after another, without waiting for replies | How many are accepted before the first `429`; `Retry-After`; order kept; every accepted message answered | Harness counts | 101 accepted (one in flight and 100 waiting), the rest `429` with `Retry-After: 30`, all answered in order |
| 5 | `many` | 20 chats send at once for 5 minutes | Messages and events per second, error rate, memory of the services, outbox backlog, PC CPU | Harness; `psutil`; `GET /v1/monitor` | no errors, memory flat |
| 6 | `history` | 1,000, 10,000 and 100,000 stored events | Time to page messages, to search chats and to read a timeline page; database growth per 1,000 events; ingest speed | Harness; size of the gateway data folder | reported, no target |
| 7 | `soak` | Workload 5 for 30 minutes; the voice agent is killed (`SIGKILL`) at the half | Gaps and repeats in event numbers, user messages stored twice, shown twice in a chat, errors, time until the agent is back | Harness, from the full event stream and a chat search | 0 lost, 0 repeated |

The targets were guesses. The first full run (2026-10-29) met all of them, so they stay as written. Results are in the main README.

## Inputs

Generated with a fixed seed (`20261029`). The seed and a hash of the fake model's reply are recorded in each result.

## Tools

- A Python harness with `httpx` and `websockets`, because the WebSocket timing needs a client that holds the stream open.
- `psutil` to read the memory of each service process.
- `py-spy` to profile when a target is missed (installed when needed, not part of the harness).

## Runs

| Workload | Measured runs | Why |
|---|---|---|
| `serial`, `burst`, `history` | 5 | Short. |
| `many` | 3 | 5 minutes each. |
| `soak` | 2 | 30 minutes each. |

The report gives the median and the range (smallest to largest) over the runs. A result reproduces when the medians of separate runs stay within 20% of each other. Counts (accepted, refused, repeated, lost) must match exactly.

## Environment recorded with each run

Commit (and whether files were uncommitted), machine, operating system, CPU, memory, Python and library versions, the hash of `uv.lock`, the fake model's reply hash, the seed, and the sizes used.

## Output

- Raw output and logs: `var/bench/<date>/` (ignored): `results.json`, `report.md`, and each run's logs.
- `var/` is disposable. To keep a run, copy its `results.json` and `report.md` out of `var/`.

## Limits

- The fake model answers at once, so these numbers show Thursday's own work. A real model adds its own time to every reply.
- One PC, one operating system, one run of the plan. Numbers from another machine will differ.
- The tool server, speech, the phone and the dashboard are not measured.
