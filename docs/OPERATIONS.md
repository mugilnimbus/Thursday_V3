# Operations: Setting Up, Running, and Maintaining Thursday

These steps are for Windows 11. The design behind these steps is in [ARCHITECTURE.md](ARCHITECTURE.md), [FLOWS.md](FLOWS.md), and [SECURITY.md](SECURITY.md).

## What you install

| Needed | For | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | All Python services | Installs Python 3.12 itself |
| Node.js 20 or newer | Building the dashboard | |
| A model source | The two agents | LM Studio, or `.gguf` files for the built-in llama.cpp, or an OpenAI-compatible endpoint |
| Tailscale, with HTTPS certificates enabled | The phone | Only if you use the Android app |
| JDK 21 and the Android SDK | Building the Android app | Only if you build the APK yourself; a signed APK is in `apps/android/release/` |

## First setup

Run these from the repository folder, in your own terminal.

```bash
uv sync
```

```bash
uv run thursday setup
```

```bash
npm ci --prefix apps/dashboard
```

```bash
npm run build --prefix apps/dashboard
```

```bash
uv run thursday up
```

What `setup` does:

- Creates `.env` from `.env.example` if it is missing. Other lines are never changed.
- Generates `THURSDAY_SERVICE_TOKEN` if it is empty. The token is never printed.
- Offers the built-in llama.cpp. It reads the newest stable release of the official llama.cpp project, picks the build for this PC, and asks "Download llama.cpp ..., about 650 MB?" (the CUDA build and its runtime libraries on an NVIDIA PC; otherwise the Vulkan build, about 35 MB, or the CPU build). A yes downloads it into the data folder, checks every file against the SHA-256 the release publishes, and unpacks it. A no, or running setup from a script with nobody to ask, downloads nothing. If the download fails, setup says so and the rest still works with LM Studio or a cloud endpoint; run setup again to retry.
- Ends with the requirements check (below).

Setup options:

| Option | Effect |
|---|---|
| `--with-llamacpp` | Download llama.cpp without asking |
| `--skip-llamacpp` | Do not download llama.cpp, and do not ask |
| `--update-llamacpp` | Replace the installed llama.cpp with the newest build (nothing is downloaded if it is already the newest) |

To use your own llama.cpp build instead, set `LLAMACPP_DIR` in `.env` to the folder that holds `llama-server`; setup then downloads nothing.

## The requirements check

```bash
uv run thursday check
```

It lists what Thursday needs on this PC, one line each, marked `ok`, `MISSING` (Thursday will not work fully until it is fixed) or `note` (only needed for a part you may not use), and under anything that is not `ok` it says what to do. It looks at: the `.env` file and the service token; the dashboard build (and Node.js, if it still has to be built, or was not rebuilt after an update); the credential store for API keys; the built-in llama.cpp; an NVIDIA card; Tailscale and whether the gateway is published to your tailnet; the speech models; Thursday's ports; and, while Thursday is running, whether each agent's model source answers. `setup` ends with this list, and `up` prints only the `MISSING` lines before it starts.

## First run

1. Open http://127.0.0.1:8700 on the PC.
2. Go to **Settings, Agents**. For the main agent and then the voice agent:
   - Choose the provider.
   - LM Studio or OpenAI-compatible: enter the endpoint address. Built-in llama.cpp: choose the folder that holds your `.gguf` files (Browse lists the PC's folders).
   - Save. The model list then shows what that provider offers; pick the model and save again.
   - If the endpoint needs a key, type it in the API key box and press Save key.
3. Optional: press **Load** to load the model now. Otherwise it loads the first time it is used. **Unload** frees the hardware, and a model not used for five minutes is unloaded by itself (**Unload when not used for**, per agent; Never keeps it loaded).
4. Under Chats, add a project (a folder on the PC) and send a message.

Nothing is loaded when Thursday starts: no model, no speech engine. The speech models download and load the first time you use the microphone or have a reply read aloud, and are dropped from memory again after five minutes without use (`SPEECH_IDLE_UNLOAD_MINUTES`).

## Everyday commands

| Command | What it does |
|---|---|
| `uv run thursday up` | Starts all services and keeps them running; restarts one that crashes. Leave the terminal open |
| `uv run thursday down` | Stops everything, from any terminal |
| `uv run thursday status` | Checks each service once and prints up or down with its port |
| `uv run thursday check` | Lists what Thursday needs on this PC and what is missing |

Ctrl+C in the `up` terminal also stops everything. `down` also stops any built-in llama.cpp server that an agent left running (one that crashed or was force-stopped), and before `up` starts or restarts an agent it stops that agent's leftover server. Only servers run from Thursday's own llama.cpp folder are ever stopped; LM Studio's are not touched.

## Where things are kept

| What | Where |
|---|---|
| Settings and the service token | `.env` in the repository folder (ignored by git) |
| API keys | Windows Credential Manager, under the name `Thursday`; one entry per agent and provider, for example `main-llm-lmstudio` |
| Databases | `%LOCALAPPDATA%\Thursday\services\<service>\*.sqlite` |
| Logs | `%LOCALAPPDATA%\Thursday\logs\` |
| Built-in llama.cpp | `%LOCALAPPDATA%\Thursday\llamacpp\` |
| Speech models | `%LOCALAPPDATA%\Thursday\services\speech\models\` |
| The built dashboard | `apps/dashboard/dist/` |

Set `THURSDAY_DATA_DIR` in `.env` to keep the data folder somewhere else.

Settings changed on the Settings screens (provider, model, load and answer settings, context limit, prompts, backup schedule, retention) are saved in each service's own database, not in `.env`. The `.env` values are only the starting point; clearing a setting on screen returns it to the `.env` value.

### How long data is kept

Working data is how tasks were done: their steps and traces, the saved state of finished tasks, and the log of tool calls. Settings, General (dashboard) says how long it is kept: 7 days, 30 days, 3 months, 6 months, 1 year, or until you delete it. The starting value is `DATA_RETENTION_DAYS` in `.env` (30; 0 means until you delete it). The choice is applied by every part of Thursday to its own data, about once an hour and when a service starts. Chats and their messages are never removed by age; deleting a chat removes everything about it everywhere.

Monitor shows how much each service keeps on disk and the total. Deleted data leaves the disk when the service next starts: a database of at least 8 MB that is a quarter or more empty is compacted then. If the total stays high after shortening the period, restart Thursday.

## Ports

All services listen on 127.0.0.1 only.

| Port | Service |
|---|---|
| 8700 | Gateway, localhost listener: the dashboard and the trusted API |
| 8701 | Gateway, proxy listener: what `tailscale serve` forwards the phone to; every call needs a device token |
| 8710 | Voice agent |
| 8711 | Main agent |
| 8720 | Metrics collector |
| 8730 | Speech service |
| a free port, chosen at load | Each built-in `llama-server`, with a random key only its agent knows |

Change the fixed ports in `.env` if they clash with something else.

## Logs

Each service writes JSON lines to `%LOCALAPPDATA%\Thursday\logs\<service>.log`, rotated at 10 MB with five older files kept. What a service printed while starting or crashing is in `<service>.stdout.log`. The launcher's own log is `launcher.log`. Each built-in llama.cpp writes `llama-main.log` or `llama-voice.log`; when a model fails to load, the end of that file says why.

Log lines carry the chat, task, and event IDs, so one task can be followed across services. Keys and tokens are never logged.

## The phone

1. Install Tailscale on the PC and the phone, sign both in to the same tailnet, and enable HTTPS certificates in the Tailscale admin console.
2. Publish the gateway's proxy port inside the tailnet:

```bash
tailscale serve --bg http://127.0.0.1:8701
```

3. Install `apps/android/release/Thursday-1.0.0.apk` on the phone.
4. In the dashboard open Settings, Devices and make a pairing code. Scan it with the app.

A phone is removed in Settings, Devices; it is disconnected at once. If the PC's tailnet address is not detected, set `GATEWAY_PUBLIC_URL` in `.env`.

## Updating Thursday

1. Stop it: `uv run thursday down`.
2. Get the new version of the repository.
3. `uv sync` (installs changed Python packages).
4. `npm ci --prefix apps/dashboard`, then `npm run build --prefix apps/dashboard`.
5. `uv run thursday up`. Each service takes a copy of its database before applying a migration.
6. If the Android app changed, install the new APK over the old one. An APK signed with a different key is refused; uninstall the old app first in that case (this forgets the pairing).

To update only llama.cpp: `uv run thursday setup --update-llamacpp`, with the models unloaded.

## Backups

Set a backup folder in Settings, Backup (dashboard), then use **Back up now** or turn on the daily backup. Each run makes a folder `thursday-backup-<date>-<time>` with one sub-folder per service holding copies of its databases, and a `manifest.json` saying what was copied and whether the run was complete. A run is complete when every service copied its chats and projects; a service that was not running makes it partial. The newest copies are kept (seven by default) and older ones removed, except that the newest complete copy always stays, however many partial runs follow it.

A backup holds your chats and projects (transcripts, tasks, settings, and device token hashes): treat the folder as sensitive. It does not hold the Monitor's history, the tool call logs, `.env`, API keys, the llama.cpp build, models, or the Android signing key. Back up the signing key (`apps/android/keystore.properties` and the key file) and `.env` yourself.

To restore:

1. `uv run thursday down`.
2. For each service folder in the backup (`gateway`, `main_agent`, `voice_agent`), copy its `.sqlite` files over the ones in `%LOCALAPPDATA%\Thursday\services\<service>\`, and delete any `-wal` and `-shm` files beside them.
3. `uv run thursday up`.
4. Type the API keys again in Settings if this is a different PC or Windows account.

## Moving to another PC

What git holds comes with a clone. These do not:

| What | Copy it? | Why |
|---|---|---|
| `.env` | Yes | Your settings and the service token |
| `apps/android/keystore.properties` and the key file it names | Yes, if you build the APK | A new APK signed with another key cannot update the installed app |
| `%LOCALAPPDATA%\Thursday\services\` | Yes, to keep chats, tasks, settings and paired phones (or restore a backup instead) | The databases |
| Your `.gguf` models | Yes, if you use the built-in llama.cpp | Large; not downloaded by Thursday |
| API keys | No, type them again | Credential Manager belongs to one Windows account |
| `%LOCALAPPDATA%\Thursday\llamacpp\` and the speech models | No | `setup` downloads the build that suits the new PC; speech models download on first use |
| `.venv`, `apps/dashboard/node_modules`, `apps/dashboard/dist`, `apps/android/app/build` | No | Rebuilt by the first setup steps |

1. On the old PC: `uv run thursday down`.
2. On the new PC: clone the repository, copy the files above into the same places, then run the [first setup](#first-setup) steps.
3. Check the model addresses in Settings, Agents (LM Studio's port, the `.gguf` folder), and type the API keys again.
4. Projects remember their folder path. Put the project folders at the same paths, or add the projects again.
5. For the phone, publish the proxy port again (`tailscale serve --bg http://127.0.0.1:8701`). If the new PC has another Tailscale name, pair the phone again.

## Checks before changing code

| What | Command |
|---|---|
| Python lint and format | `uv run ruff check .` and `uv run ruff format --check .` |
| Python types | `uv run pyright` |
| Python tests, including the layer rule (`tests/test_layers.py`: no import inside a service may point from an inner layer to an outer one) | `uv run pytest -q` |
| Dashboard types | `npm run check --prefix apps/dashboard` |
| Dashboard unit tests | `npm test --prefix apps/dashboard` |
| Dashboard browser tests (needs a build first) | `npm run test:e2e --prefix apps/dashboard` |
| Android tests, build, and lint (from `apps/android`, JDK 21 in `JAVA_HOME`) | `./gradlew :app:testDebugUnitTest :app:assembleDebug :app:lintDebug` |
| Diagrams after editing Mermaid in the pages | `node docs/diagrams/render.mjs` with `MERMAID_JS` set (see [README](README.md#diagrams)) |

The browser tests use Playwright's Chromium; set `THURSDAY_E2E_CHROMIUM` to a `chrome.exe` if it is not installed. After an intended change to a shared message, regenerate the committed schemas with `THURSDAY_UPDATE_SCHEMAS=1 uv run pytest contracts`.

## Troubleshooting

| What you see | Likely cause | What to do |
|---|---|---|
| A service shows DOWN in `thursday status` | It crashed at start | Read `<service>.stdout.log` in the logs folder |
| "Some services could not be stopped" | A process is stuck | Close it in Task Manager, then run `thursday down` again |
| Dashboard page is missing or old | The dashboard was not built after an update | `npm run build --prefix apps/dashboard`, then refresh |
| Agent chip says "endpoint unreachable" | LM Studio's server is not running, or the address is wrong | Start the server in LM Studio; check the Endpoint in Settings |
| Requests are refused with 401 by the model endpoint | No key stored for this agent and provider | Type the key in Settings, Agents |
| Built-in llama.cpp says it is not installed | Setup was skipped or the download failed | `uv run thursday setup` |
| "No model is chosen for this agent" | The provider was switched and no model was picked for it yet | Open Settings, Agents, pick the model from the list, and save |
| Built-in llama.cpp model list is empty | The models folder has no `.gguf` files, or the folder was not saved | Choose the folder, Save, then Refresh list |
| You want the models LM Studio already downloaded | They are in `.lmstudio\models` in your user folder | Press Browse and use the **LM Studio's models** shortcut at the top, or type the path |
| "llama.cpp stopped while loading the model" | Not enough GPU memory, or an unsupported file | Read `llama-main.log` or `llama-voice.log`; try a smaller context length or model |
| GPU memory stays used after `thursday down` | LM Studio still has a model loaded (Thursday stops its own leftover servers, never LM Studio's) | Unload the model in LM Studio, or let Thursday unload it: it does so after the idle time for a model it loaded |
| A model is gone when you come back | It was unloaded after its idle time | Normal: it loads again on the next message. Set **Unload when not used for** to a longer time or to Never in Settings, Agents |
| Two models should each have a card to themselves | By default a model is spread over all the cards | In Settings, Agents set **Graphics cards** to one card for each agent; or keep all cards and set **A model larger than one card** to fill a different card first for each agent |
| A big model is slow on the built-in llama.cpp | Part of it did not fit on the graphics cards and runs on the CPU | Free the cards (unload other models), use all cards (**Graphics cards**: default), a smaller context length, or a smaller model |
| Not sure what is missing | | `uv run thursday check` |
| The model list shows "Save to see the models" | The provider, address, or folder was changed and not saved | Save first |
| A long task loses track of earlier work | The context filled up | Load the model with a larger context length, or set a lower context limit so older turns are summarised sooner |
| The phone says "PC unreachable" | The PC is asleep, Thursday is stopped, or the phone is off the tailnet | Wake the PC, run `thursday up`, check Tailscale on both |
| The phone or tablet says "Cannot find your PC by its name" although Tailscale is on | The device's **Private DNS** names a server of its own (for example an ad blocker's), so the PC's name, which only Tailscale knows, is asked of that server | In the device's settings set Private DNS to Automatic or Off. To keep the ad blocker, set it as the tailnet's nameserver in Tailscale's admin console instead |
| The phone says it was removed | The device was revoked, or the gateway's data changed | Pair again from Settings, Devices on the dashboard |
| The microphone or speaker button reports an error | The speech service is down or a model could not load | Check `speech.log`; the first use downloads the models and needs the internet |
| Pairing address is empty | Tailscale's address was not found | Set `GATEWAY_PUBLIC_URL` in `.env` |

## Removing Thursday

1. `uv run thursday down`.
2. Delete `%LOCALAPPDATA%\Thursday` (databases, logs, llama.cpp, speech models).
3. In Windows Credential Manager remove the `Thursday` entries.
4. `tailscale serve reset` if you published the proxy port.
5. Delete the repository folder, which holds `.env`.
